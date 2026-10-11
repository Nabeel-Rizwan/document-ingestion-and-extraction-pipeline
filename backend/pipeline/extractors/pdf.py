"""PDF extractor.

Handles both digital-text and scanned (OCR) PDFs. Whether a page is text or
OCR is decided per page by :func:`pipeline.extractors.pdf_classifier.classify_page`
during :meth:`plan`, and honoured during :meth:`extract`.

Text pages are analysed using the PDF's own layout (per-fragment font size,
weight and position) so the output differentiates structure:

* **headings** — lines larger than the body font (level 1 = largest) or short
  bold standalone lines;
* **list items** — lines starting with a bullet glyph or ``1.`` / ``a)`` marker;
* **paragraphs** — everything else, consecutive lines reflowed into one block
  (a paragraph break is inferred from an unusually large vertical gap).
"""

# Defer annotation evaluation (PEP 563).
from __future__ import annotations

# Regular-expression matching for bullet/number markers.
import re
# Statistics helpers for medians and weighted medians.
import statistics
# dataclass gives _Line a compact value type.
from dataclasses import dataclass

# PIL image type for rendered pages passed to OCR.
from PIL import Image

# Domain errors raised for unreadable, empty, or encrypted PDFs; ProgressReporter/band_progress for progress.
from ..errors import CorruptDocumentError, EmptyDocumentError, EncryptedDocumentError
from ..progress import ProgressReporter, band_progress
# Block is one extracted unit; ExtractionPlan/Result are the plan and final value objects.
from ..schema import Block, ExtractionPlan, ExtractionResult
# Shared capability-description helper.
from .base import describe_extractor
# Per-page text/OCR classifier and its configuration/result types.
from .pdf_classifier import PageClass, PdfConfig, classify_page

# A leading bullet (incl. the byte Helvetica emits for U+2022) or an ordered
# marker (``1.``, ``2)``, ``a.``). A whitespace separator is required so we
# never eat a legitimate hyphen/asterisk mid-sentence.
_BULLET_RE = re.compile(r"^[\u2022\u25cf\u25aa\u25e6\u2043\u2219\u00b7*\-\x7f]\s+")
# Ordered-list marker: up to three digits or a single letter followed by "." or ")" and whitespace.
_NUMBER_RE = re.compile(r"^(\d{1,3}|[a-zA-Z])[.)]\s+")

# A line must exceed the body font by this factor to be treated as a size-based heading.
_HEADING_SIZE_RATIO = 1.15
# Upper bound on characters for a size-based heading (long lines are body text).
_MAX_HEADING_CHARS = 120
# Upper bound on characters for a bold standalone heading (kept tighter than size headings).
_MAX_BOLD_HEADING_CHARS = 60


# Immutable record of one reconstructed visual line and its dominant typography.
@dataclass(frozen=True)
class _Line:
    # 1-based page number the line came from.
    page: int
    # Baseline vertical coordinate (PDF user space; larger = higher on the page).
    y: float
    # Normalised text content of the line.
    text: str
    # Dominant font size across the line's fragments.
    size: float
    # True when every non-empty fragment was bold/black/semibold.
    bold: bool


# Opens a PDF with pypdf, transparently decrypting empty-password files.
def _open_reader(probe):
    """Open and decrypt the PDF, mapping pypdf failures to our errors."""
    # Imported lazily so pypdf is only required when a PDF is processed.
    import pypdf
    # PasswordType enumerates the result codes returned by PdfReader.decrypt.
    from pypdf._encryption import PasswordType

    try:
        # Parse the file into a PdfReader.
        reader = pypdf.PdfReader(probe.path)
    # Translate low-level parse failures into our domain error.
    except pypdf.errors.PdfReadError as exc:
        raise CorruptDocumentError(f"Could not read PDF: {exc}") from exc

    # Encrypted PDFs must be decrypted before pages can be read.
    if reader.is_encrypted:
        # Try an empty password (common for owner-only restrictions).
        result = reader.decrypt("")
        # Success is reported as USER_PASSWORD or OWNER_PASSWORD.
        ok = result == PasswordType.USER_PASSWORD or result == PasswordType.OWNER_PASSWORD
        if not ok:
            # Password-protected with a non-empty password: cannot proceed.
            raise EncryptedDocumentError("The PDF is password-protected.")
    # Return the ready-to-use reader.
    return reader


