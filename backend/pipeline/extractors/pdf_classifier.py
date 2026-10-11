"""Per-page PDF text/OCR classification.

A page needs OCR when its extracted text layer is missing, too garbled, or so
sparse that it is really a scanned image with only a few text artifacts. The
*image presence* signal matters: a short page with no embedded images is very
likely a genuine (if terse) digital page and should not be OCR'd, whereas a
short page that also contains an image is a scanned page in disguise.

Pure function, easily unit-tested.
"""

# Defer annotation evaluation (PEP 563).
from __future__ import annotations

# dataclass provides frozen value types for config and results.
from dataclasses import dataclass
# re is used to strip non-alphanumeric characters for the ratio calculation.
import re


# Immutable tuning parameters for page classification and rendering.
@dataclass(frozen=True)
class PdfConfig:
    # A text layer with at least this many (stripped) characters is trusted.
    # Kept deliberately low because many real pages are short (titles,
    # invoices, forms) — the image check below guards against scanned pages.
    min_chars: int = 8
    # Minimum fraction of alphanumeric (or whitespace) characters required.
    min_alnum_ratio: float = 0.5
    # OCR results below this confidence are flagged as warnings.
    ocr_min_confidence: float = 0.6
    # Rasterisation scale passed to the PDF renderer for OCR.
    render_scale: float = 3.0


# Immutable classification outcome for a single page.
@dataclass(frozen=True)
class PageClass:
    strategy: str  # "text" | "ocr"
    # Human-readable explanation for the chosen strategy.
    reason: str
    # Number of stripped characters seen in the text layer.
    chars: int
    # Alphanumeric ratio of the stripped text layer.
    alnum_ratio: float


# Computes the fraction of characters that are word characters or whitespace.
def _alnum_ratio(text: str) -> float:
    # Empty text has an undefined ratio, reported as 0.0.
    if not text:
        return 0.0
    # Remove every character that is not a word character or whitespace.
    alnum_ws = re.sub(r"[^\w\s]", "", text)
    # Ratio of retained (alphanumeric/whitespace) characters to total length.
    return len(alnum_ws) / len(text)


# Decides whether a page should be read as digital text or sent to OCR.
def classify_page(text: str, config: PdfConfig, *, has_images: bool = False) -> PageClass:
    # Strip surrounding whitespace before measuring.
    stripped = text.strip()
    # Character count of the meaningful text layer.
    chars = len(stripped)
    # Alphanumeric ratio of the meaningful text.
    ratio = _alnum_ratio(stripped)

    # No text layer at all: the page must be scanned.
    if chars == 0:
        return PageClass(
            strategy="ocr",
            reason="no text layer",
            chars=0,
            alnum_ratio=0.0,
        )

    # Garbled/low-quality text layer (too few alphanumerics): treat as scanned.
    if ratio < config.min_alnum_ratio:
        return PageClass(
            strategy="ocr",
            reason=f"low alphanumeric ratio ({ratio:.2f} < {config.min_alnum_ratio})",
            chars=chars,
            alnum_ratio=ratio,
        )

    # Sparse but clean text needs the image signal to disambiguate.
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
        # Short clean text with no image: genuine digital page.
        return PageClass(
            strategy="text",
            reason=f"short text layer ({chars} chars, no images)",
            chars=chars,
            alnum_ratio=ratio,
        )

    # Plenty of clean text: unambiguously a digital page.
    return PageClass(
        strategy="text",
        reason="clean text layer",
        chars=chars,
        alnum_ratio=ratio,
    )
