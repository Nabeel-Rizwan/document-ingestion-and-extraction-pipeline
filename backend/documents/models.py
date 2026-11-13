"""Data models for the documents app.

Documents carry denormalised status/stage/progress so reads are cheap and SSE
has a single source of truth. The Job table only handles queueing.
"""

# Enables postponed evaluation of annotations so type hints are strings at runtime.
from __future__ import annotations

# Standard-library UUID module used as the default for Document primary keys.
import uuid

# Postgres-specific GIN index type used for fast full-text search lookups.
from django.contrib.postgres.indexes import GinIndex
# Postgres tsvector column type that stores precomputed search vectors.
from django.contrib.postgres.search import SearchVectorField
# Core Django ORM module providing model/field definitions.
from django.db import models
# Timezone helpers for timezone-aware datetime values.
from django.utils import timezone

# Document/job statuses that are considered final (no further processing).
TERMINAL_STATUSES = ("done", "failed")

# Allowed values for Document.status, in lifecycle order.
DOCUMENT_STATUSES = ("queued", "processing", "done", "failed")
# Pipeline stages a document passes through; note statuses and stages differ.
STAGES = ("queued", "detecting", "extracting", "indexing", "done", "failed")
# Extraction methods; the empty string means "not yet determined".
METHODS = ("", "pdf_text", "pdf_ocr", "pdf_mixed", "docx", "txt")
# Stable error codes; the empty string means "no error".
ERROR_CODES = ("", "corrupt", "encrypted", "unsupported", "empty", "internal")

# Content block kinds emitted by the extraction pipeline.
BLOCK_TYPES = ("heading", "paragraph", "list_item", "table")


class Document(models.Model):
    # UUID primary key generated client-side; editable=False keeps it out of forms.
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Uploaded source file, stored under a date-sharded path documents/YYYY/MM/.
    file = models.FileField(upload_to="documents/%Y/%m/")
    # Content hash used to detect duplicates; unique=True enforces dedupe at DB level.
    sha256 = models.CharField(max_length=64, unique=True)
    # Original client-supplied file name (display only, not the storage path).
    filename = models.CharField(max_length=255)
    # Detected MIME type; blank default allows rows created before detection.
    mime = models.CharField(max_length=127, blank=True, default="")
    # File size in bytes; BigInteger because uploads can exceed 2 GB.
    size = models.BigIntegerField(default=0)

    # Lifecycle status; choices are (value, label) pairs derived from DOCUMENT_STATUSES.
    status = models.CharField(max_length=16, choices=[(s, s) for s in DOCUMENT_STATUSES], default="queued")
    # Current pipeline stage; drives the SSE progress display.
    stage = models.CharField(max_length=16, choices=[(s, s) for s in STAGES], default="queued")
    # Completion fraction from 0.0 to 1.0, updated as processing advances.
    progress = models.FloatField(default=0.0)
    # Extraction method chosen by the pipeline; empty until decided.
    method = models.CharField(max_length=16, choices=[(m, m) for m in METHODS], default="")
    # Number of pages; nullable because non-paged formats (e.g. docx) have none.
    page_count = models.IntegerField(null=True, blank=True)
    # Number of extracted content blocks stored for this document.
    block_count = models.IntegerField(default=0)
    # Non-fatal warnings list; JSONField stored as a JSON array in Postgres.
    warnings = models.JSONField(default=list, blank=True)
    # Human-readable error message for failed documents; blank when successful.
    error = models.TextField(blank=True, default="")
    # Machine-readable error code, chosen from ERROR_CODES.
    error_code = models.CharField(
        max_length=16, choices=[(c, c) for c in ERROR_CODES], default="", blank=True
    )

    # Set automatically on first insert and never changed thereafter.
    created_at = models.DateTimeField(auto_now_add=True)
    # Updated automatically on every save.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Newest documents first in default querysets.
        ordering = ["-created_at"]
        # Composite index speeds status-filtered, time-ordered listing queries.
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        # Human-readable representation shown in admin and logs.
        return f"{self.filename} ({self.id})"


