"""DOCX extractor.

Iterates the document body in document order so paragraphs and tables stay
interleaved (``doc.paragraphs`` + ``doc.tables`` would lose that ordering).
"""

from __future__ import annotations

from ..errors import CorruptDocumentError
from ..progress import ProgressReporter, band_progress
from ..schema import Block, ExtractionPlan, ExtractionResult
from .base import describe_extractor

_HEADING_STYLES = {"heading 1", "heading 2", "heading 3", "heading 4", "heading 5", "heading 6"}
_LIST_STYLES = {"list bullet", "list number"}


def _heading_level(style_name: str) -> int | None:
    name = (style_name or "").strip().lower()
    if name == "title":
        return 1
    if name.startswith("heading ") and name[-1].isdigit():
        return int(name[-1])
    return None


def _count_images(doc) -> int:
    xml = doc.element.xml
    return xml.count("w:drawing") + xml.count("w:pict")


class DocxExtractor:
    name = "docx"
    kinds = frozenset({"docx"})
    extensions = (".docx",)
    mime_types = (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    def can_handle(self, probe) -> bool:
        return probe.kind == "docx"

    def describe(self) -> dict[str, object]:
        return describe_extractor(self)

    def plan(self, probe) -> ExtractionPlan:
        return ExtractionPlan(
            extractor=self.name,
            units=1,
            strategies=["text"],
            summary="DOCX: text and tables in document order",
        )

    def extract(
        self,
        probe,
        plan: ExtractionPlan,
        progress: ProgressReporter,
    ) -> ExtractionResult:
        import docx
        from docx.document import Document as DocxDocument
        from docx.table import Table
        from docx.text.paragraph import Paragraph

        progress.progress(0.0, "Opening DOCX")
        try:
            document = docx.Document(str(probe.path))
        except Exception as exc:
            if isinstance(exc, CorruptDocumentError):
                raise
            raise CorruptDocumentError(f"Could not open DOCX: {exc}") from exc

        blocks: list[Block] = []
        warnings: list[str] = []

        body = document.element.body
        total = len(list(body))
        for i, child in enumerate(body):
            progress.progress(band_progress("extracting", (i + 1) / max(1, total)), "Reading document body")

            if child.tag.endswith("}p"):
                paragraph = Paragraph(child, document)
                blocks.extend(self._paragraph_blocks(paragraph))
            elif child.tag.endswith("}tbl"):
                table = Table(child, document)
                blocks.append(self._table_block(table))

        image_count = _count_images(document)
        if image_count:
            warnings.append(
                f"{image_count} embedded image{'s' if image_count != 1 else ''} "
                f"were not extracted."
            )

        return ExtractionResult(
            blocks=blocks,
            method="docx",
            page_count=None,
            warnings=warnings,
            confidence=None,
        )

    # --- helpers ----------------------------------------------------------

    def _paragraph_blocks(self, paragraph) -> list[Block]:
        style_name = paragraph.style.name if paragraph.style is not None else ""
        text = paragraph.text.strip()

        level = _heading_level(style_name)
        if level is not None:
            if not text:
                return []
            return [Block(type="heading", text=text, metadata={"level": level})]

        if style_name.strip().lower() in _LIST_STYLES:
            if not text:
                return []
            return [Block(type="list_item", text=text, metadata={})]

        if not text:
            return []
        return [Block(type="paragraph", text=text, metadata={})]

    def _table_block(self, table) -> Block:
        rows: list[list[str]] = []
        for row in table.rows:
            rows.append([cell.text.strip() for cell in row.cells])
        text = "\n".join("\t".join(r) for r in rows)
        return Block(type="table", text=text, metadata={"rows": rows})