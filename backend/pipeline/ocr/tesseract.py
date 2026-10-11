"""Tesseract OCR client.

Wraps the ``pytesseract`` binding (which drives the ``tesseract`` binary) behind
the :class:`~pipeline.ocr.base.OcrClient` interface. No pipeline code depends on
Tesseract directly, so it can be swapped for a cloud engine without changes.

Confidence is the mean per-word confidence Tesseract reports, normalised to
0..1. Words with confidence ``-1`` (structural tokens) are ignored.
"""

# Defer annotation evaluation (PEP 563).
from __future__ import annotations

# PIL image type accepted by recognize().
from PIL import Image

# Result value type returned by recognize().
from .base import OcrResult

# Default page-segmentation mode: 3 = fully automatic page segmentation.
DEFAULT_PSM = 3  # fully automatic page segmentation


class TesseractOcrClient:
    # Stores language(s), page-segmentation mode, and an optional injected engine.
    def __init__(
        self,
        languages: str = "eng",
        psm: int = DEFAULT_PSM,
        *,
        _pytesseract=None,
    ) -> None:
        # Tesseract language(s), e.g. "eng" or "eng+deu".
        self.languages = languages
        # Page-segmentation mode passed to Tesseract via --psm.
        self.psm = psm
        # Injected pytesseract module (used by tests); None means lazy import.
        self._pt = _pytesseract

    # Returns the pytesseract module, importing it on first use.
    def _engine(self):
        if self._pt is None:
            import pytesseract  # imported lazily so the package stays optional

            self._pt = pytesseract
        return self._pt

    # Recognises text in an image and computes a normalised confidence.
    def recognize(self, image: Image.Image, *, page: int) -> OcrResult:
        # Resolve the underlying engine (importing pytesseract if needed).
        engine = self._engine()
        # Tesseract CLI-style config string derived from the PSM setting.
        config = f"--psm {self.psm}"
        # Word-level data including per-word confidence values.
        data = engine.image_to_data(
            image,
            lang=self.languages,
            config=config,
            output_type="dict",
        )
        # Full recognised text for the image.
        text = engine.image_to_string(image, lang=self.languages, config=config)

        # Collect per-word confidence values (Tesseract reports 0..100).
        confidences: list[float] = []
        for raw in data.get("conf", []):
            try:
                # Values may arrive as strings; coerce to float.
                value = float(raw)
            except (TypeError, ValueError):
                # Skip non-numeric entries.
                continue
            # Ignore -1 (structural tokens such as blocks/lines) and other negatives.
            if value >= 0:
                confidences.append(value)
        # Mean word confidence normalised to 0..1; 0.0 when no words were scored.
        confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0

        # Return trimmed text with the computed confidence.
        return OcrResult(text=text.strip(), confidence=confidence)
