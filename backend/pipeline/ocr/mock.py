"""Mock OCR client.

Used in local development and tests. A production client would wrap
Tesseract / AWS Textract / Azure Document Intelligence behind the same
:class:`OcrClient` interface — no pipeline code would change.
"""

# Defer annotation evaluation (PEP 563).
from __future__ import annotations

# time is used to optionally simulate OCR latency.
import time

# PIL image type accepted by recognize().
from PIL import Image

# Base interface types implemented/returned by this mock client.
from .base import OcrClient, OcrResult


class MockOcrClient:
    """Returns a canned string for any image.

    ``latency_s`` simulates the cost of a real OCR call so progress is visible
    in the UI and tests.
    """

    # Stores the artificial per-call delay in seconds.
    def __init__(self, latency_s: float = 0.0) -> None:
        self.latency_s = latency_s

    # Returns a deterministic placeholder result for any image.
    def recognize(self, image: Image.Image, *, page: int) -> OcrResult:
        # Optionally sleep to mimic real OCR latency.
        if self.latency_s:
            time.sleep(self.latency_s)
        # Canned text names the page; fixed high confidence keeps it above thresholds.
        return OcrResult(
            text=f"[MOCK OCR] Recognised text from page {page}.",
            confidence=0.92,
        )