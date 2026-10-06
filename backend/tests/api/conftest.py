"""Fixtures for API tests. Reuses the Phase 1 document builders."""

from __future__ import annotations

import io

import pytest

from documents.models import Document, Job
from documents.processing import process_job
from documents.queue import DbJobQueue

from tests.factories import (
    make_digital_pdf,
    make_docx,
    make_encrypted_pdf,
    make_mixed_pdf,
    make_scanned_pdf,
    make_truncated_pdf,
)


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Keep test uploads out of the repo's media folder."""
    settings.MEDIA_ROOT = str(tmp_path / "media")


def _upload(client, path, filename):
    from django.core.files.uploadedfile import SimpleUploadedFile

    with open(path, "rb") as fh:
        content = fh.read()
    uploaded = SimpleUploadedFile(filename, content, content_type="application/octet-stream")
    return client.post("/api/documents/", {"file": uploaded}, format="multipart")


@pytest.fixture
def api_client():
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def digital_pdf(tmp_path):
    return make_digital_pdf(pages=3, tmp_path=tmp_path)


@pytest.fixture
def scanned_pdf(tmp_path):
    return make_scanned_pdf(pages=2, tmp_path=tmp_path)


@pytest.fixture
def mixed_pdf(tmp_path):
    return make_mixed_pdf(text_pages=2, ocr_pages=1, tmp_path=tmp_path)


@pytest.fixture
def docx(tmp_path):
    return make_docx(tmp_path=tmp_path)


@pytest.fixture
def encrypted_pdf(tmp_path):
    return make_encrypted_pdf(tmp_path=tmp_path)


@pytest.fixture
def truncated_pdf(tmp_path):
    return make_truncated_pdf(tmp_path=tmp_path)


@pytest.fixture
def processed_document(api_client, digital_pdf):
    """Upload a digital PDF, process it synchronously, return the Document."""
    resp = _upload(api_client, digital_pdf, "digital.pdf")
    assert resp.status_code == 202, resp.data
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    doc = Document.objects.get(pk=doc_id)
    return doc


__all__ = ["_upload"]