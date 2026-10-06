"""Tests for the per-page PDF text/OCR classifier."""

from __future__ import annotations

from pipeline.extractors.pdf_classifier import PdfConfig, classify_page


def test_exactly_min_chars_is_text():
    config = PdfConfig(min_chars=25)
    text = "a" * 25
    assert classify_page(text, config).strategy == "text"


def test_sparse_text_over_image_is_ocr():
    """A short text layer over an embedded image is a scanned page."""
    config = PdfConfig(min_chars=25)
    result = classify_page("a" * 24, config, has_images=True)
    assert result.strategy == "ocr"
    assert "sparse text" in result.reason


def test_short_clean_text_without_image_is_text():
    """A terse digital page (eg a title) must not be sent to OCR."""
    result = classify_page("Hello world", PdfConfig())
    assert result.strategy == "text"
    assert result.chars == 11


def test_short_page_with_image_is_ocr():
    result = classify_page("Hello", PdfConfig(), has_images=True)
    assert result.strategy == "ocr"


def test_no_text_layer_is_ocr():
    result = classify_page("   \n  ", PdfConfig())
    assert result.strategy == "ocr"
    assert result.reason == "no text layer"


def test_whitespace_only_is_ocr():
    config = PdfConfig(min_chars=25)
    text = " " * 100
    assert classify_page(text, config).strategy == "ocr"


def test_empty_is_ocr():
    assert classify_page("", PdfConfig()).strategy == "ocr"


def test_garbled_text_is_ocr():
    config = PdfConfig(min_alnum_ratio=0.5)
    text = "\x01\x02\x03\x04" * 20  # control chars, low alnum ratio
    result = classify_page(text, config)
    assert result.strategy == "ocr"
    assert "alphanumeric ratio" in result.reason


def test_clean_text_is_text():
    text = (
        "This is a perfectly normal sentence with plenty of words and "
        "letters to classify as a real text page."
    )
    assert classify_page(text, PdfConfig()).strategy == "text"


def test_chars_and_ratio_reported():
    result = classify_page("hello world", PdfConfig())
    assert result.chars == 11
    assert 0.0 < result.alnum_ratio <= 1.0