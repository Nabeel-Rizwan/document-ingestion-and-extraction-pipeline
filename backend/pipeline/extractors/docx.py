"""DOCX extractor.

Iterates the document body in document order so paragraphs and tables stay
interleaved (``doc.paragraphs`` + ``doc.tables`` would lose that ordering).
Embedded images are OCR'd into text blocks that are inserted where each image
appears in the document, so the image content is searchable too.
"""

# Defer evaluation of annotations (PEP 563) to avoid runtime forward references.
from __future__ import annotations

# BytesIO decodes raw image parts (blobs) into PIL images.
import io

# PIL Image decodes the raw image bytes from the DOCX package.
from PIL import Image

# Raised when python-docx cannot open or parse the file.
from ..errors import CorruptDocumentError
# Fallback OCR client when the extractor is built without an explicit engine.
from ..ocr.mock import MockOcrClient
# ProgressReporter is the callback type; band_progress maps a 0..1 fraction into a named band.
from ..progress import ProgressReporter, band_progress
# Block is one extracted unit; ExtractionPlan/Result are the plan and final value objects.
from ..schema import Block, ExtractionPlan, ExtractionResult
# Shared helper that describes an extractor's capabilities.
from .base import describe_extractor

# Word style names (lower-cased) that indicate a heading, mapped by _heading_level.
_HEADING_STYLES = {"heading 1", "heading 2", "heading 3", "heading 4", "heading 5", "heading 6"}
# Word style names (lower-cased) that indicate a list item.
_LIST_STYLES = {"list bullet", "list number"}

# OPC relationship namespace used by r:embed / r:id attribute references.
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
# Clark-notation attribute key on DrawingML a:blip carrying the embedded image rId.
_BLIP_EMBED_ATTR = f"{{{_REL_NS}}}embed"
# Clark-notation attribute key on VML v:imagedata carrying the embedded image rId.
_IMAGEDATA_ID_ATTR = f"{{{_REL_NS}}}id"
# OCR results below this confidence are reported as warnings instead of blocks.
_OCR_MIN_CONFIDENCE = 0.6


# Maps a Word paragraph style name to a heading level (1..6), or None if not a heading.
def _heading_level(style_name: str) -> int | None:
    # Normalise: guard against None, trim whitespace, and lower-case for comparison.
    name = (style_name or "").strip().lower()
    # The built-in "Title" style is treated as a top-level (level 1) heading.
    if name == "title":
        return 1
    # "Heading N" styles: require a trailing digit to read the level from it.
    if name.startswith("heading ") and name[-1].isdigit():
        return int(name[-1])
    # Anything else is not a heading.
    return None


# Collects the rIds of images embedded anywhere beneath an XML element, in document order.
def _embedded_image_r_ids(element) -> list[str]:
    """Return the relationship ids of images referenced below ``element``."""
    # Deduplicated rIds in first-seen (document) order.
    rids: list[str] = []
    for node in element.iter():
        # Only lxml elements carry a tag; comments/PIs would lack one.
        if not isinstance(node.tag, str):
            continue
        # The local tag name with any namespace prefix stripped off.
        local = node.tag.rsplit("}", 1)[-1]
        # DrawingML a:blip embeds the image via the r:embed attribute.
        if local == "blip":
            rid = node.get(_BLIP_EMBED_ATTR)
        # Legacy VML imagedata references the image via the r:id attribute.
        elif local == "imagedata":
            rid = node.get(_IMAGEDATA_ID_ATTR)
        # Any other element is not an image reference.
        else:
            continue
        # Only add each rId once; the same image may be referenced repeatedly.
        if rid and rid not in rids:
            rids.append(rid)
    return rids


