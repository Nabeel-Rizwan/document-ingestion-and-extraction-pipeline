"""Worker-side processing: runs the pipeline for one job.

All error handling lives here. ExtractionError subclasses are permanent and
fail the document immediately; any other exception is transient and retried up
to ``WORKER_MAX_ATTEMPTS``. No exception may escape.
"""

from __future__ import annotations

import logging

from django.conf import settings
from django.contrib.postgres.search import SearchVector
from django.db import transaction

from pipeline.errors import ExtractionError
from pipeline.ocr.mock import MockOcrClient
from pipeline.registry import default_registry
from pipeline.service import run_pipeline

from .models import Block, Document, ProgressEvent
from .progress import DbProgressReporter
from .queue import JobQueue
from .storage import local_path

logger = logging.getLogger(__name__)


def build_ocr_client():
    """OCR client factory. Swapping in a real engine requires only this change."""
    return MockOcrClient(latency_s=settings.OCR_MOCK_LATENCY)


def _mark_failed(doc: Document, *, code: str, error: str, progress: float = 1.0) -> None:
    doc.status = "failed"
    doc.stage = "failed"
    doc.error = error
    doc.error_code = code
    doc.progress = progress
    doc.save(update_fields=["status", "stage", "error", "error_code", "progress", "updated_at"])
    ProgressEvent.objects.create(
        document=doc, status="failed", stage="failed", message=error, progress=progress
    )


def _requeue(doc: Document, job) -> None:
    doc.status = "queued"
    doc.stage = "queued"
    doc.progress = 0.0
    doc.error = ""
    doc.error_code = ""
    doc.save(update_fields=["status", "stage", "progress", "error", "error_code", "updated_at"])
    ProgressEvent.objects.create(
        document=doc,
        status="queued",
        stage="queued",
        message=f"Retrying (attempt {job.attempts})",
        progress=0.0,
    )


def process_job(job, queue: JobQueue, registry=None, ocr=None) -> None:
    """Process a single job. Never raises."""
    doc = job.document

    doc.status = "processing"
    doc.save(update_fields=["status", "updated_at"])
    ProgressEvent.objects.create(
        document=doc, status="processing", stage=doc.stage, message="Processing started", progress=doc.progress
    )

    try:
        if ocr is None:
            ocr = build_ocr_client()
        if registry is None:
            registry = default_registry(ocr=ocr)

        with local_path(doc) as path:
            reporter = DbProgressReporter(doc)
            output = run_pipeline(str(path), doc.filename, reporter, registry=registry, ocr=ocr)

        # --- indexing stage -------------------------------------------------
        doc.stage = "indexing"
        doc.save(update_fields=["stage", "updated_at"])
        with transaction.atomic():
            Block.objects.filter(document=doc).delete()
            rows = [
                Block(
                    document=doc,
                    idx=idx,
                    type=b.type,
                    text=b.text,
                    page=b.page,
                    metadata=b.metadata,
                )
                for idx, b in enumerate(output.result.blocks)
            ]
            Block.objects.bulk_create(rows, batch_size=500)
            Block.objects.filter(document=doc).update(
                search=SearchVector("text", config="english")
            )

        doc.method = output.result.method
        doc.page_count = output.result.page_count
        doc.block_count = len(rows)
        doc.warnings = output.result.warnings
        doc.status = "done"
        doc.stage = "done"
        doc.progress = 1.0
        doc.save(
            update_fields=[
                "method",
                "page_count",
                "block_count",
                "warnings",
                "status",
                "stage",
                "progress",
                "updated_at",
            ]
        )
        ProgressEvent.objects.create(
            document=doc, status="done", stage="done", message="Done", progress=1.0
        )
        queue.complete(job)

    except ExtractionError as exc:
        logger.info("Permanent failure for %s: %s", doc.id, exc.message)
        try:
            _mark_failed(doc, code=exc.code, error=exc.message)
        except Exception:  # pragma: no cover - last-resort guard
            logger.exception("Failed to persist failure state for %s", doc.id)
        queue.fail(job, retry=False, error=exc.message)

    except Exception as exc:  # noqa: BLE001 - transient, retryable
        logger.exception("Transient failure for %s", doc.id)
        next_attempt = job.attempts + 1
        if next_attempt < settings.WORKER_MAX_ATTEMPTS:
            queue.fail(job, retry=True, error=repr(exc))
            try:
                _requeue(doc, job)
            except Exception:  # pragma: no cover
                logger.exception("Failed to persist requeue state for %s", doc.id)
        else:
            queue.fail(job, retry=False, error=repr(exc))
            try:
                _mark_failed(doc, code="internal", error=f"Internal error: {exc!r}")
            except Exception:  # pragma: no cover
                logger.exception("Failed to persist failure state for %s", doc.id)