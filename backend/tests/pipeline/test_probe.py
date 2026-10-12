"""Tests for magic-byte sniffing.

What it does:
    Verifies build_probe() detects the true file kind from magic bytes
    (not the filename), warns on extension mismatches, rejects non-DOCX
    ZIPs and random bytes, and raises on empty files.

How it works:
    - Builds real PDFs/DOCXs via fixtures, optionally renames them with
      shutil.copyfile to simulate lying extensions.
    - Calls build_probe(path, filename) and asserts on probe.kind,
      probe.warnings, and probe.declared_ext.
"""

from __future__ import annotations

import shutil

import pytest

from pipeline.errors import EmptyDocumentError
from pipeline.probe import build_probe
from tests.pipeline.conftest import make_digital_pdf, make_docx


def _copy(src, dst):
    # What: copies a fixture to a misleading filename, returning the new path.
    # How: thin wrapper around shutil.copyfile for rename-to-lie scenarios.
    shutil.copyfile(src, dst)
    return dst


def test_docx_renamed_to_pdf_is_still_docx(tmp_path, docx):
    # What: DOCX bytes named .pdf are still detected as docx + warning.
    # How: copies docx fixture to report.pdf, probes it, asserts kind==docx
    #   and a warning mentions both "extension" and ".pdf".
    renamed = _copy(docx, tmp_path / "report.pdf")
    probe = build_probe(renamed, "report.pdf")
    assert probe.kind == "docx"
    assert any("extension" in w and ".pdf" in w for w in probe.warnings)


def test_pdf_renamed_to_docx_is_still_pdf(tmp_path, digital_pdf):
    # What: PDF bytes named .docx are still detected as pdf + warning.
    # How: copies PDF fixture to scan.docx, probes it, asserts kind==pdf
    #   and a warning mentions "extension" and ".docx".
    renamed = _copy(digital_pdf, tmp_path / "scan.docx")
    probe = build_probe(renamed, "scan.docx")
    assert probe.kind == "pdf"
    assert any("extension" in w and ".docx" in w for w in probe.warnings)


def test_plain_zip_is_not_docx(plain_zip):
    # What: a plain ZIP (not OOXML) is kind=None with a "not a DOCX" warning.
    # How: probes the plain_zip fixture as archive.docx, asserts kind is None
    #   and some warning contains "not a DOCX".
    probe = build_probe(plain_zip, "archive.docx")
    assert probe.kind is None
    assert any("not a DOCX" in w for w in probe.warnings)


def test_random_bytes_are_unsupported(random_binary):
    # What: random bytes sniff as kind=None with no warnings (pure 415 path).
    # How: probes the random_binary fixture, asserts kind None + no warnings.
    probe = build_probe(random_binary, "data.bin")
    assert probe.kind is None
    assert probe.warnings == []


def test_empty_file_raises(tmp_path):
    # What: zero-byte files raise EmptyDocumentError (400 path).
    # How: writes an empty file, asserts build_probe raises the error.
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    with pytest.raises(EmptyDocumentError):
        build_probe(empty, "empty.pdf")


def test_declared_extension_captured(digital_pdf):
    # What: declared_ext is normalised to lowercase with leading dot.
    # How: probes a PDF as file.PDF, asserts declared_ext == ".pdf".
    probe = build_probe(digital_pdf, "file.PDF")
    assert probe.declared_ext == ".pdf"


def test_no_extension_no_warning(digital_pdf):
    # What: extensionless filenames produce no spurious warnings.
    # How: probes a PDF as "noext", asserts kind==pdf and warnings empty.
    probe = build_probe(digital_pdf, "noext")
    assert probe.kind == "pdf"
    assert probe.warnings == []