class DocxExtractor:
    # Identifier used in plans and results.
    name = "docx"
    # Logical document kind this extractor claims.
    kinds = frozenset({"docx"})
    # File extensions handled.
    extensions = (".docx",)
    # MIME type served by this extractor.
    mime_types = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    # Accepts the file when the probe classified it as a DOCX.
    def can_handle(self, probe) -> bool:
        return probe.kind == "docx"

    # Constructs the extractor with an optional OCR client for embedded images.
    def __init__(self, ocr=None) -> None:
        # Default to the mock OCR client when none is supplied.
        self.ocr = ocr or MockOcrClient()

    # Returns the serialisable capability description for this extractor.
    def describe(self) -> dict[str, object]:
        return describe_extractor(self)

    # DOCX is a single unit read as digital text; OCR may still run on images.
    def plan(self, probe) -> ExtractionPlan:
        return ExtractionPlan(
            extractor=self.name,
            units=1,
            strategies=["text"],
            summary="DOCX: text, tables and embedded images",
        )

    def extract(
        self,
        probe,
        plan: ExtractionPlan,
        progress: ProgressReporter,
    ) -> ExtractionResult:
        # Imported lazily so python-docx is only required when actually extracting DOCX.
        import docx
        # OPC relationship-type constants used to filter image parts.
        from docx.opc.constants import RELATIONSHIP_TYPE as RT
        # Concrete classes used to wrap raw body XML elements in high-level objects.
        from docx.document import Document as DocxDocument
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        # Signal the start of the opening phase.
        progress.progress(0.0, "Opening DOCX")
        try:
            # Open the package; python-docx does the ZIP/XML parsing here.
            document = docx.Document(str(probe.path))
        except Exception as exc:
            # Preserve our own domain error if it somehow originated here.
            if isinstance(exc, CorruptDocumentError):
                raise
            # Normalise any underlying library failure into our domain error.
            raise CorruptDocumentError(f"Could not open DOCX: {exc}") from exc

        # Accumulators for the output blocks and any non-fatal warnings.
        blocks: list[Block] = []
        warnings: list[str] = []
        # Mean OCR confidence across extracted images (None when there are none).
        ocr_confidences: list[float] = []

        # Resolve every image relationship of the document part by its rId.
        image_parts = {
            rid: rel.target_part
            for rid, rel in document.part.rels.items()
            if rel.reltype == RT.IMAGE
        }
        # rIds whose OCR blocks are ready, reused when the same image recurs.
        image_cache: dict[str, list[Block]] = {}

        # The body element holds paragraphs and tables in document order.
        body = document.element.body
        # Total number of top-level body children, for progress reporting.
        total = len(list(body))
        # Walk each child so paragraphs and tables keep their original interleaving.
        for i, child in enumerate(body):
            # Report incremental progress across the document body.
            progress.progress(band_progress("extracting", (i + 1) / max(1, total)), "Reading document body")

            # Paragraph elements end with "}p" (namespaced tag).
            if child.tag.endswith("}p"):
                # Wrap the raw XML element and expand it into one or more blocks.
                paragraph = Paragraph(child, document)
                blocks.extend(self._paragraph_blocks(paragraph))
            # Table elements end with "}tbl".
            elif child.tag.endswith("}tbl"):
                # Wrap the raw XML element as a Table and emit a single table block.
                table = Table(child, document)
                blocks.append(self._table_block(table))

            # OCR any images embedded beneath this element, in document order.
            for rid in _embedded_image_r_ids(child):
                # Skip images already turned into blocks elsewhere in the doc.
                if rid not in image_cache:
                    # 1-based position of this image among all unique images.
                    image_no = len(image_cache) + 1
                    # Run OCR once and stash the blocks for reuse.
                    image_cache[rid] = self._image_blocks(
                        rid, image_parts, image_no=image_no, warnings=warnings
                    )
                    # Aggregate the first block's confidence when OCR produced text.
                    if image_cache[rid]:
                        ocr_confidences.append(float(image_cache[rid][0].metadata["confidence"]))
                # Insert the image's OCR content where the image appeared.
                blocks.extend(image_cache[rid])

        # Overall confidence is the mean of the image OCR confidences.
        confidence = (sum(ocr_confidences) / len(ocr_confidences)) if ocr_confidences else None

        # DOCX has no pagination in our model, so page_count is null.
        return ExtractionResult(
            blocks=blocks,
            method="docx",
            page_count=None,
            warnings=warnings,
            confidence=confidence,
        )

    # --- helpers ----------------------------------------------------------

    # Converts one DOCX paragraph into zero or more typed blocks.
    def _paragraph_blocks(self, paragraph) -> list[Block]:
        # Style name drives heading/list detection; fall back to "" when unset.
        style_name = paragraph.style.name if paragraph.style is not None else ""
        # Trim surrounding whitespace; empty text yields no block.
        text = paragraph.text.strip()

        # Determine if this paragraph is a heading via its style.
        level = _heading_level(style_name)
        if level is not None:
            # Skip empty heading paragraphs.
            if not text:
                return []
            # Emit a heading block carrying its numeric level in metadata.
            return [Block(type="heading", text=text, metadata={"level": level})]

        # Detect list styles (case-insensitive, trimmed).
        if style_name.strip().lower() in _LIST_STYLES:
            # Skip empty list items.
            if not text:
                return []
            # Emit a list-item block.
            return [Block(type="list_item", text=text, metadata={})]

        # Skip whitespace-only body paragraphs.
        if not text:
            return []
        # Everything else is a plain paragraph block.
        return [Block(type="paragraph", text=text, metadata={})]

    # Converts one DOCX table into a single tab-separated table block.
    def _table_block(self, table) -> Block:
        # Row-major grid of trimmed cell strings.
        rows: list[list[str]] = []
        for row in table.rows:
            # Extract the text of every cell in this row.
            rows.append([cell.text.strip() for cell in row.cells])
        # Serialise rows as newline-separated, tab-joined cells for flat text.
        text = "\n".join("\t".join(r) for r in rows)
        # Keep the structured grid in metadata alongside the flat text.
        return Block(type="table", text=text, metadata={"rows": rows})

    # OCRs one embedded image into one or more text blocks.
    def _image_blocks(
        self,
        rid: str,
        image_parts: dict,
        *,
        image_no: int,
        warnings: list[str],
    ) -> list[Block]:
        """OCR a single embedded image into paragraph blocks.

        A missing, undecodable, or low-confidence image yields a warning rather
        than failing the whole document.
        """
        # Look up the image part referenced by this relationship id.
        part = image_parts.get(rid)
        # A dangling rId (e.g. an external or removed image) contributes nothing.
        if part is None:
            return []
        try:
            # Decode the raw image bytes stored in the DOCX package.
            image = Image.open(io.BytesIO(part.blob))
            # Force full decode so malformed data raises here rather than later.
            image.load()
            # Normalise to RGB so every OCR engine sees a consistent format.
            if image.mode != "RGB":
                image = image.convert("RGB")
        except Exception as exc:
            # A single unreadable image must not abort extraction of the rest.
            warnings.append(f"Embedded image {image_no}: could not be opened for OCR ({exc!r}).")
            return []
        try:
            # DOCX has no page numbers; report page 1 to the OCR client as context.
            ocr_result = self.ocr.recognize(image, page=1)
        finally:
            # Always release the decoded pixel buffer.
            image.close()
        # Normalise the recognised text and its confidence.
        text = ocr_result.text.strip()
        confidence = float(ocr_result.confidence)
        # Empty or low-confidence OCR is flagged but does not fail extraction.
        if not text or confidence < _OCR_MIN_CONFIDENCE:
            warnings.append(
                f"Embedded image {image_no}: OCR result was empty or low confidence "
                f"({confidence:.2f})."
            )
            return []
        # Emit one paragraph block tagged with the OCR method, confidence, and position.
        return [
            Block(
                type="paragraph",
                text=text,
                metadata={"method": "ocr", "confidence": confidence, "image": image_no},
            )
        ]