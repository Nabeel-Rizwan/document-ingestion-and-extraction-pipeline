"""Per-page PDF text/OCR classification.

A page is classified as "ocr" when its extracted text is too sparse or too
garbled to be trustworthy (common with scanned pages whose font encodings come
out mangled). Pure function, easily unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PdfConfig:
    min_chars: int = 25
    min_alnum_ratio: float = 0.5
    ocr_min_confidence: float = 0.6
    render_scale: float = 2.0


@dataclass(frozen=True)
class PageClass:
    strategy: str  # "text" | "ocr"
    reason: str
    chars: int
    alnum_ratio: float


def _alnum_ratio(text: str) -> float:
    if not text:
        return 0.0
    alnum_ws = re.sub(r"[^\w\s]", "", text)
    return len(alnum_ws) / len(text)


def classify_page(text: str, config: PdfConfig) -> PageClass:
    stripped = text.strip()
    chars = len(stripped)
    ratio = _alnum_ratio(stripped)

    if chars < config.min_chars:
        return PageClass(
            strategy="ocr",
            reason=f"too few characters ({chars} < {config.min_chars})",
            chars=chars,
            alnum_ratio=ratio,
        )
    if ratio < config.min_alnum_ratio:
        return PageClass(
            strategy="ocr",
            reason=(
                f"low alphanumeric ratio "
                f"({ratio:.2f} < {config.min_alnum_ratio})"
            ),
            chars=chars,
            alnum_ratio=ratio,
        )
    return PageClass(
        strategy="text",
        reason="clean text layer",
        chars=chars,
        alnum_ratio=ratio,
    )