class Block(models.Model):
    # Parent document; CASCADE deletes blocks when the document is deleted.
    # related_name="blocks" enables document.blocks reverse accessor.
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="blocks")
    # Zero-based position of this block within the document ordering.
    idx = models.PositiveIntegerField()
    # Block kind, constrained to the values in BLOCK_TYPES.
    type = models.CharField(max_length=16, choices=[(t, t) for t in BLOCK_TYPES])
    # Extracted text content of the block.
    text = models.TextField()
    # Source page number, or null for formats without pages.
    page = models.IntegerField(null=True, blank=True)
    # Arbitrary per-block extras (e.g. table cells); stored as a JSON object.
    metadata = models.JSONField(default=dict, blank=True)
    # Precomputed Postgres tsvector for full-text search; populated by the pipeline.
    # null=True allows rows created before the search update; editable=False hides it.
    search = SearchVectorField(null=True, editable=False)

    

    class Meta:
        # Default ordering by position within the document.
        ordering = ["idx"]
        # Enforces one block per (document, idx) pair at the database level.
        constraints = [models.UniqueConstraint(fields=["document", "idx"], name="uniq_document_idx")]
        # GIN index makes the search tsvector field queryable efficiently.
        indexes = [GinIndex(fields=["search"], name="block_search_gin")]

    def __str__(self) -> str:
        # Identifies the block by its document and position.
        return f"{self.document_id}:{self.idx} {self.type}"


class Job(models.Model):
    # Auto-incrementing 64-bit primary key; doubles as the queue ordering key.
    id = models.BigAutoField(primary_key=True)
    # Document this job processes; CASCADE removes jobs with their document.
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="jobs")
    # Job state; "queued" means claimable, "running" means locked by a worker.
    status = models.CharField(
        max_length=16,
        choices=[("queued", "queued"), ("running", "running"), ("done", "done"), ("failed", "failed")],
        default="queued",
    )
    # Number of processing attempts so far; drives retry/backoff decisions.
    attempts = models.PositiveIntegerField(default=0)
    # When the job was claimed; used to detect stale locks after a worker dies.
    locked_at = models.DateTimeField(null=True, blank=True)
    # Most recent error text, retained for diagnostics after a failure.
    last_error = models.TextField(blank=True, default="")
    # Set once when the job row is first inserted.
    created_at = models.DateTimeField(auto_now_add=True)
    # Refreshed automatically on each save.
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        # Oldest jobs first, matching FIFO claim order.
        ordering = ["id"]
        # Composite index supports filtering queued jobs ordered by id.
        indexes = [models.Index(fields=["status", "id"])]

    def __str__(self) -> str:
        # Identifies the job and its current state.
        return f"Job {self.id} ({self.status})"


class ProgressEvent(models.Model):
    # Auto-incrementing primary key; also the SSE event cursor.
    id = models.BigAutoField(primary_key=True)
    # Document this event belongs to; CASCADE cleans up events with the document.
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="progress_events")
    # Pipeline stage the event was emitted for (free-form, not choices-constrained).
    stage = models.CharField(max_length=16)
    # Optional human-readable detail for the event.
    message = models.TextField(blank=True, default="")
    # Progress fraction reported at the time of the event.
    progress = models.FloatField(default=0.0)
    # Document status at the time of the event; defaults to "processing".
    status = models.CharField(max_length=16, default="processing")
    # Insert timestamp; used to order and stream events.
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        # Events replay in creation order for SSE.
        ordering = ["id"]
        # Composite index supports fetching one document's events by cursor.
        indexes = [models.Index(fields=["document", "id"])]

    def __str__(self) -> str:
        # Compact summary of the event for admin and logs.
        return f"{self.document_id}:{self.id} {self.stage} {self.progress}"