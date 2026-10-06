"""Tests for magic-byte sniffing."""

from __future__ import annotations

import shutil

import pytest

from pipeline.errors import EmptyDocumentError
from pipeline.probe import build_probe
from tests.pipeline.conftest import make_digital_pdf, make_docx


def _copy(src, dst):
    shutil.copyfile(src, dst)
    return dst


def test_docx_renamed_to_pdf_is_still_docx(tmp_path, docx):
    renamed = _copy(docx, tmp_path / "report.pdf")
    probe = build_probe(renamed, "report.pdf")
    assert probe.kind == "docx"
    assert any("extension" in w and ".pdf" in w for w in probe.warnings)


def test_pdf_renamed_to_docx_is_still_pdf(tmp_path, digital_pdf):
    renamed = _copy(digital_pdf, tmp_path / "scan.docx")
    probe = build_probe(renamed, "scan.docx")
    assert probe.kind == "pdf"
    assert any("extension" in w and ".docx" in w for w in probe.warnings)


def test_plain_zip_is_not_docx(plain_zip):
    probe = build_probe(plain_zip, "archive.docx")
    assert probe.kind is None
    assert any("not a DOCX" in w for w in probe.warnings)


def test_random_bytes_are_unsupported(random_binary):
    probe = build_probe(random_binary, "data.bin")
    assert probe.kind is None
    assert probe.warnings == []


def test_empty_file_raises(tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(EmptyDocumentError):
        build_probe(empty, "empty.pdf")


def test_declared_extension_captured(digital_pdf):
    probe = build_probe(digital_pdf, "file.PDF")
    assert probe.declared_ext == ".pdf"


def test_no_extension_no_warning(digital_pdf):
    probe = build_probe(digital_pdf, "noext")
    assert probe.kind == "pdf"
    assert probe.warnings == []