"""Tesseract OCR client.

Wraps the ``pytesseract`` binding (which drives the ``tesseract`` binary) behind
the :class:`~pipeline.ocr.base.OcrClient` interface. No pipeline code depends on
Tesseract directly, so it can be swapped for a cloud engine without changes.

Confidence is the mean per-word confidence Tesseract reports, normalised to
0..1. Words with confidence ``-1`` (structural tokens) are ignored.
"""

from __future__ import annotations

from PIL import Image

from .base import OcrResult

DEFAULT_PSM = 3  # fully automatic page segmentation


class TesseractOcrClient:
    def __init__(
        self,
        languages: str = "eng",
        psm: int = DEFAULT_PSM,
        *,
        _pytesseract=None,
    ) -> None:
        self.languages = languages
        self.psm = psm
        self._pt = _pytesseract

    def _engine(self):
        if self._pt is None:
            import pytesseract  # imported lazily so the package stays optional

            self._pt = pytesseract
        return self._pt

    def recognize(self, image: Image.Image, *, page: int) -> OcrResult:
        engine = self._engine()
        config = f"--psm {self.psm}"
        data = engine.image_to_data(
            image,
            lang=self.languages,
            config=config,
            output_type="dict",
        )
        text = engine.image_to_string(image, lang=self.languages, config=config)

        confidences: list[float] = []
        for raw in data.get("conf", []):
            try:
                value = float(raw)
            except (TypeError, ValueError):
                continue
            if value >= 0:
                confidences.append(value)
        confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0

        return OcrResult(text=text.strip(), confidence=confidence)
