"""Per-page PDF text/OCR classification.

A page needs OCR when its extracted text layer is missing, too garbled, or so
sparse that it is really a scanned image with only a few text artifacts. The
*image presence* signal matters: a short page with no embedded images is very
likely a genuine (if terse) digital page and should not be OCR'd, whereas a
short page that also contains an image is a scanned page in disguise.

Pure function, easily unit-tested.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass(frozen=True)
class PdfConfig:
    # A text layer with at least this many (stripped) characters is trusted.
    # Kept deliberately low because many real pages are short (titles,
    # invoices, forms) — the image check below guards against scanned pages.
    min_chars: int = 8
    min_alnum_ratio: float = 0.5
    ocr_min_confidence: float = 0.6
    render_scale: float = 3.0


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


def classify_page(text: str, config: PdfConfig, *, has_images: bool = False) -> PageClass:
    stripped = text.strip()
    chars = len(stripped)
    ratio = _alnum_ratio(stripped)

    if chars == 0:
        return PageClass(
            strategy="ocr",
            reason="no text layer",
            chars=0,
            alnum_ratio=0.0,
        )

    if ratio < config.min_alnum_ratio:
        return PageClass(
            strategy="ocr",
            reason=f"low alphanumeric ratio ({ratio:.2f} < {config.min_alnum_ratio})",
            chars=chars,
            alnum_ratio=ratio,
        )

    if chars < config.min_chars:
        # Sparse but clean text. With an embedded image this is almost always a
        # scanned page; without one it is just a short digital page.
        if has_images:
            return PageClass(
                strategy="ocr",
                reason=f"sparse text ({chars} < {config.min_chars}) over an image",
                chars=chars,
                alnum_ratio=ratio,
            )
        return PageClass(
            strategy="text",
            reason=f"short text layer ({chars} chars, no images)",
            chars=chars,
            alnum_ratio=ratio,
        )

    return PageClass(
        strategy="text",
        reason="clean text layer",
        chars=chars,
        alnum_ratio=ratio,
    )
