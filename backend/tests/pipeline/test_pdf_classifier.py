"""Tests for the per-page PDF text/OCR classifier."""

from __future__ import annotations

from pipeline.extractors.pdf_classifier import PdfConfig, classify_page


def test_exactly_min_chars_is_text():
    config = PdfConfig(min_chars=25)
    text = "a" * 25
    assert classify_page(text, config).strategy == "text"


def test_below_min_chars_is_ocr():
    config = PdfConfig(min_chars=25)
    text = "a" * 24
    result = classify_page(text, config)
    assert result.strategy == "ocr"
    assert "too few characters" in result.reason


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