# Detects whether a page has an embedded image XObject without decoding image data.
def _page_has_images(page) -> bool:
    """Cheaply detect an embedded image XObject without decoding it."""
    try:
        # Page resource dictionary lists fonts, XObjects, etc.
        resources = page.get("/Resources")
        if resources is None:
            return False
        # XObject sub-dictionary holds images and form XObjects.
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            return False
        # Resolve the XObject dictionary and inspect each entry.
        for obj in xobjects.get_object().values():
            try:
                # An image XObject declares "/Subtype /Image".
                if obj.get_object().get("/Subtype") == "/Image":
                    return True
            # Skip entries that are not indirect objects or lack a subtype.
            except Exception:
                continue
    # Treat any structural failure as "no images detected".
    except Exception:
        return False
    # Default when nothing matched.
    return False


# Reconstructs text lines with dominant font size/weight from a page's text layer.
def _page_lines(page, page_no: int) -> list[_Line]:
    """Reconstruct visual lines with their dominant font size / weight."""
    # Raw text fragments gathered by the visitor callback.
    fragments: list[dict] = []

    # pypdf calls this for each run of text, giving position and font info.
    def visitor(text, cm, tm, font_dict, font_size):
        # Replace intra-fragment newlines with spaces to keep lines intact.
        piece = (text or "").replace("\n", " ")
        # Ignore whitespace-only fragments.
        if not piece.strip():
            return
        try:
            # Base font name (often encodes weight, e.g. "ABCDEE+Bold").
            name = str((font_dict or {}).get("/BaseFont", ""))
        except Exception:
            # Fall back to an empty name if font_dict is malformed.
            name = ""
        # Lower-cased font name for weight substring checks.
        lowered = name.lower()
        try:
            # tm[5] is the vertical translation (baseline y); tm[4] the horizontal x.
            y = float(tm[5])
            x = float(tm[4])
            # Font size for this fragment (0.0 if unavailable).
            size = float(font_size or 0.0)
        # Skip fragments whose transform/size cannot be interpreted.
        except (TypeError, ValueError, IndexError):
            return
        fragments.append(
            {
                "y": y,
                "x": x,
                "size": size,
                # Infer boldness from common weight markers in the font name.
                "bold": "bold" in lowered or "black" in lowered or "semibold" in lowered,
                "text": piece,
            }
        )

    try:
        # Drive extraction, invoking the visitor per text fragment.
        page.extract_text(visitor_text=visitor)
    except Exception:
        # No usable text layer on this page.
        return []

    # Group fragments into lines by vertical position (2pt tolerance).
    rows: list[dict] = []
    for frag in fragments:
        for row in rows:
            # Same visual line if baselines are within 2 points.
            if abs(row["y"] - frag["y"]) <= 2.0:
                row["frags"].append(frag)
                break
        else:
            # No matching row: start a new line at this fragment's y.
            rows.append({"y": frag["y"], "frags": [frag]})

    # Sort rows top-to-bottom (PDF y grows upward, so descending y).
    rows.sort(key=lambda row: row["y"], reverse=True)
    lines: list[_Line] = []
    for row in rows:
        # Order fragments left-to-right within the row.
        ordered = sorted(row["frags"], key=lambda f: f["x"])
        # Collapse runs of spaces/tabs and join fragments into the line text.
        text = re.sub(r"[ \t]+", " ", "".join(f["text"] for f in ordered)).strip()
        # Skip rows that collapse to empty text.
        if not text:
            continue
        # Dominant size is the largest fragment size in the line.
        size = max(f["size"] for f in ordered)
        # The line is bold only if every non-empty fragment is bold.
        bold = all(f["bold"] for f in ordered if f["text"].strip())
        lines.append(_Line(page=page_no, y=row["y"], text=text, size=size, bold=bold))
    # Return lines in reading order.
    return lines


# Computes a median weighted by per-value integer weights.
def _weighted_median(values: list[float], weights: list[int]) -> float:
    # Pair values with their weights, sorted by value ascending.
    pairs = sorted(zip(values, weights))
    # Total weight across all values.
    total = sum(weights)
    # Degenerate all-zero weights: fall back to the unweighted median.
    if total <= 0:
        return statistics.median(values) if values else 0.0
    # Running cumulative weight.
    acc = 0
    for value, weight in pairs:
        acc += weight
        # First value whose cumulative weight reaches half the total is the weighted median.
        if acc >= total / 2:
            return value
    # Fallback (should be unreachable given the loop above).
    return pairs[-1][0]


# Removes a leading bullet or ordered-list marker from a line of text.
def _strip_marker(text: str) -> str:
    # Prefer a bullet match, otherwise try the ordered-marker pattern.
    match = _BULLET_RE.match(text) or _NUMBER_RE.match(text)
    # Drop the matched prefix when present, else return the text unchanged.
    return text[match.end():].strip() if match else text


