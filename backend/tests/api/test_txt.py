"""TXT API tests: upload, process, content.

What it does:
    Verifies .txt uploads return 202, process to done with method txt,
    and render through the content/search endpoints like other formats.

How it works:
    - Uses the _upload helper plus process_job/DbJobQueue to drive docs to
      done without the background worker, mirroring test_content.py.
"""

from __future__ import annotations

import pytest

from documents.models import Document, Job
from documents.processing import process_job
from documents.queue import DbJobQueue

from tests.api.conftest import _upload


def _process(api_client, path, filename):
    # What: uploads + fully processes one file, returning the DONE Document.
    # How: POSTs via _upload, runs process_job inline on the queued Job.
    resp = _upload(api_client, path, filename)
    assert resp.status_code == 202, resp.data
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    return Document.objects.get(pk=doc_id)


@pytest.mark.django_db
def test_upload_txt_returns_202(api_client, plain_txt):
    # What: happy-path TXT upload is accepted and queued.
    # How: POSTs notes.txt, asserts 202 + not-a-duplicate.
    resp = _upload(api_client, plain_txt, "notes.txt")
    assert resp.status_code == 202, resp.data
    assert resp.data["duplicate"] is False


@pytest.mark.django_db
def test_txt_processes_to_done(api_client, plain_txt):
    # What: TXT processes to done with method txt and 2 blocks.
    # How: drives to terminal, asserts status done + method txt +
    #   block_count 2 + null page_count (pageless, like docx).
    doc = _process(api_client, plain_txt, "notes.txt")
    assert doc.status == "done"
    assert doc.method == "txt"
    assert doc.block_count == 2
    assert doc.page_count is None


@pytest.mark.django_db
def test_txt_content_text(api_client, plain_txt):
    # What: extracted lines survive into ?format=text.
    # How: processes notes.txt, GETs text content, asserts both lines present.
    doc = _process(api_client, plain_txt, "notes.txt")
    resp = api_client.get(f"/api/documents/{doc.id}/content/?format=text")
    assert resp.status_code == 200
    body = resp.content.decode()
    assert "Hello world" in body
    assert "Second line" in body


@pytest.mark.django_db
def test_txt_searchable(api_client, plain_txt):
    # What: TXT blocks are indexed for full-text search.
    # How: processes notes.txt, searches q=Second, asserts count>=1.
    _process(api_client, plain_txt, "notes.txt")
    resp = api_client.get("/api/search/?q=Second")
    assert resp.status_code == 200
    assert resp.data["count"] >= 1
