"""Fixtures for API tests. Reuses the Phase 1 document builders.

What it does:
    Provides shared pytest fixtures for all ``tests/api/*`` modules:
    isolated MEDIA_ROOT, deterministic mock OCR, per-test document files,
    DRF APIClient, and a pre-processed Document.

How it works:
    - The autouse ``_tmp_media`` fixture redirects Django file storage into
      pytest's tmp_path and forces OCR_ENGINE=mock so no Tesseract binary
      or network is needed.
    - ``_upload`` is a thin helper that wraps a file on disk in a
      SimpleUploadedFile and POSTs it to /api/documents/.
    - Named fixtures (digital_pdf, scanned_pdf, ...) build fresh files per
      test via tests/factories.py; ``processed_document`` uploads + runs
      process_job synchronously so tests can assert on terminal state.
"""

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
    make_plain_txt,
    make_scanned_pdf,
    make_truncated_pdf,
)


@pytest.fixture(autouse=True)
def _tmp_media(settings, tmp_path):
    """Keep test uploads out of the repo's media folder and force mock OCR so
    the API tests are deterministic and do not depend on a Tesseract install."""
    # What: isolates file + OCR side effects for every API test.
    # How: points MEDIA_ROOT at tmp_path/media and sets OCR to in-memory mock
    #   with zero artificial latency.
    settings.MEDIA_ROOT = str(tmp_path / "media")
    settings.OCR_ENGINE = "mock"
    settings.OCR_MOCK_LATENCY = 0.0


def _upload(client, path, filename):
    # What: uploads one local file to the ingest endpoint.
    # How: reads raw bytes, wraps in DRF SimpleUploadedFile (octet-stream so
    #   server-side sniffing is exercised), POSTs multipart to /api/documents/.
    from django.core.files.uploadedfile import SimpleUploadedFile

    with open(path, "rb") as fh:
        content = fh.read()
    uploaded = SimpleUploadedFile(filename, content, content_type="application/octet-stream")
    return client.post("/api/documents/", {"file": uploaded}, format="multipart")


@pytest.fixture
def api_client():
    # What: provides a DRF test client for HTTP-level assertions.
    # How: returns a fresh APIClient; tests call .get/.post/.delete on it.
    from rest_framework.test import APIClient

    return APIClient()


@pytest.fixture
def digital_pdf(tmp_path):
    # What: 3-page born-digital PDF with a real text layer.
    # How: delegates to the factory with tmp_path isolation.
    return make_digital_pdf(pages=3, tmp_path=tmp_path)


@pytest.fixture
def scanned_pdf(tmp_path):
    # What: 2-page image-only PDF (no text layer, forces OCR path).
    # How: delegates to the factory with tmp_path isolation.
    return make_scanned_pdf(pages=2, tmp_path=tmp_path)


@pytest.fixture
def mixed_pdf(tmp_path):
    # What: hybrid PDF (2 text pages + 1 scanned page) for routing tests.
    # How: delegates to the factory with tmp_path isolation.
    return make_mixed_pdf(text_pages=2, ocr_pages=1, tmp_path=tmp_path)


@pytest.fixture
def docx(tmp_path):
    # What: sample DOCX with heading, bullets, table.
    # How: delegates to the factory with tmp_path isolation.
    return make_docx(tmp_path=tmp_path)


@pytest.fixture
def encrypted_pdf(tmp_path):
    # What: password-protected PDF for the encrypted error path.
    # How: delegates to the factory with tmp_path isolation.
    return make_encrypted_pdf(tmp_path=tmp_path)


@pytest.fixture
def truncated_pdf(tmp_path):
    # What: structurally broken PDF for the corrupt error path.
    # How: delegates to the factory with tmp_path isolation.
    return make_truncated_pdf(tmp_path=tmp_path)


@pytest.fixture
def plain_txt(tmp_path):
    # What: two-line UTF-8 text file for the TXT path.
    # How: delegates to the factory with tmp_path isolation.
    return make_plain_txt(tmp_path=tmp_path)


@pytest.fixture
def processed_document(api_client, digital_pdf):
    """Upload a digital PDF, process it synchronously, return the Document."""
    # What: end-to-end shortcut returning a DONE document.
    # How: uploads via API (asserts 202 accepted), fetches the queued Job,
    #   runs process_job inline with DbJobQueue, then re-reads the Document.
    resp = _upload(api_client, digital_pdf, "digital.pdf")
    assert resp.status_code == 202, resp.data
    doc_id = resp.data["document"]["id"]
    job = Job.objects.get(document_id=doc_id)
    process_job(job, DbJobQueue())
    doc = Document.objects.get(pk=doc_id)
    return doc


__all__ = ["_upload"]
