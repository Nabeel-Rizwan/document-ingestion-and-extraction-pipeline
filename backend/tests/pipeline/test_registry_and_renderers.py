"""Tests for the registry, routing, renderers, and adding a new format."""

from __future__ import annotations

import pytest

from pipeline.errors import UnsupportedFormatError
from pipeline.extractors.base import Extractor
from pipeline.extractors.pdf_classifier import PdfConfig
from pipeline.probe import build_probe
from pipeline.registry import ExtractorRegistry, default_registry
from pipeline.renderers import render_csv, render_html, render_markdown, render_text
from pipeline.router import route
from pipeline.schema import Block, ExtractionPlan, ExtractionResult
from pipeline.service import run_pipeline
from pipeline.progress import RecordingProgressReporter


def test_registry_describe_contract():
    registry = default_registry()
    described = registry.describe()
    by_kind = {d["kind"]: d for d in described}
    assert set(by_kind) == {"pdf", "docx"}
    assert by_kind["pdf"]["extensions"] == [".pdf"]
    assert by_kind["docx"]["mime_types"][0].startswith("application/vnd")


def test_registry_select_unsupported(random_binary):
    registry = default_registry()
    probe = build_probe(random_binary, "random.bin")
    with pytest.raises(UnsupportedFormatError) as exc:
        registry.select(probe)
    assert exc.value.code == "unsupported"


def test_route_returns_extractor_and_plan(digital_pdf):
    registry = default_registry()
    probe = build_probe(digital_pdf, digital_pdf.name)
    extractor, plan = route(probe, registry)
    assert extractor.name == "pdf"
    assert plan.units == 3


def test_new_format_needs_only_new_extractor(tmp_path):
    """A toy TxtExtractor registered in-test proves adding a format is cheap."""

    class TxtExtractor:
        name = "txt"
        kinds = frozenset({"txt"})
        extensions = (".txt",)
        mime_types = ("text/plain",)

        def can_handle(self, probe):
            # plain text has no magic bytes; sniffing gives kind=None, so we
            # fall back to the declared extension. The router/registry need no
            # changes for this to work.
            return probe.kind == "txt" or (probe.kind is None and probe.declared_ext == ".txt")

        def plan(self, probe):
            return ExtractionPlan(extractor="txt", units=1, strategies=["text"], summary="TXT")

        def extract(self, probe, plan, progress):
            text = probe.path.read_text()
            return ExtractionResult(
                blocks=[Block(type="paragraph", text=text, metadata={})],
                method="txt",
                page_count=None,
            )

    path = tmp_path / "notes.txt"
    path.write_text("plain text notes")
    registry = ExtractorRegistry()
    registry.register(TxtExtractor())
    assert registry.supported_kinds() == frozenset({"txt"})
    described = registry.describe()
    assert described == [
        {"kind": "txt", "extensions": [".txt"], "mime_types": ["text/plain"]}
    ]

    reporter = RecordingProgressReporter()
    out = run_pipeline(str(path), "notes.txt", reporter, registry=registry)
    assert out.result.method == "txt"
    assert out.result.blocks[0].text == "plain text notes"


# --- renderers ------------------------------------------------------------


def _blocks():
    return [
        Block(type="heading", text="Title", metadata={"level": 1}),
        Block(type="paragraph", text="intro", page=1),
        Block(type="list_item", text="item one", page=2),
        Block(
            type="table",
            text="a\tb",
            metadata={"rows": [["a", "b"], ["1", "2"]]},
        ),
    ]


def test_render_markdown_headings_and_tables():
    md = render_markdown(_blocks())
    assert "# Title" in md
    assert "- item one" in md
    assert "| a | b |" in md
    assert "| --- | --- |" in md


def test_render_markdown_page_markers():
    blocks = [
        Block(type="paragraph", text="first", page=1),
        Block(type="paragraph", text="second", page=2),
        Block(type="paragraph", text="third", page=2),
    ]
    md = render_markdown(blocks)
    assert "<!-- page 1 -->" in md
    assert "<!-- page 2 -->" in md
    assert "---" in md
    # page marker appears twice, once for each page change
    assert md.count("<!-- page") == 2


def test_render_markdown_table_escapes_pipes():
    blocks = [
        Block(type="table", text="x", metadata={"rows": [["a|b"]]}),
    ]
    md = render_markdown(blocks)
    assert "a\\|b" in md


def test_render_text_basic():
    text = render_text(_blocks())
    assert "# Title" in text
    assert "* item one" in text
    assert "a\tb" in text
    assert "1\t2" in text


def test_render_text_no_page_markers():
    blocks = [Block(type="paragraph", text="x", page=1)]
    assert "<!--" not in render_text(blocks)


# --- html -----------------------------------------------------------------


def test_render_html_structure_and_groups_lists():
    html = render_html(_blocks())
    assert "<h1>Title</h1>" in html
    assert "<p>intro</p>" in html
    assert "<ul>" in html and "<li>item one</li>" in html
    assert html.count("<ul>") == 1  # consecutive list items grouped
    assert "<table" in html and "<th>a</th>" in html and "<td>1</td>" in html


def test_render_html_escapes_text():
    blocks = [Block(type="paragraph", text="<script>alert(1)</script> & \"quote\"")]
    html = render_html(blocks)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_render_html_page_breaks():
    blocks = [
        Block(type="paragraph", text="a", page=1),
        Block(type="paragraph", text="b", page=2),
    ]
    html = render_html(blocks)
    assert 'data-page="1"' in html
    assert 'data-page="2"' in html
    assert html.count("page-break") == 2


# --- csv ------------------------------------------------------------------


def test_render_csv_has_header_and_row_per_block():
    import csv as _csv
    from io import StringIO

    rows = list(_csv.reader(StringIO(render_csv(_blocks()))))
    assert rows[0] == ["idx", "type", "page", "method", "confidence", "text"]
    assert len(rows) == 5  # header + 4 blocks
    assert rows[1] == ["0", "heading", "", "", "", "Title"]
    assert rows[3] == ["2", "list_item", "2", "", "", "item one"]


def test_render_csv_reports_ocr_confidence():
    from io import StringIO
    import csv as _csv

    blocks = [
        Block(
            type="paragraph",
            text="scanned",
            page=1,
            metadata={"method": "ocr", "confidence": 0.91},
        )
    ]
    rows = list(_csv.reader(StringIO(render_csv(blocks))))
    assert rows[1][3] == "ocr"
    assert rows[1][4] == "0.91"