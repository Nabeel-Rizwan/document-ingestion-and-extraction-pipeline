"""Postgres-backed job queue.

The queue is a table claimed with ``SELECT ... FOR UPDATE SKIP LOCKED`` behind
a small Protocol, so a different queue implementation could be swapped in
without touching the worker.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Protocol

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Document, Job


class JobQueue(Protocol):
    def enqueue(self, document: Document) -> Job: ...
    def claim(self) -> Job | None: ...
    def complete(self, job: Job) -> None: ...
    def fail(self, job: Job, *, retry: bool, error: str = "") -> None: ...
    def requeue_stale(self) -> int: ...


class DbJobQueue:
    def enqueue(self, document: Document) -> Job:
        return Job.objects.create(document=document, status="queued")

    def claim(self) -> Job | None:
        with transaction.atomic():
            job = (
                Job.objects.select_for_update(skip_locked=True)
                .filter(status="queued")
                .order_by("id")
                .first()
            )
            if job is None:
                return None
            job.status = "running"
            job.locked_at = timezone.now()
            job.save(update_fields=["status", "locked_at", "updated_at"])
            return job

    def complete(self, job: Job) -> None:
        job.status = "done"
        job.locked_at = None
        job.save(update_fields=["status", "locked_at", "updated_at"])

    def fail(self, job: Job, *, retry: bool, error: str = "") -> None:
        job.attempts += 1
        job.last_error = error
        if retry:
            job.status = "queued"
            job.locked_at = None
            job.save(update_fields=["status", "locked_at", "last_error", "attempts", "updated_at"])
        else:
            job.status = "failed"
            job.locked_at = None
            job.save(update_fields=["status", "locked_at", "last_error", "attempts", "updated_at"])

    def requeue_stale(self) -> int:
        """Re-queue running jobs whose lock has expired (worker died)."""
        cutoff = timezone.now() - timedelta(seconds=settings.WORKER_STALE_AFTER_SECONDS)
        stale = list(Job.objects.filter(status="running", locked_at__lt=cutoff))
        if not stale:
            return 0
        with transaction.atomic():
            for job in stale:
                job.status = "queued"
                job.locked_at = None
                job.save(update_fields=["status", "locked_at", "updated_at"])
        return len(stale)