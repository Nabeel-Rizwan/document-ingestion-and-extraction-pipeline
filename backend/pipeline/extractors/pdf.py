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

from __future__ import annotations

import re
import statistics
from dataclasses import dataclass

from PIL import Image

from ..errors import CorruptDocumentError, EmptyDocumentError, EncryptedDocumentError
from ..progress import ProgressReporter, band_progress
from ..schema import Block, ExtractionPlan, ExtractionResult
from .base import describe_extractor
from .pdf_classifier import PageClass, PdfConfig, classify_page

# A leading bullet (incl. the byte Helvetica emits for U+2022) or an ordered
# marker (``1.``, ``2)``, ``a.``). A whitespace separator is required so we
# never eat a legitimate hyphen/asterisk mid-sentence.
_BULLET_RE = re.compile(r"^[\u2022\u25cf\u25aa\u25e6\u2043\u2219\u00b7*\-\x7f]\s+")
_NUMBER_RE = re.compile(r"^(\d{1,3}|[a-zA-Z])[.)]\s+")

_HEADING_SIZE_RATIO = 1.15
_MAX_HEADING_CHARS = 120
_MAX_BOLD_HEADING_CHARS = 60


@dataclass(frozen=True)
class _Line:
    page: int
    y: float
    text: str
    size: float
    bold: bool


def _open_reader(probe):
    """Open and decrypt the PDF, mapping pypdf failures to our errors."""
    import pypdf
    from pypdf._encryption import PasswordType

    try:
        reader = pypdf.PdfReader(probe.path)
    except pypdf.errors.PdfReadError as exc:
        raise CorruptDocumentError(f"Could not read PDF: {exc}") from exc

    if reader.is_encrypted:
        result = reader.decrypt("")
        ok = result == PasswordType.USER_PASSWORD or result == PasswordType.OWNER_PASSWORD
        if not ok:
            raise EncryptedDocumentError("The PDF is password-protected.")
    return reader


def _page_has_images(page) -> bool:
    """Cheaply detect an embedded image XObject without decoding it."""
    try:
        resources = page.get("/Resources")
        if resources is None:
            return False
        xobjects = resources.get_object().get("/XObject")
        if xobjects is None:
            return False
        for obj in xobjects.get_object().values():
            try:
                if obj.get_object().get("/Subtype") == "/Image":
                    return True
            except Exception:
                continue
    except Exception:
        return False
    return False


def _page_lines(page, page_no: int) -> list[_Line]:
    """Reconstruct visual lines with their dominant font size / weight."""
    fragments: list[dict] = []

    def visitor(text, cm, tm, font_dict, font_size):
        piece = (text or "").replace("\n", " ")
        if not piece.strip():
            return
        try:
            name = str((font_dict or {}).get("/BaseFont", ""))
        except Exception:
            name = ""
        lowered = name.lower()
        try:
            y = float(tm[5])
            x = float(tm[4])
            size = float(font_size or 0.0)
        except (TypeError, ValueError, IndexError):
            return
        fragments.append(
            {
                "y": y,
                "x": x,
                "size": size,
                "bold": "bold" in lowered or "black" in lowered or "semibold" in lowered,
                "text": piece,
            }
        )

    try:
        page.extract_text(visitor_text=visitor)
    except Exception:
        return []

    # Group fragments into lines by vertical position (2pt tolerance).
    rows: list[dict] = []
    for frag in fragments:
        for row in rows:
            if abs(row["y"] - frag["y"]) <= 2.0:
                row["frags"].append(frag)
                break
        else:
            rows.append({"y": frag["y"], "frags": [frag]})

    rows.sort(key=lambda row: row["y"], reverse=True)
    lines: list[_Line] = []
    for row in rows:
        ordered = sorted(row["frags"], key=lambda f: f["x"])
        text = re.sub(r"[ \t]+", " ", "".join(f["text"] for f in ordered)).strip()
        if not text:
            continue
        size = max(f["size"] for f in ordered)
        bold = all(f["bold"] for f in ordered if f["text"].strip())
        lines.append(_Line(page=page_no, y=row["y"], text=text, size=size, bold=bold))
    return lines


