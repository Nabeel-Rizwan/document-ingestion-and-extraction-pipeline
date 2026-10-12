"""Shared fixtures for pipeline (extractor-level) tests.

What it does:
    Exposes one fixture per document shape so pipeline tests can just ask
    for ``digital_pdf`` / ``scanned_pdf`` / ``docx`` etc. without calling
    factories directly.

How it works:
    - Each fixture receives pytest's ``tmp_path`` (fresh dir per test) and
      forwards it to the matching builder in tests/factories.py.
    - ``__all__`` re-exports the builder names for modules that import them
      directly (e.g. test_probe imports make_digital_pdf for clarity).
"""

from __future__ import annotations

import pytest

from tests.factories import (
    make_binary,
    make_digital_pdf,
    make_docx,
    make_encrypted_pdf,
    make_garbled_pdf,
    make_mixed_pdf,
    make_plain_zip,
    make_scanned_pdf,
    make_short_text_pdf,
    make_structured_pdf,
    make_truncated_pdf,
)


@pytest.fixture
def digital_pdf(tmp_path):
    # What: 3-page text-layer PDF. How: factory-built in tmp_path isolation.
    return make_digital_pdf(pages=3, tmp_path=tmp_path)


@pytest.fixture
def scanned_pdf(tmp_path):
    # What: 2-page image-only PDF. How: factory-built in tmp_path isolation.
    return make_scanned_pdf(pages=2, tmp_path=tmp_path)


@pytest.fixture
def mixed_pdf(tmp_path):
    # What: 2 text + 1 OCR pages. How: factory merges digital + scanned PDFs.
    return make_mixed_pdf(text_pages=2, ocr_pages=1, tmp_path=tmp_path)


@pytest.fixture
def docx(tmp_path):
    # What: DOCX with heading/bullets/table. How: factory-built via python-docx.
    return make_docx(tmp_path=tmp_path)


@pytest.fixture
def encrypted_pdf(tmp_path):
    # What: password-protected PDF. How: factory encrypts a digital PDF.
    return make_encrypted_pdf(tmp_path=tmp_path)


@pytest.fixture
def truncated_pdf(tmp_path):
    # What: broken-trailer PDF. How: factory writes invalid raw PDF bytes.
    return make_truncated_pdf(tmp_path=tmp_path)


@pytest.fixture
def structured_pdf(tmp_path):
    # What: PDF with title/headings/lists. How: factory draws styled text.
    return make_structured_pdf(tmp_path=tmp_path)


@pytest.fixture
def short_text_pdf(tmp_path):
    # What: 1-page terse-text PDF. How: factory draws a single short string.
    return make_short_text_pdf(tmp_path=tmp_path)


@pytest.fixture
def garbled_pdf(tmp_path):
    # What: PDF with non-alphanumeric text layer. How: factory draws control chars.
    return make_garbled_pdf(tmp_path=tmp_path)


@pytest.fixture
def plain_zip(tmp_path):
    # What: valid ZIP that is not a DOCX. How: factory zips hello.txt.
    return make_plain_zip(tmp_path=tmp_path)


@pytest.fixture
def random_binary(tmp_path):
    # What: 128 random bytes. How: factory writes os.urandom output.
    return make_binary(tmp_path=tmp_path)


__all__ = [
    "make_binary",
    "make_digital_pdf",
    "make_docx",
    "make_encrypted_pdf",
    "make_garbled_pdf",
    "make_mixed_pdf",
    "make_plain_zip",
    "make_scanned_pdf",
    "make_short_text_pdf",
    "make_structured_pdf",
    "make_truncated_pdf",
]
