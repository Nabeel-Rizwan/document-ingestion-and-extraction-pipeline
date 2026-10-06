"""Failure handling tests: corrupt/encrypted/transient failures."""

from __future__ import annotations

import io

import pytest

from documents.models import Document, Job, ProgressEvent
from documents.processing import process_job
from documents.queue import DbJobQueue

from tests.api.conftest import _upload
from tests.factories import make_truncated_pdf


def _process(api_client, path, filename, **kwargs):
    """Upload then process jobs until the document is terminal (done/failed)."""
    resp = _upload(api_client, path, filename)
    doc_id = resp.data["document"]["id"]
    queue = DbJobQueue()
    doc = Document.objects.get(pk=doc_id)
    while doc.status not in ("done", "failed"):
        job = queue.claim()
        if job is None:
            break
        process_job(job, queue, **kwargs)
        doc.refresh_from_db()
    return doc, job


@pytest.mark.django_db
def test_corrupt_pdf_fails_with_code_and_no_retry(api_client, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken broken broken broken")
    doc, job = _process(api_client, bad, "bad.pdf")
    assert doc.status == "failed"
    assert doc.error_code == "corrupt"
    assert job.status == "failed"
    assert job.attempts == 1  # permanent: failed, not retried


@pytest.mark.django_db
def test_encrypted_pdf_fails_with_code(api_client, encrypted_pdf):
    doc, job = _process(api_client, encrypted_pdf, "encrypted.pdf")
    assert doc.status == "failed"
    assert doc.error_code == "encrypted"
    assert job.status == "failed"
    assert job.attempts == 1


@pytest.mark.django_db
def test_transient_failure_retries_then_internal(api_client, digital_pdf, monkeypatch):
    from pipeline.extractors.pdf import PdfExtractor

    def boom(self, probe):
        raise RuntimeError("transient boom")

    monkeypatch.setattr(PdfExtractor, "plan", boom)

    doc, job = _process(api_client, digital_pdf, "doc.pdf")
    assert doc.status == "failed"
    assert doc.error_code == "internal"
    assert job.status == "failed"
    # initial attempt + retries up to WORKER_MAX_ATTEMPTS (3)
    assert job.attempts == 3

    # document got a requeue event at some point
    messages = [e.message for e in ProgressEvent.objects.filter(document=doc)]
    assert any("Retrying" in m for m in messages)


@pytest.mark.django_db
def test_transient_failure_requeues_below_cap(api_client, digital_pdf, monkeypatch, settings):
    settings.WORKER_MAX_ATTEMPTS = 5
    from pipeline.extractors.pdf import PdfExtractor

    def boom(self, probe):
        raise RuntimeError("boom")

    monkeypatch.setattr(PdfExtractor, "plan", boom)
    doc, job = _process(api_client, digital_pdf, "doc.pdf")
    assert doc.error_code == "internal"
    assert job.status == "failed"
    assert job.attempts == 5


@pytest.mark.django_db
def test_truncated_pdf_fails_corrupt(api_client, tmp_path):
    path = make_truncated_pdf(tmp_path=tmp_path)
    doc, job = _process(api_client, path, "truncated.pdf")
    assert doc.status == "failed"
    assert doc.error_code == "corrupt"


@pytest.mark.django_db
def test_failed_document_emits_failed_event(api_client, tmp_path):
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken broken")
    _process(api_client, bad, "bad.pdf")
    events = ProgressEvent.objects.filter(document__filename="bad.pdf")
    assert events.filter(status="failed").exists()