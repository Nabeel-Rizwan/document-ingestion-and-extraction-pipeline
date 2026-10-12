"""Tests for the per-page PDF text/OCR classifier.

What it does:
    Pins the classify_page() decision table: enough clean text -> "text"
    strategy, otherwise (empty/whitespace/sparse-over-image/garbled) ->
    "ocr" strategy, with human-readable reasons + chars/alnum diagnostics.

How it works:
    - Each test calls classify_page(text, PdfConfig(...), has_images=...)
      directly with a crafted string - no files, no OCR, pure unit tests.
    - Asserts on .strategy ("text"/"ocr"), .reason substrings, .chars and
      .alnum_ratio so routing regressions are caught at the boundary values.
"""

from __future__ import annotations

from pipeline.extractors.pdf_classifier import PdfConfig, classify_page


def test_exactly_min_chars_is_text():
    # What: boundary - exactly min_chars counts as sufficient text.
    # How: classifies "a"*25 with min_chars=25, asserts strategy text.
    config = PdfConfig(min_chars=25)
    text = "a" * 25
    assert classify_page(text, config).strategy == "text"


def test_sparse_text_over_image_is_ocr():
    """A short text layer over an embedded image is a scanned page."""
    # What: just-under-threshold text + image -> OCR (likely scanned).
    # How: classifies 24 chars with has_images=True, asserts ocr + reason
    #   mentions "sparse text".
    config = PdfConfig(min_chars=25)
    result = classify_page("a" * 24, config, has_images=True)
    assert result.strategy == "ocr"
    assert "sparse text" in result.reason


def test_short_clean_text_without_image_is_text():
    """A terse digital page (eg a title) must not be sent to OCR."""
    # What: short but clean text with no image stays "text" (title pages).
    # How: classifies "Hello world" with defaults, asserts text + chars==11.
    result = classify_page("Hello world", PdfConfig())
    assert result.strategy == "text"
    assert result.chars == 11


def test_short_page_with_image_is_ocr():
    # What: same short text but over an image flips to OCR.
    # How: classifies "Hello" with has_images=True, asserts ocr strategy.
    result = classify_page("Hello", PdfConfig(), has_images=True)
    assert result.strategy == "ocr"


def test_no_text_layer_is_ocr():
    # What: whitespace-only extraction means no text layer -> OCR.
    # How: classifies spaces/newlines, asserts ocr + reason "no text layer".
    result = classify_page("   \n  ", PdfConfig())
    assert result.strategy == "ocr"
    assert result.reason == "no text layer"


def test_whitespace_only_is_ocr():
    # What: 100 spaces still count as empty -> OCR, even at high char count.
    # How: classifies " "*100 with min_chars=25, asserts ocr (chars are
    #   stripped before counting).
    config = PdfConfig(min_chars=25)
    text = " " * 100
    assert classify_page(text, config).strategy == "ocr"


def test_empty_is_ocr():
    # What: empty string -> OCR.
    # How: classifies "" with defaults, asserts ocr strategy.
    assert classify_page("", PdfConfig()).strategy == "ocr"


def test_garbled_text_is_ocr():
    # What: low alphanumeric ratio (broken encoding) -> OCR.
    # How: classifies control chars with min_alnum_ratio=0.5, asserts ocr +
    #   reason mentions "alphanumeric ratio".
    config = PdfConfig(min_alnum_ratio=0.5)
    text = "\x01\x02\x03\x04" * 20  # control chars, low alnum ratio
    result = classify_page(text, config)
    assert result.strategy == "ocr"
    assert "alphanumeric ratio" in result.reason


def test_clean_text_is_text():
    # What: normal sentences comfortably exceed thresholds -> text.
    # How: classifies a two-clause sentence with defaults, asserts text.
    text = (
        "This is a perfectly normal sentence with plenty of words and "
        "letters to classify as a real text page."
    )
    assert classify_page(text, PdfConfig()).strategy == "text"


def test_chars_and_ratio_reported():
    # What: diagnostics report char count + alnum ratio in (0,1].
    # How: classifies "hello world", asserts chars==11 and 0 < ratio <= 1.
    result = classify_page("hello world", PdfConfig())
    assert result.chars == 11
    assert 0.0 < result.alnum_ratio <= 1.0
