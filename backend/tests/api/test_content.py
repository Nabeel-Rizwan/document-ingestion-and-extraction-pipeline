"""Content, download, search and config endpoint tests.

What it does:
    Covers everything after ingest: rendering extracted blocks as
    json/markdown/text/html/csv, page filtering, download headers, full-text
    search with highlight markers, /api/config/, and the serializer contract.

How it works:
    - Local ``_process`` helper uploads a file then runs process_job
      synchronously via DbJobQueue so the document reaches ``done`` without
      needing the background worker.
    - Tests then GET the content/search/config endpoints and assert on
      status codes, bodies, headers, and exact field sets.
"""

from __future__ import annotations

import io

import pytest

from documents.models import Document, Job
from documents.processing import process_job
from documents.queue import DbJobQueue

from tests.api.conftest import _upload


def _process(api_client, path, filename):
    # What: uploads + fully processes one file, returning the DONE Document.
    # How: POSTs via _upload, looks up the auto-created Job, runs
    #   process_job inline (mock OCR), then re-fetches the Document row.
    resp = _upload(api_client, path, filename)
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    return Document.objects.get(pk=doc_id)


@pytest.mark.django_db
def test_content_json(api_client, digital_pdf):
    # What: JSON content exposes blocks with the exact public schema.
    # How: processes a 3-page PDF, GETs ?format=json, asserts document_id,
    #   page_count, non-empty blocks, and exact keys + first-block values.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=json")
    assert resp.status_code == 200
    body = resp.data
    assert body["document_id"] == str(doc.id)
    assert body["page_count"] == 3
    assert len(body["blocks"]) > 0
    block = body["blocks"][0]
    assert set(block.keys()) == {"id", "idx", "type", "text", "page", "metadata"}
    assert block["type"] == "paragraph"
    assert block["metadata"]["method"] == "text"


@pytest.mark.django_db
def test_content_markdown(api_client, digital_pdf):
    # What: markdown rendering inserts per-page HTML comment markers.
    # How: processes PDF, GETs ?format=markdown, asserts 200 and the
    #   "<!-- page 1 -->" marker is present in the decoded body.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=markdown")
    assert resp.status_code == 200
    assert "<!-- page 1 -->" in resp.content.decode()


@pytest.mark.django_db
def test_content_text(api_client, digital_pdf):
    # What: plain-text rendering contains the extracted page text.
    # How: processes PDF, GETs ?format=text, asserts known sentence from
    #   factories.py ("digital page number 1") appears.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=text")
    assert resp.status_code == 200
    assert "digital page number 1" in resp.content.decode()


@pytest.mark.django_db
def test_short_text_pdf_is_extracted_as_text_not_ocr(api_client, tmp_path):
    """Regression: a short but real text layer must not be routed to OCR."""
    # What: guards the classifier so terse digital pages stay method=pdf_text.
    # How: builds a "Hello world" PDF, processes it, asserts method is
    #   pdf_text (not pdf_ocr) and the text survives in ?format=text.
    from tests.factories import make_short_text_pdf

    path = make_short_text_pdf("Hello world", tmp_path=tmp_path)
    doc = _process(api_client, path, "short.pdf")
    assert doc.method == "pdf_text"
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=text")
    assert "Hello world" in resp.content.decode()


@pytest.mark.django_db
def test_structured_pdf_preserves_block_types(api_client, tmp_path):
    """Title/section/list/paragraph survive into every output format."""
    # What: structural typing (heading/paragraph/list_item) is preserved
    #   across json, markdown, html and csv renderers.
    # How: processes structured.pdf, then asserts block-type set in JSON,
    #   "# / ## / -" markers in markdown, <h1>/<li> in HTML, type names in CSV.
    from tests.factories import make_structured_pdf

    doc = _process(api_client, make_structured_pdf(tmp_path=tmp_path), "structured.pdf")

    body = api_client.get(f"/api/documents/{doc.id}/content/?format=json").data
    types = {b["type"] for b in body["blocks"]}
    assert {"heading", "paragraph", "list_item"} <= types

    md = api_client.get(f"/api/documents/{doc.id}/content/?format=markdown").content.decode()
    assert "# Quarterly Report" in md
    assert "## Findings" in md
    assert "- First bullet point" in md

    html = api_client.get(f"/api/documents/{doc.id}/content/?format=html").content.decode()
    assert "<h1>Quarterly Report</h1>" in html
    assert "<li>First bullet point</li>" in html

    csv = api_client.get(f"/api/documents/{doc.id}/content/?format=csv").content.decode()
    assert "heading" in csv and "list_item" in csv


@pytest.mark.django_db
def test_content_page_filter(api_client, digital_pdf):
    # What: ?page=2 filters JSON blocks down to that page only.
    # How: processes 3-page PDF, GETs ?format=json&page=2, asserts every
    #   returned block has page==2 and mentions "page number 2".
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=json&page=2")
    assert resp.status_code == 200
    assert all(b["page"] == 2 for b in resp.data["blocks"])
    assert any("page number 2" in b["text"] for b in resp.data["blocks"])


