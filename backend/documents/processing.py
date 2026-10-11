"""Worker-side processing: runs the pipeline for one job.

All error handling lives here. ExtractionError subclasses are permanent and
fail the document immediately; any other exception is transient and retried up
to ``WORKER_MAX_ATTEMPTS``. No exception may escape.
"""

from __future__ import annotations

# Standard logging for worker diagnostics.
import logging

# Django settings access for engine/attempt configuration.
from django.conf import settings
# Builds a tsvector expression for populating the Block.search field.
from django.contrib.postgres.search import SearchVector
# Atomic transactions keep block replacement all-or-nothing.
from django.db import transaction

# Base class for permanent extraction failures defined by the pipeline.
from pipeline.errors import ExtractionError
# Mock OCR backend used for local development and as a fallback.
from pipeline.ocr.mock import MockOcrClient
# Factory that builds the default extraction registry.
from pipeline.registry import default_registry
# The pipeline runner that turns a file into blocks.
from pipeline.service import run_pipeline

# Local models and helpers used by the worker.
from .models import Block, Document, ProgressEvent
# DB-backed progress reporter injected into the pipeline.
from .progress import DbProgressReporter
# Queue protocol implementation used to mark jobs done/failed.
from .queue import JobQueue
# Context manager that yields a local filesystem path for a document.
from .storage import local_path

# Module-level logger for this worker module.
logger = logging.getLogger(__name__)


def build_ocr_client():
    """OCR client factory. Swapping in a real engine requires only this change.

    ``OCR_ENGINE`` selects the backend (``tesseract`` by default, or ``mock``).
    If Tesseract is selected but the binary is unavailable, we fall back to the
    mock client so local development still works, with a loud warning.
    """
    # Read the configured engine name, defaulting to tesseract.
    engine = getattr(settings, "OCR_ENGINE", "tesseract")
    # Explicit mock mode short-circuits before touching the filesystem.
    if engine == "mock":
        return MockOcrClient(latency_s=settings.OCR_MOCK_LATENCY)

    # Imported lazily so the module loads even if no real OCR stack is present.
    import shutil

    # If the tesseract binary is missing, degrade to mock with a warning.
    if shutil.which("tesseract") is None:
        logger.warning(
            "OCR_ENGINE=%r but the 'tesseract' binary was not found on PATH; "
            "falling back to mock OCR. Install tesseract for real OCR.",
            engine,
        )
        return MockOcrClient(latency_s=settings.OCR_MOCK_LATENCY)

    # Import the real client only when it will actually be used.
    from pipeline.ocr.tesseract import TesseractOcrClient

    # Construct the real OCR client with configured languages.
    return TesseractOcrClient(languages=getattr(settings, "OCR_LANGUAGES", "eng"))


def _mark_failed(doc: Document, *, code: str, error: str, progress: float = 1.0) -> None:
    # Move the document into its terminal failed state.
    doc.status = "failed"
    doc.stage = "failed"
    doc.error = error
    doc.error_code = code
    doc.progress = progress
    # Persist only the changed columns for efficiency.
    doc.save(update_fields=["status", "stage", "error", "error_code", "progress", "updated_at"])
    # Append an event so SSE clients observe the failure.
    ProgressEvent.objects.create(
        document=doc, status="failed", stage="failed", message=error, progress=progress
    )


def _requeue(doc: Document, job) -> None:
    # Reset the document to a clean queued state for a retry.
    doc.status = "queued"
    doc.stage = "queued"
    doc.progress = 0.0
    doc.error = ""
    doc.error_code = ""
    # Save just the reset fields.
    doc.save(update_fields=["status", "stage", "progress", "error", "error_code", "updated_at"])
    # Record a progress event noting which attempt is being started.
    ProgressEvent.objects.create(
        document=doc,
        status="queued",
        stage="queued",
        message=f"Retrying (attempt {job.attempts})",
        progress=0.0,
    )


