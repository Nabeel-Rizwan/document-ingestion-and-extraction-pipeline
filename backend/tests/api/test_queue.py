"""Job queue tests: claiming, stale requeueing, concurrency."""

from __future__ import annotations

import threading
import time
from datetime import timedelta

import pytest

from django.utils import timezone

from documents.models import Document, Job
from documents.queue import DbJobQueue

from tests.api.conftest import _upload


@pytest.mark.django_db
def test_sequential_claims_return_different_jobs(api_client, digital_pdf, docx):
    _upload(api_client, digital_pdf, "a.pdf")
    _upload(api_client, docx, "b.docx")
    queue = DbJobQueue()
    first = queue.claim()
    second = queue.claim()
    assert first is not None and second is not None
    assert first.id != second.id
    assert first.status == "running"
    assert second.status == "running"
    # queue is now empty
    assert queue.claim() is None


@pytest.mark.django_db
def test_stale_running_jobs_are_requeued(api_client, digital_pdf, settings):
    _upload(api_client, digital_pdf, "a.pdf")
    queue = DbJobQueue()
    job = queue.claim()
    # simulate a crashed worker: lock expired long ago
    job.locked_at = timezone.now() - timedelta(seconds=settings.WORKER_STALE_AFTER_SECONDS + 60)
    job.save(update_fields=["locked_at", "updated_at"])

    assert queue.requeue_stale() == 1
    job.refresh_from_db()
    assert job.status == "queued"
    assert job.locked_at is None


@pytest.mark.django_db
def test_fresh_running_jobs_not_requeued(api_client, digital_pdf):
    _upload(api_client, digital_pdf, "a.pdf")
    queue = DbJobQueue()
    queue.claim()
    assert queue.requeue_stale() == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_never_return_same_job(api_client, digital_pdf, docx, tmp_path):
    """Two threads racing to claim never get the same job (skip_locked)."""
    from tests.factories import make_scanned_pdf

    for path, name in [
        (digital_pdf, "a.pdf"),
        (docx, "b.docx"),
        (make_scanned_pdf(pages=1, tmp_path=tmp_path), "c.pdf"),
    ]:
        _upload(api_client, path, name)

    seen: list[int] = []
    lock = threading.Lock()
    barrier = threading.Barrier(3)

    def claimer():
        from django.db import connection

        queue = DbJobQueue()
        barrier.wait()
        try:
            for _ in range(10):
                job = queue.claim()
                if job is None:
                    break
                with lock:
                    seen.append(job.id)
                queue.complete(job)
        finally:
            connection.close()

    threads = [threading.Thread(target=claimer) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    from django.db import connection as main_connection

    main_connection.close()
    assert len(seen) == len(set(seen)), "duplicate job claimed"
    assert len(seen) == Job.objects.count()