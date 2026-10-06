"""Upload / ingest API tests."""

from __future__ import annotations

import io

import pytest

from documents.models import Document, Job

from tests.api.conftest import _upload
from tests.factories import make_binary, make_digital_pdf, make_docx


@pytest.mark.django_db
def test_upload_pdf_returns_202(api_client, digital_pdf):
    resp = _upload(api_client, digital_pdf, "doc.pdf")
    assert resp.status_code == 202, resp.data
    data = resp.data["document"]
    assert data["status"] == "queued"
    assert data["stage"] == "queued"
    assert data["sha256"] == Document.objects.first().sha256
    assert resp.data["duplicate"] is False


@pytest.mark.django_db
def test_upload_docx_returns_202(api_client, docx):
    resp = _upload(api_client, docx, "report.docx")
    assert resp.status_code == 202, resp.data
    assert resp.data["duplicate"] is False
    assert Document.objects.count() == 1


@pytest.mark.django_db
def test_wrong_extension_accepted_with_warning(api_client, digital_pdf):
    resp = _upload(api_client, digital_pdf, "scan.docx")
    assert resp.status_code == 202, resp.data
    assert any("extension" in w for w in resp.data["document"]["warnings"])


@pytest.mark.django_db
def test_unsupported_type_returns_415(api_client, tmp_path):
    path = make_binary(tmp_path=tmp_path, ext=".bin")
    resp = _upload(api_client, path, "random.bin")
    assert resp.status_code == 415
    assert resp.data["error"]["code"] == "unsupported_type"


@pytest.mark.django_db
def test_empty_file_returns_400(api_client, tmp_path):
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    resp = _upload(api_client, empty, "empty.pdf")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_missing_file_field_returns_400(api_client):
    resp = api_client.post("/api/documents/", {}, format="multipart")
    assert resp.status_code == 400
    assert resp.data["error"]["code"] == "bad_request"


@pytest.mark.django_db
def test_oversize_returns_413(api_client, tmp_path, settings):
    settings.MAX_UPLOAD_BYTES = 100
    path = make_digital_pdf(pages=3, tmp_path=tmp_path)
    resp = _upload(api_client, path, "big.pdf")
    assert resp.status_code == 413
    assert resp.data["error"]["code"] == "too_large"


@pytest.mark.django_db
def test_duplicate_upload_returns_same_id(api_client, digital_pdf):
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
    resp = _upload(api_client, digital_pdf, "a.pdf")
    doc_id = resp.data["document"]["id"]
    deleted = api_client.delete(f"/api/documents/{doc_id}/")
    assert deleted.status_code == 204
    assert Document.objects.count() == 0
    assert api_client.get(f"/api/documents/{doc_id}/").status_code == 404


@pytest.mark.django_db
def test_retrieve_missing_returns_404(api_client):
    import uuid

    resp = api_client.get(f"/api/documents/{uuid.uuid4()}/")
    assert resp.status_code == 404
    assert resp.data["error"]["code"] == "not_found"


@pytest.mark.django_db
def test_list_pagination(api_client, digital_pdf, docx, tmp_path):
    from tests.factories import make_scanned_pdf

    make_docx(tmp_path=tmp_path)
    _upload(api_client, digital_pdf, "a.pdf")
    _upload(api_client, docx, "b.docx")
    page = api_client.get("/api/documents/?page=1")
    assert page.status_code == 200
    assert page.data["count"] >= 2