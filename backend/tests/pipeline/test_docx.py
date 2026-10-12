"""DOCX extraction tests: document-order interleaving, headings, tables.

What it does:
    Verifies DOCX blocks come out in document order with correct types
    (heading/paragraph/list_item/table), heading levels, table metadata,
    null page fields, embedded-image OCR, and corrupt handling.

How it works:
    - ``_extract`` runs probe -> plan -> extract with a recording reporter.
    - Tests assert on block type sequences, metadata dicts, and warning
      absence/presence; image/corrupt cases build dedicated fixtures inline.
"""

from __future__ import annotations

import pytest

from pipeline.errors import CorruptDocumentError
from pipeline.extractors.docx import DocxExtractor
from pipeline.probe import build_probe
from pipeline.progress import RecordingProgressReporter
from pipeline.schema import Block


def _extract(path):
    # What: shortcut returning the ExtractionResult for a DOCX path.
    # How: builds DocxExtractor, probes the file, plans, then extracts with
    #   a RecordingProgressReporter (progress assertions not needed here).
    extractor = DocxExtractor()
    probe = build_probe(path, path.name)
    plan = extractor.plan(probe)
    return extractor.extract(probe, plan, RecordingProgressReporter())


def test_docx_block_order_preserves_interleaving(docx):
    # What: blocks follow the DOCX body order, not grouped by style.
    # How: extracts the standard fixture, asserts the exact 6-block type
    #   sequence heading/paragraph/bullet/bullet/table/paragraph.
    result = _extract(docx)
    types = [b.type for b in result.blocks]
    # heading, paragraph, bullet, bullet, table, paragraph
    assert types == ["heading", "paragraph", "list_item", "list_item", "table", "paragraph"]


def test_docx_heading_levels(docx):
    # What: Heading 1 style maps to heading level 1 metadata.
    # How: extracts, finds the first heading block, asserts level==1.
    result = _extract(docx)
    heading = next(b for b in result.blocks if b.type == "heading")
    assert heading.metadata["level"] == 1


def test_docx_table_metadata(docx):
    # What: tables expose both row-matrix metadata and TSV text.
    # How: extracts, finds the table block, asserts rows equals the 2x2
    #   Name/Value/alpha/42 matrix and text is tab/newline-joined.
    result = _extract(docx)
    table = next(b for b in result.blocks if b.type == "table")
    assert table.metadata["rows"] == [
        ["Name", "Value"],
        ["alpha", "42"],
    ]
    assert table.text == "Name\tValue\nalpha\t42"


def test_docx_page_fields_null(docx):
    # What: DOCX is pageless - page_count None, every block page None.
    # How: extracts, asserts result.page_count is None, all block.page None,
    #   and method label is "docx".
    result = _extract(docx)
    assert result.page_count is None
    assert all(b.page is None for b in result.blocks)
    assert result.method == "docx"


def test_docx_image_is_ocr_extracted(tmp_path):
    # What: embedded images are OCR'd into text blocks (not dropped/warned).
    # How: builds a DOCX with include_image=True, extracts, asserts at least
    #   one block has method ocr + "[MOCK OCR]" text + 0.92 confidence, and
    #   no "were not extracted" warning exists.
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
    # What: image-free DOCX emits no image warnings and no OCR blocks.
    # How: extracts the standard fixture, asserts no warning mentions "image"
    #   and no block has method ocr.
    result = _extract(docx)
    assert not any("image" in w for w in result.warnings)
    assert not any(b.metadata.get("method") == "ocr" for b in result.blocks)


def test_corrupt_docx_raises(tmp_path):
    # What: non-ZIP bytes named .docx raise CorruptDocumentError.
    # How: writes plain text as bad.docx, probes it, asserts extract()
    #   (with a fresh plan) raises the corrupt error.
    bad = tmp_path / "bad.docx"
    bad.write_bytes(b"this is not a zip file at all")
    extractor = DocxExtractor()
    probe = build_probe(bad, "bad.docx")
    with pytest.raises(CorruptDocumentError):
        extractor.extract(probe, extractor.plan(probe), RecordingProgressReporter())


def test_plain_zip_is_not_docx(plain_zip):
    # What: a plain ZIP is not claimable by the DOCX extractor.
    # How: probes plain.zip, asserts DocxExtractor.can_handle returns False.
    extractor = DocxExtractor()
    probe = build_probe(plain_zip, "plain.zip")
    assert extractor.can_handle(probe) is False