class PdfExtractor:
    """Extracts blocks from digital or scanned PDF files."""

    # Identifier used in plans and results.
    name = "pdf"
    # Logical document kind this extractor claims.
    kinds = frozenset({"pdf"})
    # File extension handled.
    extensions = (".pdf",)
    # MIME type served.
    mime_types = ("application/pdf",)

    # Constructs the extractor with an optional OCR client and classification config.
    def __init__(self, ocr=None, config: PdfConfig | None = None) -> None:
        # Local import keeps the mock client out of the module import path.
        from ..ocr.mock import MockOcrClient

        # Default to the mock OCR client when none is supplied.
        self.ocr = ocr or MockOcrClient()
        # Default to standard classification settings.
        self.config = config or PdfConfig()
        # Per-document cache of the page layout (populated during plan() and
        # reused during extract()). The extractor is created fresh per job, so
        # this never leaks across documents; the key includes size+mtime.
        self._layout_cache: tuple[tuple[str, int, int], list[list[_Line]]] | None = None

    # Accepts the file when the probe classified it as a PDF.
    def can_handle(self, probe) -> bool:
        return probe.kind == "pdf"

    # Returns the serialisable capability description for this extractor.
    def describe(self) -> dict[str, object]:
        return describe_extractor(self)

    # --- planning ---------------------------------------------------------

    # Builds a cache key from path, byte size, and nanosecond mtime.
    def _cache_key(self, probe) -> tuple[str, int, int]:
        # Stat the file to obtain its size and modification time.
        stat = probe.path.stat()
        # mtime_ns gives sub-second resolution to detect rewrites.
        return (str(probe.path), stat.st_size, stat.st_mtime_ns)

    # Returns per-page reconstructed lines, computing them only once per file.
    def _page_layouts(self, probe, reader) -> list[list[_Line]]:
        """Analyse each page's layout once, memoised for extract()."""
        # Identity of the current file for cache validation.
        key = self._cache_key(probe)
        # Serve the cached layouts when the same file is unchanged.
        if self._layout_cache is not None and self._layout_cache[0] == key:
            return self._layout_cache[1]
        # Reconstruct lines for every page (1-based page numbers).
        layouts = [_page_lines(page, i + 1) for i, page in enumerate(reader.pages)]
        # Populate the single-entry cache.
        self._layout_cache = (key, layouts)
        # Return the freshly computed layouts.
        return layouts

    # Joins a page's lines back into a newline-separated text blob.
    @staticmethod
    def _page_text(lines: list[_Line]) -> str:
        return "\n".join(line.text for line in lines)

    # Produces the extraction plan: one strategy per page plus a summary.
    def plan(self, probe) -> ExtractionPlan:
        # Open (and possibly decrypt) the PDF.
        reader = _open_reader(probe)
        # Number of pages drives the plan's unit count.
        page_count = len(reader.pages)
        # A PDF with no pages cannot be processed.
        if page_count == 0:
            raise EmptyDocumentError("The PDF has no pages.")

        # Reconstruct each page's layout (also cached for extract()).
        layouts = self._page_layouts(probe, reader)
        # Classify every page using its text, images presence, and config.
        strategies = [
            classify_page(
                self._page_text(lines),
                self.config,
                has_images=_page_has_images(page),
            ).strategy
            for lines, page in zip(layouts, reader.pages)
        ]

        # Count how many pages each strategy was assigned.
        text_pages = strategies.count("text")
        ocr_pages = strategies.count("ocr")
        # Human-readable summary with correct singular/plural wording.
        summary = (
            f"PDF: {text_pages} text page{'s' if text_pages != 1 else ''}, "
            f"{ocr_pages} scanned page{'s' if ocr_pages != 1 else ''}"
        )
        # Annotate when any OCR will occur.
        if ocr_pages:
            summary += " \u2192 OCR"
        # Emit the plan; units equals the page count and strategies is per-page.
        return ExtractionPlan(
            extractor=self.name,
            units=page_count,
            strategies=strategies,
            summary=summary,
        )

    # --- extraction -------------------------------------------------------

    # Runs the plan: text pages are parsed directly, OCR pages are rendered and recognised.
    def extract(
        self,
        probe,
        plan: ExtractionPlan,
        progress: ProgressReporter,
    ) -> ExtractionResult:
        # Imported lazily; still needed here for error handling.
        import pypdf

        # Re-open the PDF for extraction.
        reader = _open_reader(probe)
        # Number of pages to iterate.
        page_count = len(reader.pages)
        # Per-page strategies established during plan().
        strategies = plan.strategies
        # Aggregate method label derived from the per-page strategies.
        method = self._method_for(strategies)
        # Reuse the layout computed during planning (cached).
        layouts = self._page_layouts(probe, reader)
        # Accumulators for output blocks, warnings, and OCR confidences.
        blocks: list[Block] = []
        warnings: list[str] = []
        ocr_confidences: list[float] = []
        # Lazily opened pdfium renderer, shared across all scanned pages.
        pdfium_doc = None

        try:
            for i in range(page_count):
                # 1-based page number for messages and block metadata.
                page_no = i + 1
                # Fall back to "ocr" if the plan is unexpectedly short.
                strategy = strategies[i] if i < len(strategies) else "ocr"
                # Report progress with the page's strategy.
                progress.progress(
                    band_progress("extracting", (i + 1) / max(1, page_count)),
                    f"Page {page_no}/{page_count} ({strategy})",
                )

                # Digital pages reuse the already-reconstructed lines.
                if strategy == "text":
                    lines = layouts[i] if i < len(layouts) else []
                    blocks.extend(self._blocks_from_lines(lines, page_no, method="text"))
                # Scanned pages are rendered to an image and sent to OCR.
                else:
                    if pdfium_doc is None:
                        # Import the renderer only when a scanned page is encountered.
                        import pypdfium2 as pdfium

                        # Open the renderer once for the whole document rather
                        # than re-parsing it for every scanned page.
                        pdfium_doc = pdfium.PdfDocument(str(probe.path))
                    # Rasterise this page at the configured scale.
                    image = self._render_page(pdfium_doc, i)
                    try:
                        # Run OCR on the rendered image.
                        ocr_result = self.ocr.recognize(image, page=page_no)
                    finally:
                        # Always release the image's memory.
                        image.close()
                    # Normalise the recognised text.
                    text = ocr_result.text.strip()
                    # Numeric confidence for aggregation and warnings.
                    confidence = float(ocr_result.confidence)
                    ocr_confidences.append(confidence)
                    # Warn when OCR produced nothing useful.
                    if not text or confidence < self.config.ocr_min_confidence:
                        warnings.append(
                            f"Page {page_no}: OCR result was empty or low confidence "
                            f"({confidence:.2f})."
                        )
                    # Split OCR text into paragraph blocks tagged with method/confidence.
                    blocks.extend(
                        self._paragraph_blocks(
                            text,
                            page_no,
                            method="ocr",
                            confidence=confidence,
                        )
                    )
        # Translate a mid-extraction parse failure into our domain error.
        except pypdf.errors.PdfReadError as exc:
            raise CorruptDocumentError(f"Could not read PDF: {exc}") from exc
        finally:
            # Close the shared renderer if it was opened.
            if pdfium_doc is not None:
                pdfium_doc.close()

        # Final result: average OCR confidence (or None when no OCR ran).
        return ExtractionResult(
            blocks=blocks,
            method=method,
            page_count=page_count,
            warnings=warnings,
            confidence=(sum(ocr_confidences) / len(ocr_confidences)) if ocr_confidences else None,
        )

    # --- helpers ----------------------------------------------------------

    # Renders a single page from an already-open pdfium document into a PIL image.
    def _render_page(self, doc, index: int) -> Image.Image:
        """Render page ``index`` from an already-open pdfium document."""
        # Access the page handle.
        page = doc[index]
        try:
            # Rasterise at the configured scale (higher scale = more pixels for OCR).
            bitmap = page.render(scale=self.config.render_scale)
            try:
                # Convert the bitmap to a PIL image for the OCR client.
                return bitmap.to_pil()
            finally:
                # Free the pdfium bitmap buffer.
                bitmap.close()
        finally:
            # Release the page handle.
            page.close()

    # Converts reconstructed lines into typed blocks, grouping paragraphs.
    def _blocks_from_lines(self, lines: list[_Line], page: int, *, method: str) -> list[Block]:
        """Turn visual lines into typed blocks (heading / list_item / paragraph)."""
        # No lines means no blocks for this page.
        if not lines:
            return []

        # Metadata shared by every block from this page.
        styles: dict = {"method": method}
        # Weight each line by its character count for the weighted median.
        weights = [max(1, len(line.text)) for line in lines]
        # Estimate the body font size from the weighted median of line sizes.
        body = _weighted_median([line.size for line in lines], weights)
        # Guard against a non-positive body size from malformed input.
        if body <= 0:
            body = statistics.median([line.size for line in lines])
        # Distinct heading sizes (largest first) define heading levels 1..N.
        heading_sizes = sorted(
            {line.size for line in lines if line.size > body * _HEADING_SIZE_RATIO},
            reverse=True,
        )
        # Vertical gaps between consecutive lines (positive when moving downward).
        gaps = [prev.y - cur.y for prev, cur in zip(lines, lines[1:])]
        # Typical gap used to detect paragraph breaks.
        median_gap = statistics.median(gaps) if gaps else 0.0

        # Output blocks and the pending paragraph's buffered lines.
        blocks: list[Block] = []
        buffer: list[str] = []

        # Emits the buffered paragraph (if any) as a single block and clears the buffer.
        def flush() -> None:
            if buffer:
                blocks.append(
                    Block(
                        type="paragraph",
                        # Reflow buffered lines into one space-separated paragraph.
                        text=" ".join(buffer).strip(),
                        page=page,
                        metadata=dict(styles),
                    )
                )
                buffer.clear()

        # Previous line, used to measure inter-line gaps.
        prev: _Line | None = None
        for line in lines:
            # Normalised line text.
            text = line.text.strip()
            # Skip blank lines.
            if not text:
                continue

            # Heading when notably larger than body and not too long.
            is_size_heading = (
                line.size > body * _HEADING_SIZE_RATIO and len(text) <= _MAX_HEADING_CHARS
            )
            # Heading when bold, short, not a bullet/number, and not sentence-ending.
            is_bold_heading = (
                line.bold
                and len(text) <= _MAX_BOLD_HEADING_CHARS
                and not _BULLET_RE.match(text)
                and not _NUMBER_RE.match(text)
                and not text.endswith(".")
            )

            # Size-based headings rank by descending font size, capped at level 6.
            if is_size_heading:
                flush()
                level = min(6, heading_sizes.index(line.size) + 1)
                blocks.append(
                    Block(
                        type="heading",
                        text=text,
                        page=page,
                        metadata={**styles, "level": level},
                    )
                )
            # Bold standalone lines become headings ranked below all size headings.
            elif is_bold_heading:
                flush()
                level = min(6, len(heading_sizes) + 1)
                blocks.append(
                    Block(
                        type="heading",
                        text=text,
                        page=page,
                        metadata={**styles, "level": max(1, level)},
                    )
                )
            # Lines starting with a bullet/number are list items (marker stripped).
            elif _BULLET_RE.match(text) or _NUMBER_RE.match(text):
                flush()
                blocks.append(
                    Block(
                        type="list_item",
                        text=_strip_marker(text),
                        page=page,
                        metadata=dict(styles),
                    )
                )
            # Everything else is body text, accumulated into a paragraph.
            else:
                # Detect a paragraph break: an unusually large gap since the previous line.
                broke = (
                    prev is not None
                    and median_gap > 0
                    and (prev.y - line.y) > median_gap * 1.6
                )
                # Close the current paragraph when a break is detected.
                if broke and buffer:
                    flush()
                # Add this line to the current paragraph buffer.
                buffer.append(text)

            # Remember this line for the next gap calculation.
            prev = line

        # Emit any final buffered paragraph.
        flush()
        # Return all blocks for the page.
        return blocks

    # Splits plain text (from OCR) into paragraph blocks on blank lines.
    def _paragraph_blocks(
        self,
        text: str,
        page: int,
        *,
        method: str,
        confidence: float | None = None,
    ) -> list[Block]:
        # Base metadata identifying how the text was obtained.
        metadata: dict = {"method": method}
        # Attach OCR confidence when available.
        if confidence is not None:
            metadata["confidence"] = confidence
        # Split on blank lines and drop empty paragraphs.
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        # Emit one paragraph block per non-empty chunk.
        return [
            Block(type="paragraph", text=p, page=page, metadata=dict(metadata))
            for p in paragraphs
        ]

    # Derives the aggregate method label from the per-page strategies.
    def _method_for(self, strategies: list[str]) -> str:
        # No page strategies: report a generic mixed PDF.
        if not strategies:
            return "pdf_mixed"
        # Whether any page is digital text / any page requires OCR.
        has_text = "text" in strategies
        has_ocr = "ocr" in strategies
        # Both kinds present: mixed document.
        if has_text and has_ocr:
            return "pdf_mixed"
        # OCR only.
        if has_ocr:
            return "pdf_ocr"
        # Text only.
        return "pdf_text"
