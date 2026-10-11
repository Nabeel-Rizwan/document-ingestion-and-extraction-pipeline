"""DOCX extraction tests: document-order interleaving, headings, tables."""

from __future__ import annotations

import pytest

from pipeline.errors import CorruptDocumentError
from pipeline.extractors.docx import DocxExtractor
from pipeline.probe import build_probe
from pipeline.progress import RecordingProgressReporter
from pipeline.schema import Block


def _extract(path):
    extractor = DocxExtractor()
    probe = build_probe(path, path.name)
    plan = extractor.plan(probe)
    return extractor.extract(probe, plan, RecordingProgressReporter())


def test_docx_block_order_preserves_interleaving(docx):
    result = _extract(docx)
    types = [b.type for b in result.blocks]
    # heading, paragraph, bullet, bullet, table, paragraph
    assert types == ["heading", "paragraph", "list_item", "list_item", "table", "paragraph"]


def test_docx_heading_levels(docx):
    result = _extract(docx)
    heading = next(b for b in result.blocks if b.type == "heading")
    assert heading.metadata["level"] == 1


def test_docx_table_metadata(docx):
    result = _extract(docx)
    table = next(b for b in result.blocks if b.type == "table")
    assert table.metadata["rows"] == [
        ["Name", "Value"],
        ["alpha", "42"],
    ]
    assert table.text == "Name\tValue\nalpha\t42"


def test_docx_page_fields_null(docx):
    result = _extract(docx)
    assert result.page_count is None
    assert all(b.page is None for b in result.blocks)
    assert result.method == "docx"


def test_docx_image_is_ocr_extracted(tmp_path):
    from tests.factories import make_docx

    path = make_docx(tmp_path=tmp_path, include_image=True)
    result = _extract(path)
    # The embedded image is OCR'd into a text block instead of being warned about.
    ocr_blocks = [b for b in result.blocks if b.metadata.get("method") == "ocr"]
    assert ocr_blocks
    assert "[MOCK OCR]" in ocr_blocks[0].text
    assert ocr_blocks[0].metadata["confidence"] == 0.92
    assert not any("were not extracted" in w for w in result.warnings)


def test_docx_no_image_warning(docx):
    result = _extract(docx)
    assert not any("image" in w for w in result.warnings)
    assert not any(b.metadata.get("method") == "ocr" for b in result.blocks)


def test_corrupt_docx_raises(tmp_path):
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"this is not a zip file at all")
    extractor = DocxExtractor()
    probe = build_probe(bad, "bad.docx")
    with pytest.raises(CorruptDocumentError):
        extractor.extract(probe, extractor.plan(probe), RecordingProgressReporter())


def test_plain_zip_is_not_docx(plain_zip):
    extractor = DocxExtractor()
    probe = build_probe(plain_zip, "plain.zip")
    assert extractor.can_handle(probe) is False