def _weighted_median(values: list[float], weights: list[int]) -> float:
    pairs = sorted(zip(values, weights))
    total = sum(weights)
    if total <= 0:
        return statistics.median(values) if values else 0.0
    acc = 0
    for value, weight in pairs:
        acc += weight
        if acc >= total / 2:
            return value
    return pairs[-1][0]


def _strip_marker(text: str) -> str:
    match = _BULLET_RE.match(text) or _NUMBER_RE.match(text)
    return text[match.end():].strip() if match else text


class PdfExtractor:
    """Extracts blocks from digital or scanned PDF files."""

    name = "pdf"
    kinds = frozenset({"pdf"})
    extensions = (".pdf",)
    mime_types = ("application/pdf",)

    def __init__(self, ocr=None, config: PdfConfig | None = None) -> None:
        from ..ocr.mock import MockOcrClient

        self.ocr = ocr or MockOcrClient()
        self.config = config or PdfConfig()
        # Per-document cache of the page layout (populated during plan() and
        # reused during extract()). The extractor is created fresh per job, so
        # this never leaks across documents; the key includes size+mtime.
        self._layout_cache: tuple[tuple[str, int, int], list[list[_Line]]] | None = None

    def can_handle(self, probe) -> bool:
        return probe.kind == "pdf"

    def describe(self) -> dict[str, object]:
        return describe_extractor(self)

    # --- planning ---------------------------------------------------------

    def _cache_key(self, probe) -> tuple[str, int, int]:
        stat = probe.path.stat()
        return (str(probe.path), stat.st_size, stat.st_mtime_ns)

    def _page_layouts(self, probe, reader) -> list[list[_Line]]:
        """Analyse each page's layout once, memoised for extract()."""
        key = self._cache_key(probe)
        if self._layout_cache is not None and self._layout_cache[0] == key:
            return self._layout_cache[1]
        layouts = [_page_lines(page, i + 1) for i, page in enumerate(reader.pages)]
        self._layout_cache = (key, layouts)
        return layouts

    @staticmethod
    def _page_text(lines: list[_Line]) -> str:
        return "\n".join(line.text for line in lines)

    def plan(self, probe) -> ExtractionPlan:
        reader = _open_reader(probe)
        page_count = len(reader.pages)
        if page_count == 0:
            raise EmptyDocumentError("The PDF has no pages.")

        layouts = self._page_layouts(probe, reader)
        strategies = [
            classify_page(
                self._page_text(lines),
                self.config,
                has_images=_page_has_images(page),
            ).strategy
            for lines, page in zip(layouts, reader.pages)
        ]

        text_pages = strategies.count("text")
        ocr_pages = strategies.count("ocr")
        summary = (
            f"PDF: {text_pages} text page{'s' if text_pages != 1 else ''}, "
            f"{ocr_pages} scanned page{'s' if ocr_pages != 1 else ''}"
        )
        if ocr_pages:
            summary += " \u2192 OCR"
        return ExtractionPlan(
            extractor=self.name,
            units=page_count,
            strategies=strategies,
            summary=summary,
        )

    # --- extraction -------------------------------------------------------

    def extract(
        self,
        probe,
        plan: ExtractionPlan,
        progress: ProgressReporter,
    ) -> ExtractionResult:
        import pypdf

        reader = _open_reader(probe)
        page_count = len(reader.pages)
        strategies = plan.strategies
        method = self._method_for(strategies)
        layouts = self._page_layouts(probe, reader)
        blocks: list[Block] = []
        warnings: list[str] = []
        ocr_confidences: list[float] = []
        pdfium_doc = None

        try:
            for i in range(page_count):
                page_no = i + 1
                strategy = strategies[i] if i < len(strategies) else "ocr"
                progress.progress(
                    band_progress("extracting", (i + 1) / max(1, page_count)),
                    f"Page {page_no}/{page_count} ({strategy})",
                )

                if strategy == "text":
                    lines = layouts[i] if i < len(layouts) else []
                    blocks.extend(self._blocks_from_lines(lines, page_no, method="text"))
                else:
                    if pdfium_doc is None:
                        import pypdfium2 as pdfium

                        # Open the renderer once for the whole document rather
                        # than re-parsing it for every scanned page.
                        pdfium_doc = pdfium.PdfDocument(str(probe.path))
                    image = self._render_page(pdfium_doc, i)
                    try:
                        ocr_result = self.ocr.recognize(image, page=page_no)
                    finally:
                        image.close()
                    text = ocr_result.text.strip()
                    confidence = float(ocr_result.confidence)
                    ocr_confidences.append(confidence)
                    if not text or confidence < self.config.ocr_min_confidence:
                        warnings.append(
                            f"Page {page_no}: OCR result was empty or low confidence "
                            f"({confidence:.2f})."
                        )
                    blocks.extend(
                        self._paragraph_blocks(
                            text,
                            page_no,
                            method="ocr",
                            confidence=confidence,
                        )
                    )
        except pypdf.errors.PdfReadError as exc:
            raise CorruptDocumentError(f"Could not read PDF: {exc}") from exc
        finally:
            if pdfium_doc is not None:
                pdfium_doc.close()

        return ExtractionResult(
            blocks=blocks,
            method=method,
            page_count=page_count,
            warnings=warnings,
            confidence=(sum(ocr_confidences) / len(ocr_confidences)) if ocr_confidences else None,
        )

    # --- helpers ----------------------------------------------------------

    def _render_page(self, doc, index: int) -> Image.Image:
        """Render page ``index`` from an already-open pdfium document."""
        page = doc[index]
        try:
            bitmap = page.render(scale=self.config.render_scale)
            try:
                return bitmap.to_pil()
            finally:
                bitmap.close()
        finally:
            page.close()

    def _blocks_from_lines(self, lines: list[_Line], page: int, *, method: str) -> list[Block]:
        """Turn visual lines into typed blocks (heading / list_item / paragraph)."""
        if not lines:
            return []

        styles: dict = {"method": method}
        weights = [max(1, len(line.text)) for line in lines]
        body = _weighted_median([line.size for line in lines], weights)
        if body <= 0:
            body = statistics.median([line.size for line in lines])
        heading_sizes = sorted(
            {line.size for line in lines if line.size > body * _HEADING_SIZE_RATIO},
            reverse=True,
        )
        gaps = [prev.y - cur.y for prev, cur in zip(lines, lines[1:])]
        median_gap = statistics.median(gaps) if gaps else 0.0

        blocks: list[Block] = []
        buffer: list[str] = []

        def flush() -> None:
            if buffer:
                blocks.append(
                    Block(
                        type="paragraph",
                        text=" ".join(buffer).strip(),
                        page=page,
                        metadata=dict(styles),
                    )
                )
                buffer.clear()

        prev: _Line | None = None
        for line in lines:
            text = line.text.strip()
            if not text:
                continue

            is_size_heading = (
                line.size > body * _HEADING_SIZE_RATIO and len(text) <= _MAX_HEADING_CHARS
            )
            is_bold_heading = (
                line.bold
                and len(text) <= _MAX_BOLD_HEADING_CHARS
                and not _BULLET_RE.match(text)
                and not _NUMBER_RE.match(text)
                and not text.endswith(".")
            )

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
            else:
                broke = (
                    prev is not None
                    and median_gap > 0
                    and (prev.y - line.y) > median_gap * 1.6
                )
                if broke and buffer:
                    flush()
                buffer.append(text)

            prev = line

        flush()
        return blocks

    def _paragraph_blocks(
        self,
        text: str,
        page: int,
        *,
        method: str,
        confidence: float | None = None,
    ) -> list[Block]:
        metadata: dict = {"method": method}
        if confidence is not None:
            metadata["confidence"] = confidence
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return [
            Block(type="paragraph", text=p, page=page, metadata=dict(metadata))
            for p in paragraphs
        ]

    def _method_for(self, strategies: list[str]) -> str:
        if not strategies:
            return "pdf_mixed"
        has_text = "text" in strategies
        has_ocr = "ocr" in strategies
        if has_text and has_ocr:
            return "pdf_mixed"
        if has_ocr:
            return "pdf_ocr"
        return "pdf_text"
