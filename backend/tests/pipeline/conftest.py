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
    make_truncated_pdf,
)


@pytest.fixture
def digital_pdf(tmp_path):
    return make_digital_pdf(pages=3, tmp_path=tmp_path)


@pytest.fixture
def scanned_pdf(tmp_path):
    return make_scanned_pdf(pages=2, tmp_path=tmp_path)


@pytest.fixture
def mixed_pdf(tmp_path):
    return make_mixed_pdf(text_pages=2, ocr_pages=1, tmp_path=tmp_path)


@pytest.fixture
def docx(tmp_path):
    return make_docx(tmp_path=tmp_path)


@pytest.fixture
def encrypted_pdf(tmp_path):
    return make_encrypted_pdf(tmp_path=tmp_path)


@pytest.fixture
def truncated_pdf(tmp_path):
    return make_truncated_pdf(tmp_path=tmp_path)


@pytest.fixture
def garbled_pdf(tmp_path):
    return make_garbled_pdf(tmp_path=tmp_path)


@pytest.fixture
def plain_zip(tmp_path):
    return make_plain_zip(tmp_path=tmp_path)


@pytest.fixture
def random_binary(tmp_path):
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
    "make_truncated_pdf",
]