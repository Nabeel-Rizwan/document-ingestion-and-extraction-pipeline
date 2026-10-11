"""OCR abstraction.

A production client would wrap Tesseract / AWS Textract / Azure Document
Intelligence behind the same :class:`OcrClient` interface. The pipeline only
ever depends on this Protocol, so swapping the real engine in requires no
changes outside the client itself.
"""

# Defer annotation evaluation (PEP 563).
from __future__ import annotations

# dataclass provides the immutable OCR result value type.
from dataclasses import dataclass
# Protocol defines the structural OCR client interface.
from typing import Protocol

# PIL image type accepted by OCR clients.
from PIL import Image


# Immutable OCR output: recognised text plus a 0..1 confidence score.
@dataclass(frozen=True)
class OcrResult:
    # Recognised text content.
    text: str
    # Confidence in the recognition, normalised to 0..1.
    confidence: float


# Structural interface every OCR engine wrapper must satisfy.
class OcrClient(Protocol):
    # Recognises text in an image; ``page`` is the 1-based page number for context.
    def recognize(self, image: Image.Image, *, page: int) -> OcrResult: ...