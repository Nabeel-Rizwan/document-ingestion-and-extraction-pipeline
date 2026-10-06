"""PDF extractor.

Handles both digital-text and scanned (OCR) PDFs. Whether a page is text or
OCR is decided per page by :func:`pipeline.extractors.pdf_classifier.classify_page`
during :meth:`plan`, and honoured during :meth:`extract`.
"""

from __future__ import annotations

from PIL import Image

from ..errors import CorruptDocumentError, EmptyDocumentError, EncryptedDocumentError
from ..progress import ProgressReporter, band_progress
from ..schema import Block, ExtractionPlan, ExtractionResult
from .base import describe_extractor
from .pdf_classifier import PageClass, PdfConfig, classify_page


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

    def can_handle(self, probe) -> bool:
        return probe.kind == "pdf"

    def describe(self) -> dict[str, object]:
        return describe_extractor(self)

    # --- planning ---------------------------------------------------------

    def plan(self, probe) -> ExtractionPlan:
        reader = _open_reader(probe)
        page_count = len(reader.pages)
        if page_count == 0:
            raise EmptyDocumentError("The PDF has no pages.")

        strategies: list[str] = []
        for page in reader.pages:
            try:
                text = page.extract_text() or ""
            except Exception:
                text = ""
            strategies.append(classify_page(text, self.config).strategy)

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
        blocks: list[Block] = []
        warnings: list[str] = []
        ocr_confidences: list[float] = []

        try:
            for i, page in enumerate(reader.pages):
                page_no = i + 1
                strategy = strategies[i] if i < len(strategies) else "ocr"
                progress.progress(
                    band_progress("extracting", (i + 1) / max(1, page_count)),
                    f"Page {page_no}/{page_count} ({strategy})",
                )

                if strategy == "text":
                    text = (page.extract_text() or "").strip()
                    blocks.extend(self._paragraph_blocks(text, page_no, method="text"))
                else:
                    image = self._render_page(probe.path, i, page_no)
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

        return ExtractionResult(
            blocks=blocks,
            method=method,
            page_count=page_count,
            warnings=warnings,
            confidence=(sum(ocr_confidences) / len(ocr_confidences)) if ocr_confidences else None,
        )

    # --- helpers ----------------------------------------------------------

    def _render_page(self, path, index: int, page_no: int) -> Image.Image:
        import pypdfium2 as pdfium

        doc = pdfium.PdfDocument(path)
        try:
            page = doc[index]
            try:
                bitmap = page.render(scale=self.config.render_scale)
                try:
                    return bitmap.to_pil()
                finally:
                    bitmap.close()
            finally:
                page.close()
        finally:
            doc.close()

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