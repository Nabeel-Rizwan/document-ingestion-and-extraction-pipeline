"""Content, download, search and config endpoint tests."""

from __future__ import annotations

import io

import pytest

from documents.models import Document, Job
from documents.processing import process_job
from documents.queue import DbJobQueue

from tests.api.conftest import _upload


def _process(api_client, path, filename):
    resp = _upload(api_client, path, filename)
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    return Document.objects.get(pk=doc_id)


@pytest.mark.django_db
def test_content_json(api_client, digital_pdf):
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
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=markdown")
    assert resp.status_code == 200
    assert "<!-- page 1 -->" in resp.content.decode()


@pytest.mark.django_db
def test_content_text(api_client, digital_pdf):
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=text")
    assert resp.status_code == 200
    assert "digital page number 1" in resp.content.decode()


@pytest.mark.django_db
def test_content_page_filter(api_client, digital_pdf):
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=json&page=2")
    assert resp.status_code == 200
    assert all(b["page"] == 2 for b in resp.data["blocks"])
    assert any("page number 2" in b["text"] for b in resp.data["blocks"])


@pytest.mark.django_db
def test_content_page_on_pageless_document_400(api_client, docx):
    doc = _process(api_client, docx, "report.docx")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=json&page=1")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_content_not_ready_409(api_client, digital_pdf):
    resp = _upload(api_client, digital_pdf, "doc.pdf")
    doc_id = resp.data["document"]["id"]
    body = api_client.get(f"/api/documents/{doc_id}/content/?format=json")
    assert body.status_code == 409
    assert body.data["error"]["code"] == "not_ready"


@pytest.mark.django_db
def test_download(api_client, digital_pdf):
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = api_client.get(f"/api/documents/{doc.id}/download/")
    assert resp.status_code == 200
    body = b"".join(resp.streaming_content)
    assert body[:5] == b"%PDF-"


@pytest.mark.django_db
def test_search_returns_headlines_with_markers(api_client, digital_pdf):
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
    resp = api_client.get("/api/search/")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"

    short = api_client.get("/api/search/?q=a")
    assert short.status_code == 400


@pytest.mark.django_db
def test_config_lists_pdf_and_docx(api_client):
    resp = api_client.get("/api/config/")
    assert resp.status_code == 200
    assert resp.data["max_upload_bytes"] > 0
    kinds = {d["kind"] for d in resp.data["supported"]}
    assert kinds == {"pdf", "docx"}
    pdf = next(d for d in resp.data["supported"] if d["kind"] == "pdf")
    assert ".pdf" in pdf["extensions"]


@pytest.mark.django_db
def test_document_serializer_contract_fields(api_client, digital_pdf):
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