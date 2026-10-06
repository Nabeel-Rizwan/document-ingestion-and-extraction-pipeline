"""OCR abstraction.

A production client would wrap Tesseract / AWS Textract / Azure Document
Intelligence behind the same :class:`OcrClient` interface. The pipeline only
ever depends on this Protocol, so swapping the real engine in requires no
changes outside the client itself.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from PIL import Image


@dataclass(frozen=True)
class OcrResult:
    text: str
    confidence: float


class OcrClient(Protocol):
    def recognize(self, image: Image.Image, *, page: int) -> OcrResult: ...