def process_job(job, queue: JobQueue, registry=None, ocr=None) -> None:
    """Process a single job. Never raises."""
    # The document is the denormalised record updated throughout processing.
    doc = job.document

    # Flip status to processing before the long-running work begins.
    doc.status = "processing"
    doc.save(update_fields=["status", "updated_at"])
    # Emit a start event so clients see immediate feedback.
    ProgressEvent.objects.create(
        document=doc, status="processing", stage=doc.stage, message="Processing started", progress=doc.progress
    )

    try:
        # Build the OCR client lazily unless one was injected (tests reuse it).
        if ocr is None:
            ocr = build_ocr_client()
        # Build the extraction registry lazily unless injected.
        if registry is None:
            registry = default_registry(ocr=ocr)

        # Obtain a real local path; temp copies are cleaned up on exit.
        with local_path(doc) as path:
            # Reporter persists denormalised progress and event rows.
            reporter = DbProgressReporter(doc)
            # Run the full extraction pipeline for this file.
            output = run_pipeline(str(path), doc.filename, reporter, registry=registry, ocr=ocr)

        # --- indexing stage -------------------------------------------------
        # Advance the displayed stage to indexing.
        doc.stage = "indexing"
        doc.save(update_fields=["stage", "updated_at"])
        # Replace and reindex all blocks in a single transaction.
        with transaction.atomic():
            # Delete any previous blocks so reruns are idempotent.
            Block.objects.filter(document=doc).delete()
            # Build unsaved Block instances from the pipeline output.
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
            # Bulk insert in batches to limit memory and round-trips.
            Block.objects.bulk_create(rows, batch_size=500)
            # Compute the search tsvector for every inserted block.
            Block.objects.filter(document=doc).update(
                search=SearchVector("text", config="english")
            )

        # Copy extraction metadata from the pipeline result onto the document.
        doc.method = output.result.method
        doc.page_count = output.result.page_count
        doc.block_count = len(rows)
        doc.warnings = output.result.warnings
        # Mark the document complete.
        doc.status = "done"
        doc.stage = "done"
        doc.progress = 1.0
        # Persist all the final result fields together.
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
        # Emit the terminal success event.
        ProgressEvent.objects.create(
            document=doc, status="done", stage="done", message="Done", progress=1.0
        )
        # Mark the queue job as done.
        queue.complete(job)

    # Permanent errors are defined by the pipeline and never retried.
    except ExtractionError as exc:
        logger.info("Permanent failure for %s: %s", doc.id, exc.message)
        try:
            # Persist the terminal failed state on the document.
            _mark_failed(doc, code=exc.code, error=exc.message)
        except Exception:  # pragma: no cover - last-resort guard
            # Never let failure-state persistence mask the original error.
            logger.exception("Failed to persist failure state for %s", doc.id)
        # Fail the job without retrying.
        queue.fail(job, retry=False, error=exc.message)

    # Any other error is treated as transient and retried up to the limit.
    except Exception as exc:  # noqa: BLE001 - transient, retryable
        logger.exception("Transient failure for %s", doc.id)
        # The attempt count after this failure.
        next_attempt = job.attempts + 1
        # Retry while under the configured maximum attempts.
        if next_attempt < settings.WORKER_MAX_ATTEMPTS:
            queue.fail(job, retry=True, error=repr(exc))
            try:
                # Reset the document so a later worker picks it up again.
                _requeue(doc, job)
            except Exception:  # pragma: no cover
                logger.exception("Failed to persist requeue state for %s", doc.id)
        else:
            # Attempts exhausted: fail the job permanently.
            queue.fail(job, retry=False, error=repr(exc))
            try:
                # Record a generic internal error on the document.
                _mark_failed(doc, code="internal", error=f"Internal error: {exc!r}")
            except Exception:  # pragma: no cover
                logger.exception("Failed to persist failure state for %s", doc.id)