@pytest.mark.django_db
def test_content_page_on_pageless_document_400(api_client, docx):
    # What: ?page= on a DOCX (page_count=None) is a 400 bad request.
    # How: processes DOCX, GETs ?format=json&page=1, asserts 400 +
    #   bad_request code.
    doc = _process(api_client, docx, "report.docx")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=json&page=1")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_content_not_ready_409(api_client, digital_pdf):
    # What: content before processing returns 409 not_ready.
    # How: uploads but does NOT process, then GETs content and asserts 409 +
    #   not_ready code.
    resp = _upload(api_client, digital_pdf, "doc.pdf")
    doc_id = resp.data["document"]["id"]
    body = api_client.get(f"/api/documents/{doc_id}/content/?format=json")
    assert body.status_code == 409
    assert body.data["error"]["code"] == "not_ready"


@pytest.mark.django_db
def test_content_html(api_client, digital_pdf):
    # What: HTML rendering returns text/html with <p> + data-page attrs.
    # How: processes PDF, GETs ?format=html, asserts content-type prefix and
    #   that body contains a paragraph tag and data-page="1".
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=html")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/html")
    body = resp.content.decode()
    assert "<p>" in body
    assert 'data-page="1"' in body


@pytest.mark.django_db
def test_content_csv(api_client, digital_pdf):
    # What: CSV rendering returns text/csv with the canonical header row.
    # How: processes PDF, GETs ?format=csv, asserts content-type and that the
    #   first line is exactly "idx,type,page,method,confidence,text".
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=csv")
    assert resp.status_code == 200
    assert resp["Content-Type"].startswith("text/csv")
    first_line = resp.content.decode().splitlines()[0]
    assert first_line == "idx,type,page,method,confidence,text"


@pytest.mark.django_db
def test_content_unknown_format_400(api_client, digital_pdf):
    # What: unknown ?format= values are rejected with 400.
    # How: processes PDF, GETs ?format=xml, asserts 400 + bad_request.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=xml")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_content_download_sets_attachment_header(api_client, digital_pdf):
    # What: &download=1 forces a Content-Disposition attachment filename.
    # How: processes PDF, GETs markdown with download=1, asserts 200 and the
    #   header equals attachment; filename="doc.md".
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=markdown&download=1")
    assert resp.status_code == 200
    assert resp["Content-Disposition"] == 'attachment; filename="doc.md"'


@pytest.mark.django_db
def test_download(api_client, digital_pdf):
    # What: /download/ streams back the original uploaded bytes.
    # How: processes PDF, GETs the download URL, joins streaming_content and
    #   asserts the magic bytes are %PDF-.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/download/")
    assert resp.status_code == 200
    body = b"".join(resp.streaming_content)
    assert body[:5] == b"%PDF-"


@pytest.mark.django_db
def test_search_returns_headlines_with_markers(api_client, digital_pdf):
    # What: /api/search/ returns headline snippets with ⟦ ⟧ match markers.
    # How: processes PDF, searches q=digital, asserts count>=1, exact result
    #   keys, and that headline contains both marker chars.
    _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get("/api/search/?q=digital")
    assert resp.status_code == 200
    assert resp.data["count"] >= 1
    item = resp.data["results"][0]
    assert set(item.keys()) == {
        "document_id",
        "filename",
        "block_id",
        "idx",
        "page",
        "type",
        "headline",
        "rank",
    }
    assert "\u27e6" in item["headline"] and "\u27e7" in item["headline"]


@pytest.mark.django_db
def test_search_requires_query(api_client):
    # What: search validates q (missing or single-char -> 400).
    # How: GETs without q and with q=a (too short), asserts both 400.
    resp = api_client.get("/api/search/")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"

    short = api_client.get("/api/search/?q=a")
    assert short.status_code == 400


@pytest.mark.django_db
def test_config_lists_pdf_and_docx(api_client):
    # What: /api/config/ advertises limits + supported kinds.
    # How: GETs config, asserts max_upload_bytes>0, kinds=={pdf,docx}, and
    #   the pdf entry lists .pdf in extensions.
    resp = api_client.get("/api/config/")
    assert resp.status_code == 200
    assert resp.data["max_upload_bytes"] > 0
    kinds = {d["kind"] for d in resp.data["supported"]}
    assert kinds == {"pdf", "docx"}
    pdf = next(d for d in resp.data["supported"] if d["kind"] == "pdf")
    assert ".pdf" in pdf["extensions"]


@pytest.mark.django_db
def test_document_serializer_contract_fields(api_client, digital_pdf):
    # What: detail serializer exposes the exact stable field contract.
    # How: processes PDF, GETs detail, asserts key set matches the 16-field
    #   contract and that method/status/progress reflect a done extraction.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/")
    keys = set(resp.data.keys())
    assert keys == {
        "id",
        "filename",
        "mime",
        "size",
        "sha256",
        "status",
        "stage",
        "progress",
        "method",
        "page_count",
        "block_count",
        "warnings",
        "error",
        "error_code",
        "created_at",
        "updated_at",
    }
    assert resp.data["method"] == "pdf_text"
    assert resp.data["status"] == "done"
    assert resp.data["progress"] == 1.0
