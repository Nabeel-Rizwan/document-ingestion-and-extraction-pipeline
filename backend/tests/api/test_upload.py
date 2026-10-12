"""Upload / ingest API tests.

What it does:
    Verifies the POST /api/documents/ ingest contract: accepted types return
    202, validation errors return 400/413/415, duplicates collapse to one
    Document, and list/retrieve/delete behave correctly.

How it works:
    - Uses the ``_upload`` helper (multipart POST) plus ``api_client``,
      ``digital_pdf`` and ``docx`` fixtures from conftest.
    - Each test is Arrange (build file/settings) -> Act (POST/GET/DELETE) ->
      Assert (status code + response body + DB counts).
    - ``@pytest.mark.django_db`` gives every test a rolled-back test DB.
"""

from __future__ import annotations

import io

import pytest

from documents.models import Document, Job

from tests.api.conftest import _upload
from tests.factories import make_binary, make_digital_pdf, make_docx


@pytest.mark.django_db
def test_upload_pdf_returns_202(api_client, digital_pdf):
    # What: happy-path PDF upload is accepted and queued.
    # How: POSTs the file, asserts 202 + queued status/stage, checks the
    #   returned sha256 matches the DB row and duplicate flag is False.
    resp = _upload(api_client, digital_pdf, "doc.pdf")
    assert resp.status_code == 202, resp.data
    data = resp.data["document"]
    assert data["status"] == "queued"
    assert data["stage"] == "queued"
    assert data["sha256"] == Document.objects.first().sha256
    assert resp.data["duplicate"] is False


@pytest.mark.django_db
def test_upload_docx_returns_202(api_client, docx):
    # What: happy-path DOCX upload is accepted.
    # How: POSTs report.docx, asserts 202 + not-a-duplicate and exactly one
    #   Document row was created.
    resp = _upload(api_client, docx, "report.docx")
    assert resp.status_code == 202, resp.data
    assert resp.data["duplicate"] is False
    assert Document.objects.count() == 1


@pytest.mark.django_db
def test_wrong_extension_accepted_with_warning(api_client, digital_pdf):
    # What: content sniffing wins over filename - a PDF named .docx is still
    #   accepted but carries an extension-mismatch warning.
    # How: uploads PDF bytes as scan.docx, asserts 202 and that one of the
    #   document warnings mentions "extension".
    resp = _upload(api_client, digital_pdf, "scan.docx")
    assert resp.status_code == 202, resp.data
    assert any("extension" in w for w in resp.data["document"]["warnings"])


@pytest.mark.django_db
def test_unsupported_type_returns_415(api_client, tmp_path):
    # What: random binary is rejected as unsupported media type.
    # How: builds 128 random bytes (.bin), POSTs, asserts 415 + machine code
    #   unsupported_type in the error envelope.
    path = make_binary(tmp_path=tmp_path, ext=".bin")
    resp = _upload(api_client, path, "random.bin")
    assert resp.status_code == 415
    assert resp.data["error"]["code"] == "unsupported_type"


@pytest.mark.django_db
def test_empty_file_returns_400(api_client, tmp_path):
    # What: zero-byte upload is rejected as a bad request.
    # How: writes an empty file, POSTs, asserts 400 + bad_request code.
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    resp = _upload(api_client, empty, "empty.pdf")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_missing_file_field_returns_400(api_client):
    # What: multipart POST without a file part is rejected.
    # How: POSTs an empty multipart body, asserts 400 + bad_request.
    resp = api_client.post("/api/documents/", {}, format="multipart")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_oversize_returns_413(api_client, tmp_path, settings):
    # What: files larger than MAX_UPLOAD_BYTES are rejected.
    # How: lowers the limit to 100 bytes via Django settings override, then
    #   uploads a normal 3-page PDF and asserts 413 + too_large code.
    settings.MAX_UPLOAD_BYTES = 100
    path = make_digital_pdf(pages=3, tmp_path=tmp_path)
    resp = _upload(api_client, path, "big.pdf")
    assert resp.status_code == 413
    assert resp.data["error"]["code"] == "too_large"


@pytest.mark.django_db
def test_duplicate_upload_returns_same_id(api_client, digital_pdf):
    # What: content-addressed deduplication - uploading identical bytes twice
    #   returns the same Document/Job instead of creating new rows.
    # How: uploads the same file twice, asserts first=202 second=200 with
    #   duplicate=True and identical IDs, plus single Document/Job in DB.
    first = _upload(api_client, digital_pdf, "doc.pdf")
    second = _upload(api_client, digital_pdf, "doc.pdf")
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.data["duplicate"] is True
    assert second.data["document"]["id"] == first.data["document"]["id"]
    assert Document.objects.count() == 1
    assert Job.objects.count() == 1


@pytest.mark.django_db
def test_list_and_retrieve(api_client, digital_pdf, docx):
    # What: list endpoint paginates both uploads; retrieve returns one doc.
    # How: uploads PDF + DOCX, GETs /api/documents/ (asserts count=2, no next
    #   page), then GETs the first result's detail URL and checks its id.
    _upload(api_client, digital_pdf, "a.pdf")
    _upload(api_client, docx, "b.docx")
    listing = api_client.get("/api/documents/")
    assert listing.status_code == 200
    assert listing.data["count"] == 2
    assert listing.data["next"] is None
    assert len(listing.data["results"]) == 2

    doc_id = listing.data["results"][0]["id"]
    single = api_client.get(f"/api/documents/{doc_id}/")
    assert single.status_code == 200
    assert single.data["id"] == doc_id


@pytest.mark.django_db
def test_delete(api_client, digital_pdf):
    # What: DELETE removes the document and subsequent GETs 404.
    # How: uploads, DELETEs the detail URL (asserts 204 + zero rows left),
    #   then GETs the same URL expecting 404.
    resp = _upload(api_client, digital_pdf, "a.pdf")
    doc_id = resp.data["document"]["id"]
    deleted = api_client.delete(f"/api/documents/{doc_id}/")
    assert deleted.status_code == 204
    assert Document.objects.count() == 0
    assert api_client.get(f"/api/documents/{doc_id}/").status_code == 404


@pytest.mark.django_db
def test_retrieve_missing_returns_404(api_client):
    # What: fetching a random UUID returns a structured not_found error.
    # How: GETs /api/documents/<random-uuid>/, asserts 404 + not_found code.
    import uuid

    resp = api_client.get(f"/api/documents/{uuid.uuid4()}/")
    assert resp.status_code == 404
    assert resp.data["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_list_pagination(api_client, digital_pdf, docx, tmp_path):
    # What: ?page=1 query param returns a successful paginated listing.
    # How: uploads two docs (plus builds an unused scanned PDF for coverage),
    #   GETs with ?page=1 and asserts 200 + count >= 2.
    from tests.factories import make_scanned_pdf

    make_docx(tmp_path=tmp_path)
    _upload(api_client, digital_pdf, "a.pdf")
    _upload(api_client, docx, "b.docx")
    page = api_client.get("/api/documents/?page=1")
    assert page.status_code == 200
    assert page.data["count"] >= 2
