"""TXT extraction tests: routing, blocks, errors.

What it does:
    Verifies plain-text files route by .txt extension (no magic bytes),
    each non-empty line becomes a paragraph block, and undecodable bytes
    fail as corrupt.

How it works:
    - Uses the make_plain_txt factory plus build_probe -> plan -> extract
      with a RecordingProgressReporter, mirroring test_docx.py style.
    - Asserts on method/page_count, block texts, registry routing, and
      CorruptDocumentError for non-UTF-8 bytes.
"""

from __future__ import annotations

import pytest

from pipeline.errors import CorruptDocumentError
from pipeline.extractors.txt import TxtExtractor
from pipeline.probe import build_probe
from pipeline.progress import RecordingProgressReporter
from pipeline.registry import default_registry
from pipeline.service import run_pipeline


def _extract(path):
    # What: shortcut returning the ExtractionResult for a TXT path.
    # How: probes, plans, and extracts with a recording reporter.
    extractor = TxtExtractor()
    probe = build_probe(path, path.name)
    plan = extractor.plan(probe)
    return extractor.extract(probe, plan, RecordingProgressReporter())


def test_txt_routes_by_extension(plain_txt):
    # What: kind=None + .txt extension is claimed by TxtExtractor.
    # How: probes notes.txt (asserts kind None), selects via default
    #   registry, asserts extractor name txt and 1-unit text plan.
    probe = build_probe(plain_txt, plain_txt.name)
    assert probe.kind is None
    extractor = default_registry().select(probe)
    assert extractor.name == "txt"
    plan = extractor.plan(probe)
    assert plan.units == 1
    assert plan.strategies == ["text"]


def test_txt_lines_become_paragraphs(plain_txt):
    # What: each non-empty line becomes a paragraph block in order.
    # How: extracts the two-line fixture, asserts texts, types, null pages,
    #   method txt and page_count None.
    result = _extract(plain_txt)
    assert [b.text for b in result.blocks] == ["Hello world", "Second line"]
    assert all(b.type == "paragraph" for b in result.blocks)
    assert all(b.page is None for b in result.blocks)
    assert result.method == "txt"
    assert result.page_count is None


def test_txt_skips_blank_lines(tmp_path):
    # What: blank/whitespace lines separate but never emit blocks.
    # How: writes "a\\n\\n  \\nb", extracts, asserts only a + b remain.
    from tests.factories import make_plain_txt

    path = make_plain_txt("a\n\n  \nb", tmp_path=tmp_path)
    result = _extract(path)
    assert [b.text for b in result.blocks] == ["a", "b"]


def test_txt_empty_text_warns(tmp_path):
    # What: whitespace-only TXT yields no blocks plus a warning (still done).
    # How: writes spaces/newlines, extracts, asserts empty blocks and some
    #   warning mentions extractable text.
    from tests.factories import make_plain_txt

    path = make_plain_txt("   \n  \n", tmp_path=tmp_path)
    result = _extract(path)
    assert result.blocks == []
    assert any("extractable text" in w for w in result.warnings)


def test_txt_non_utf8_raises(tmp_path):
    # What: non-UTF-8 bytes named .txt raise CorruptDocumentError.
    # How: writes invalid byte 0xff, probes, asserts extract() raises.
    bad = tmp_path / "bad.txt"
    bad.write_bytes(b"\xff\xfe not utf-8")
    extractor = TxtExtractor()
    probe = build_probe(bad, "bad.txt")
    with pytest.raises(CorruptDocumentError):
        extractor.extract(probe, extractor.plan(probe), RecordingProgressReporter())


def test_txt_pipeline_end_to_end(plain_txt):
    # What: full run_pipeline works with the default registry.
    # How: runs the pipeline on notes.txt, asserts method txt + 2 blocks.
    out = run_pipeline(str(plain_txt), plain_txt.name, RecordingProgressReporter(), registry=default_registry())
    assert out.result.method == "txt"
    assert len(out.result.blocks) == 2
    assert out.probe.declared_ext == ".txt"
