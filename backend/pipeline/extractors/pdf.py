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
        # Per-document cache of the text layer, populated during plan() and
        # reused during extract() so pages are not text-extracted twice.
        # The extractor is created fresh per job, so this never leaks across
        # documents; the key includes size+mtime to be safe.
        self._text_cache: tuple[tuple[str, int, int], list[str]] | None = None

    def can_handle(self, probe) -> bool:
        return probe.kind == "pdf"

    def describe(self) -> dict[str, object]:
        return describe_extractor(self)

    # --- planning ---------------------------------------------------------

    def _cache_key(self, probe) -> tuple[str, int, int]:
        stat = probe.path.stat()
        return (str(probe.path), stat.st_size, stat.st_mtime_ns)

    def _page_texts(self, probe, reader) -> list[str]:
        """Extract each page's text layer once, memoised for extract()."""
        key = self._cache_key(probe)
        if self._text_cache is not None and self._text_cache[0] == key:
            return self._text_cache[1]
        texts: list[str] = []
        for page in reader.pages:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                texts.append("")
        self._text_cache = (key, texts)
        return texts

    def plan(self, probe) -> ExtractionPlan:
        reader = _open_reader(probe)
        page_count = len(reader.pages)
        if page_count == 0:
            raise EmptyDocumentError("The PDF has no pages.")

        texts = self._page_texts(probe, reader)
        strategies = [
            classify_page(text, self.config, has_images=_page_has_images(page)).strategy
            for text, page in zip(texts, reader.pages)
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
        # Reuse the text layer extracted during plan() instead of extracting
        # every page a second time.
        page_texts = self._page_texts(probe, reader)
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
                    text = (page_texts[i] if i < len(page_texts) else "").strip()
                    blocks.extend(self._paragraph_blocks(text, page_no, method="text"))
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