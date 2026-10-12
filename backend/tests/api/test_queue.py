"""Job queue tests: claiming, stale requeueing, concurrency.

What it does:
    Verifies the DB-backed job queue: sequential claims hand out distinct
    jobs, crashed-worker locks expire via requeue_stale(), and concurrent
    claimants never receive the same job twice.

How it works:
    - Uploads create queued Jobs; DbJobQueue.claim() atomically transitions
      queued->running using SELECT ... FOR UPDATE SKIP LOCKED.
    - Stale tests backdate locked_at past WORKER_STALE_AFTER_SECONDS.
    - The concurrency test races 3 threads x 10 claim loops behind a Barrier
      and asserts all claimed IDs are unique.
"""

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
    # What: two queued jobs are handed out one-by-one, then queue is empty.
    # How: uploads PDF+DOCX (2 jobs), claims twice asserting distinct ids and
    #   running status, then asserts a third claim returns None.
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
    # What: a running job whose lock expired is reset to queued for retry.
    # How: uploads + claims one job, backdates locked_at beyond the stale
    #   threshold, calls requeue_stale() (asserts count==1), then checks the
    #   row is queued with lock cleared.
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
    # What: recently-locked running jobs are NOT considered stale.
    # How: uploads + claims, immediately calls requeue_stale() and asserts 0
    #   rows were reset.
    _upload(api_client, digital_pdf, "a.pdf")
    queue = DbJobQueue()
    queue.claim()
    assert queue.requeue_stale() == 0


@pytest.mark.django_db(transaction=True)
def test_concurrent_claims_never_return_same_job(api_client, digital_pdf, docx, tmp_path):
    """Two threads racing to claim never get the same job (skip_locked)."""
    # What: proves claim() is race-safe under real DB concurrency.
    # How: uploads 3 jobs, spawns 3 threads released simultaneously by a
    #   Barrier; each loops claim()+complete() recording ids under a Lock.
    #   Needs transaction=True so threads see committed rows.
    from tests.factories import make_scanned_pdf

    for path, name in [
        (digital_pdf, "a.pdf"),
        (docx, "b.docx"),
        (make_scanned_pdf(pages=1, tmp_path=tmp_path), "c.pdf"),
    ]:
        _upload(api_client, path, name)

    seen: list[int] = []  # all job ids claimed across threads
    lock = threading.Lock()  # guards `seen` appends
    barrier = threading.Barrier(3)  # releases all 3 threads at once

    def claimer():
        # What: worker loop run in each thread.
        # How: opens its own queue handle, waits on the barrier for a fair
        #   race, then claims up to 10 jobs, recording + completing each.
        from django.db import connection

        queue = DbJobQueue()
        barrier.wait()  # line up all threads so claims truly race
        try:
            for _ in range(10):
                job = queue.claim()  # SKIP LOCKED ensures no double-claim
                if job is None:
                    break  # queue drained for this thread
                with lock:
                    seen.append(job.id)
                queue.complete(job)  # mark done so test DB stays clean
        finally:
            connection.close()  # don't leak this thread's DB connection

    threads = [threading.Thread(target=claimer) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    from django.db import connection as main_connection

    main_connection.close()
    assert len(seen) == len(set(seen)), "duplicate job claimed"
    assert len(seen) == Job.objects.count()
