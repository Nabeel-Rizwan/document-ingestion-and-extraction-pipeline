"""Agent tool interface tests.

What it does:
    Covers the LLM-facing tool endpoints: listing available tools,
    search_documents / list_documents / get_document / get_document_page,
    plus structured error envelopes for bad names/args/ids.

How it works:
    - ``_process`` uploads + synchronously processes files so tools have
      DONE documents to query.
    - ``_call`` POSTs {"name", "arguments"} JSON to /api/agent/tools/call/.
    - Tests assert on counts, filenames, block filtering, and error dicts.
"""

from __future__ import annotations

import pytest

from documents.models import Document, Job
from documents.processing import process_job
from documents.queue import DbJobQueue

from tests.api.conftest import _upload


def _process(api_client, path, filename):
    # What: uploads + fully processes one file, returning the DONE Document.
    # How: POSTs via _upload, fetches the Job, runs process_job inline.
    resp = _upload(api_client, path, filename)
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    return Document.objects.get(pk=doc_id)


def _call(api_client, name, arguments):
    # What: invokes one agent tool by name.
    # How: POSTs JSON {name, arguments} to the tools/call endpoint.
    return api_client.post("/api/agent/tools/call/", {"name": name, "arguments": arguments}, format="json")


@pytest.mark.django_db
def test_tools_listing(api_client):
    # What: GET /api/agent/tools/ advertises the 4 tools in stable order.
    # How: GETs the listing, extracts function names, asserts exact list.
    resp = api_client.get("/api/agent/tools/")
    assert resp.status_code == 200
    names = [t["function"]["name"] for t in resp.data]
    assert names == ["search_documents", "list_documents", "get_document", "get_document_page"]


@pytest.mark.django_db
def test_search_documents_tool(api_client, digital_pdf):
    # What: search_documents finds the processed PDF by keyword.
    # How: processes doc.pdf, calls tool with query=digital, asserts 200,
    #   count>=1 and "digital" appears in the first headline.
    _process(api_client, digital_pdf, "doc.pdf")
    resp = _call(api_client, "search_documents", {"query": "digital"})
    assert resp.status_code == 200
    assert resp.data["count"] >= 1
    assert "digital" in resp.data["results"][0]["headline"]


@pytest.mark.django_db
def test_list_documents_tool(api_client, digital_pdf, docx):
    # What: list_documents filters by status and returns both filenames.
    # How: processes PDF + DOCX, calls tool with status=done, asserts
    #   count==2 and filename set matches uploads.
    _process(api_client, digital_pdf, "doc.pdf")
    _process(api_client, docx, "report.docx")
    resp = _call(api_client, "list_documents", {"status": "done"})
    assert resp.data["count"] == 2
    assert {r["filename"] for r in resp.data["results"]} == {"doc.pdf", "report.docx"}


@pytest.mark.django_db
def test_get_document_tool(api_client, digital_pdf):
    # What: get_document returns JSON metadata and markdown content.
    # How: processes PDF, calls tool twice (format json + markdown),
    #   asserting id/status and the "<!-- page 1 -->" marker in markdown.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = _call(api_client, "get_document", {"document_id": str(doc.id), "format": "json"})
    assert resp.data["id"] == str(doc.id)
    assert resp.data["status"] == "done"

    md = _call(api_client, "get_document", {"document_id": str(doc.id), "format": "markdown"})
    assert "<!-- page 1 -->" in md.data["content"]


@pytest.mark.django_db
def test_get_document_page_tool(api_client, digital_pdf):
    # What: get_document_page returns only blocks from the requested page.
    # How: processes 3-page PDF, requests page 2, asserts page==2 and every
    #   block's page field equals 2.
    doc = _process(api_client, digital_pdf, "doc.pdf")
    resp = _call(api_client, "get_document_page", {"document_id": str(doc.id), "page": 2})
    assert resp.data["page"] == 2
    assert all(b["page"] == 2 for b in resp.data["blocks"])


@pytest.mark.django_db
def test_tool_structured_errors(api_client):
    # What: unknown ids/tools and invalid args return {"error": ...} dicts.
    # How: calls get_document with random UUID (not found), unknown tool
    #   name, too-short query, and non-UUID id - asserting each error string.
    import uuid

    not_found = _call(api_client, "get_document", {"document_id": str(uuid.uuid4())})
    assert not_found.data == {"error": "document not found"}

    unknown = _call(api_client, "nope", {})
    assert unknown.data["error"].startswith("unknown tool")

    bad_args = _call(api_client, "search_documents", {"query": "x"})
    assert bad_args.data["error"].startswith("query must be")

    bad_types = _call(api_client, "get_document_page", {"document_id": "abc"})
    assert "error" in bad_types.data


@pytest.mark.django_db
def test_tools_call_requires_name(api_client):
    # What: missing tool name is a 400 bad_request (HTTP-level validation).
    # How: POSTs only {"arguments": {}} without name, asserts 400 + code.
    resp = api_client.post("/api/agent/tools/call/", {"arguments": {}}, format="json")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"
