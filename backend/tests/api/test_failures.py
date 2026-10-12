"""Failure handling tests: corrupt/encrypted/transient failures.

What it does:
    Verifies the processing pipeline maps failures to stable error_codes
    (corrupt/encrypted/internal), retries transient errors up to
    WORKER_MAX_ATTEMPTS, and emits ProgressEvents for observability.

How it works:
    - Local ``_process`` uploads a file then loops claim()+process_job()
      until the Document reaches a terminal status (done/failed).
    - Permanent errors (corrupt/encrypted) assert attempts==1 (no retry);
      transient errors use monkeypatch to force PdfExtractor.plan to raise
      and assert retry counts + "Retrying" progress messages.
"""

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
    # What: drives a document to done/failed without the background worker.
    # How: uploads (creating Document+Job), then repeatedly claims the next
    #   job and runs process_job (forwarding kwargs like ocr overrides)
    #   until status is terminal or queue is empty.
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
    # What: garbage PDF bytes fail permanently as corrupt, no retry.
    # How: writes broken bytes, drives to terminal, asserts doc+job failed,
    #   error_code==corrupt, attempts==1.
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken broken broken broken")
    doc, job = _process(api_client, bad, "bad.pdf")
    assert doc.status == "failed"
    assert doc.error_code == "corrupt"
    assert job.status == "failed"
    assert job.attempts == 1  # permanent: failed, not retried


@pytest.mark.django_db
def test_encrypted_pdf_fails_with_code(api_client, encrypted_pdf):
    # What: password-protected PDF fails permanently as encrypted.
    # How: uploads the encrypted fixture, drives to terminal, asserts
    #   failed + encrypted code + single attempt.
    doc, job = _process(api_client, encrypted_pdf, "encrypted.pdf")
    assert doc.status == "failed"
    assert doc.error_code == "encrypted"
    assert job.status == "failed"
    assert job.attempts == 1


@pytest.mark.django_db
def test_transient_failure_retries_then_internal(api_client, digital_pdf, monkeypatch):
    # What: unexpected RuntimeErrors are retried to the cap, then marked
    #   internal with a "Retrying" progress trail.
    # How: monkeypatches PdfExtractor.plan to always raise, drives to
    #   terminal, asserts failed/internal + attempts==3 (default cap), and
    #   that some ProgressEvent message contains "Retrying".
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
    # What: raising the retry cap raises the observed attempt count.
    # How: sets WORKER_MAX_ATTEMPTS=5, forces plan() to boom, drives to
    #   terminal, asserts internal + attempts==5.
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
    # What: truncated-trailer PDF maps to corrupt (not internal).
    # How: builds the truncated fixture, drives to terminal, asserts
    #   failed + corrupt code.
    path = make_truncated_pdf(tmp_path=tmp_path)
    doc, job = _process(api_client, path, "truncated.pdf")
    assert doc.status == "failed"
    assert doc.error_code == "corrupt"


@pytest.mark.django_db
def test_failed_document_emits_failed_event(api_client, tmp_path):
    # What: failed docs always leave a failed ProgressEvent for SSE/polling.
    # How: uploads broken bytes, drives to terminal, queries ProgressEvent
    #   by filename and asserts a failed-status event exists.
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"%PDF-1.4 broken broken")
    _process(api_client, bad, "bad.pdf")
    events = ProgressEvent.objects.filter(document__filename="bad.pdf")
    assert events.filter(status="failed").exists()
