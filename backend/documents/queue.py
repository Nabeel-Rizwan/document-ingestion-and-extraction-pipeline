"""Postgres-backed job queue.

The queue is a table claimed with ``SELECT ... FOR UPDATE SKIP LOCKED`` behind
a small Protocol, so a different queue implementation could be swapped in
without touching the worker.
"""

from __future__ import annotations

# timedelta used to compute the stale-lock cutoff time.
from datetime import timedelta
# Protocol enables structural typing for the queue interface.
from typing import Protocol

# Settings access for the stale-lock timeout.
from django.conf import settings
# Atomic blocks make claim/requeue operations race-safe.
from django.db import transaction
# Timezone-aware "now" for lock timestamps.
from django.utils import timezone

# Document and Job models backing the queue.
from .models import Document, Job


class JobQueue(Protocol):
    # Enqueue a new job for a document and return it.
    def enqueue(self, document: Document) -> Job: ...
    # Atomically claim the next available job, or None if none are ready.
    def claim(self) -> Job | None: ...
    # Mark a claimed job as successfully finished.
    def complete(self, job: Job) -> None: ...
    # Record a failure, optionally returning the job to the queue for retry.
    def fail(self, job: Job, *, retry: bool, error: str = "") -> None: ...
    # Re-queue running jobs whose locks have expired; returns the count.
    def requeue_stale(self) -> int: ...


class DbJobQueue:
    def enqueue(self, document: Document) -> Job:
        # Creating a queued row is what makes the job visible to workers.
        return Job.objects.create(document=document, status="queued")

    def claim(self) -> Job | None:
        # Wrap selection and update so the lock is held through the state change.
        with transaction.atomic():
            # SELECT ... FOR UPDATE SKIP LOCKED lets workers claim distinct rows.
            job = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(status="queued")
                .order_by("id")
                .first()
            )
            # No queued work available.
            if job is None:
                return None
            # Transition the claimed job to running and record the lock time.
            job.status = "running"
            job.locked_at = timezone.now()
            job.save(update_fields=["status", "locked_at", "updated_at"])
            return job

    def complete(self, job: Job) -> None:
        # Terminal success: clear the lock and mark done.
        job.status = "done"
        job.locked_at = None
        job.save(update_fields=["status", "locked_at", "updated_at"])

    def fail(self, job: Job, *, retry: bool, error: str = "") -> None:
        # Every failure consumes an attempt.
        job.attempts += 1
        job.last_error = error
        if retry:
            # Re-queue for another worker to pick up later.
            job.status = "queued"
            job.locked_at = None
            job.save(update_fields=["status", "locked_at", "last_error", "attempts", "updated_at"])
        else:
            # Terminal failure: leave the job failed.
            job.status = "failed"
            job.locked_at = None
            job.save(update_fields=["status", "locked_at", "last_error", "attempts", "updated_at"])

    def requeue_stale(self) -> int:
        """Re-queue running jobs whose lock has expired (worker died)."""
        # Jobs locked before this cutoff are presumed abandoned.
        cutoff = timezone.now() - timedelta(seconds=settings.WORKER_STALE_AFTER_SECONDS)
        # Materialise the stale set so it can be updated in a transaction.
        stale = list(Job.objects.filter(status="running", locked_at__lt=cutoff))
        # Nothing to do.
        if not stale:
            return 0
        # Requeue them together atomically.
        with transaction.atomic():
            for job in stale:
                job.status = "queued"
                job.locked_at = None
                job.save(update_fields=["status", "locked_at", "updated_at"])
        # Report how many jobs were recovered.
        return len(stale)