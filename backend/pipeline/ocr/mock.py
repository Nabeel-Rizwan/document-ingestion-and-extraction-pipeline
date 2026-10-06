"""Mock OCR client.

Used in local development and tests. A production client would wrap
Tesseract / AWS Textract / Azure Document Intelligence behind the same
:class:`OcrClient` interface — no pipeline code would change.
"""

from __future__ import annotations

import time

from PIL import Image

from .base import OcrClient, OcrResult


class MockOcrClient:
    """Returns a canned string for any image.

    ``latency_s`` simulates the cost of a real OCR call so progress is visible
    in the UI and tests.
    """

    def __init__(self, latency_s: float = 0.0) -> None:
        self.latency_s = latency_s

    def recognize(self, image: Image.Image, *, page: int) -> OcrResult:
        if self.latency_s:
            time.sleep(self.latency_s)
        return OcrResult(
            text=f"[MOCK OCR] Recognised text from page {page}.",
            confidence=0.92,
        )