"""Tests for the registry, routing, renderers, and adding a new format.

What it does:
    Verifies ExtractorRegistry.describe()/select(), route() wiring, all four
    renderers (markdown/text/html/csv incl. escaping/grouping), and that a
    brand-new format only needs a new Extractor class (open/closed demo).

How it works:
    - Registry/routing tests use real fixtures + build_probe + default_registry.
    - Renderer tests build tiny in-memory Block lists via _blocks() and assert
      on exact markdown/HTML/CSV strings (escaping, grouping, headers).
    - The txt test defines an inline TxtExtractor, registers it, and runs the
      full run_pipeline to prove no router changes were needed.
"""

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
    # What: default registry advertises exactly pdf + docx with extensions/mimes.
    # How: calls describe(), indexes by kind, asserts kind set + pdf
    #   extensions + docx mime prefix.
    registry = default_registry()
    described = registry.describe()
    by_kind = {d["kind"]: d for d in described}
    assert set(by_kind) == {"pdf", "docx"}
    assert by_kind["pdf"]["extensions"] == [".pdf"]
    assert by_kind["docx"]["mime_types"][0].startswith("application/vnd")


def test_registry_select_unsupported(random_binary):
    # What: unknowable bytes raise UnsupportedFormatError with code.
    # How: probes random bytes, asserts select() raises and exc.code is
    #   "unsupported".
    registry = default_registry()
    probe = build_probe(random_binary, "random.bin")
    with pytest.raises(UnsupportedFormatError) as exc:
        registry.select(probe)
    assert exc.value.code == "unsupported"


def test_route_returns_extractor_and_plan(digital_pdf):
    # What: route() picks the pdf extractor and a 3-unit plan for digital PDF.
    # How: probes the digital fixture, routes via default registry, asserts
    #   extractor name + plan units.
    registry = default_registry()
    probe = build_probe(digital_pdf, digital_pdf.name)
    extractor, plan = route(probe, registry)
    assert extractor.name == "pdf"
    assert plan.units == 3


def test_new_format_needs_only_new_extractor(tmp_path):
    """A toy TxtExtractor registered in-test proves adding a format is cheap."""
    # What: proves extensibility - registering one class enables .txt end to end.
    # How: defines an inline TxtExtractor (can_handle via declared_ext
    #   fallback), registers it on a fresh registry, runs run_pipeline on a
    #   notes.txt file and asserts method + text survive.

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
            # What: single-unit text plan. How: returns a fixed ExtractionPlan.
            return ExtractionPlan(extractor="txt", units=1, strategies=["text"], summary="TXT")

        def extract(self, probe, plan, progress):
            # What: reads the whole file as one paragraph block.
            # How: read_text() -> single Block with empty metadata.
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
    # What: canonical 4-block sample (heading/paragraph/list/table) reused by
    #   every renderer test so expectations stay comparable.
    # How: returns fresh Block objects; table carries rows metadata for
    #   markdown/HTML table rendering.
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
    # What: markdown maps heading->"# ", list->"- ", table->pipe table.
    # How: renders _blocks(), asserts "# Title", "- item one", header row
    #   "| a | b |" and separator "| --- | --- |" all present.
    md = render_markdown(_blocks())
    assert "# Title" in md
    assert "- item one" in md
    assert "| a | b |" in md
    assert "| --- | --- |" in md


def test_render_markdown_page_markers():
    # What: page changes emit "<!-- page N -->" + "---" separators, once per page.
    # How: renders 3 paragraphs across pages 1,2,2; asserts both markers + ---
    #   exist and the marker count is exactly 2 (not per-block).
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
    # What: literal "|" inside table cells is backslash-escaped in markdown.
    # How: renders a 1-cell table containing "a|b", asserts "a\\|b" output.
    blocks = [
        Block(type="table", text="x", metadata={"rows": [["a|b"]]}),
    ]
    md = render_markdown(blocks)
    assert "a\\|b" in md


def test_render_text_basic():
    # What: plain-text renderer keeps heading/list/table affordances as text.
    # How: renders _blocks(), asserts "# Title", "* item one" and tab-joined
    #   table rows "a\\tb" / "1\\t2".
    text = render_text(_blocks())
    assert "# Title" in text
    assert "* item one" in text
    assert "a\tb" in text
    assert "1\t2" in text


def test_render_text_no_page_markers():
    # What: text output never contains HTML page-marker comments.
    # How: renders a single paged paragraph, asserts "<!--" absent.
    blocks = [Block(type="paragraph", text="x", page=1)]
    assert "<!--" not in render_text(blocks)


# --- html -----------------------------------------------------------------


def test_render_html_structure_and_groups_lists():
    # What: HTML maps blocks to h1/p/ul+li/table and groups adjacent <li>s.
    # How: renders _blocks(), asserts <h1>/<p>/<ul>/<li> present, only one
    #   <ul> wrapper (grouped), and table headers/cells present.
    html = render_html(_blocks())
    assert "<h1>Title</h1>" in html
    assert "<p>intro</p>" in html
    assert "<ul>" in html and "<li>item one</li>" in html
    assert html.count("<ul>") == 1  # consecutive list items grouped
    assert "<table" in html and "<th>a</th>" in html and "<td>1</td>" in html


def test_render_html_escapes_text():
    # What: HTML-escapes block text to prevent XSS (script stays inert).
    # How: renders a paragraph containing <script> + & + quotes, asserts raw
    #   "<script>" gone and escaped "&lt;script&gt;" + "&amp;" present.
    blocks = [Block(type="paragraph", text="<script>alert(1)</script> & \"quote\"")]
    html = render_html(blocks)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "&amp;" in html


def test_render_html_page_breaks():
    # What: page changes emit data-page attrs + page-break markers per page.
    # How: renders 2 paragraphs on pages 1/2, asserts both data-page attrs
    #   and exactly 2 "page-break" occurrences.
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
    # What: CSV has a header + one row per block with idx/type/page/text.
    # How: parses render_csv(_blocks()) with csv.reader, asserts header list,
    #   total 5 rows (header+4), and spot-checks rows 1 and 3.
    import csv as _csv
    from io import StringIO

    rows = list(_csv.reader(StringIO(render_csv(_blocks()))))
    assert rows[0] == ["idx", "type", "page", "method", "confidence", "text"]
    assert len(rows) == 5  # header + 4 blocks
    assert rows[1] == ["0", "heading", "", "", "", "Title"]
    assert rows[3] == ["2", "list_item", "2", "", "", "item one"]


def test_render_csv_reports_ocr_confidence():
    # What: OCR method + confidence survive into their CSV columns.
    # How: renders one OCR paragraph (0.91), parses CSV, asserts columns 3/4
    #   equal "ocr" / "0.91".
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
