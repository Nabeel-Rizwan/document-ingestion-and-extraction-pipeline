"""Data models for the documents app.

Documents carry denormalised status/stage/progress so reads are cheap and SSE
has a single source of truth. The Job table only handles queueing.
"""

from __future__ import annotations

import uuid

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.utils import timezone

TERMINAL_STATUSES = ("done", "failed")

DOCUMENT_STATUSES = ("queued", "processing", "done", "failed")
STAGES = ("queued", "detecting", "extracting", "indexing", "done", "failed")
METHODS = ("", "pdf_text", "pdf_ocr", "pdf_mixed", "docx")
ERROR_CODES = ("", "corrupt", "encrypted", "unsupported", "empty", "internal")

BLOCK_TYPES = ("heading", "paragraph", "list_item", "table")


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="documents/%Y/%m/")
    sha256 = models.CharField(max_length=64, unique=True)
    filename = models.CharField(max_length=255)
    mime = models.CharField(max_length=127, blank=True, default="")
    size = models.BigIntegerField(default=0)

    status = models.CharField(max_length=16, choices=[(s, s) for s in DOCUMENT_STATUSES], default="queued")
    stage = models.CharField(max_length=16, choices=[(s, s) for s in STAGES], default="queued")
    progress = models.FloatField(default=0.0)
    method = models.CharField(max_length=16, choices=[(m, m) for m in METHODS], default="")
    page_count = models.IntegerField(null=True, blank=True)
    block_count = models.IntegerField(default=0)
    warnings = models.JSONField(default=list, blank=True)
    error = models.TextField(blank=True, default="")
    error_code = models.CharField(
        max_length=16, choices=[(c, c) for c in ERROR_CODES], default="", blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["status", "created_at"])]

    def __str__(self) -> str:
        return f"{self.filename} ({self.id})"


class Block(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="blocks")
    idx = models.PositiveIntegerField()
    type = models.CharField(max_length=16, choices=[(t, t) for t in BLOCK_TYPES])
    text = models.TextField()
    page = models.IntegerField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    search = SearchVectorField(null=True, editable=False)

    class Meta:
        ordering = ["idx"]
        constraints = [models.UniqueConstraint(fields=["document", "idx"], name="uniq_document_idx")]
        indexes = [GinIndex(fields=["search"], name="block_search_gin")]

    def __str__(self) -> str:
        return f"{self.document_id}:{self.idx} {self.type}"


class Job(models.Model):
    id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="jobs")
    status = models.CharField(
        max_length=16,
        choices=[("queued", "queued"), ("running", "running"), ("done", "done"), ("failed", "failed")],
        default="queued",
    )
    attempts = models.PositiveIntegerField(default=0)
    locked_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["status", "id"])]

    def __str__(self) -> str:
        return f"Job {self.id} ({self.status})"


class ProgressEvent(models.Model):
    id = models.BigAutoField(primary_key=True)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="progress_events")
    stage = models.CharField(max_length=16)
    message = models.TextField(blank=True, default="")
    progress = models.FloatField(default=0.0)
    status = models.CharField(max_length=16, default="processing")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        indexes = [models.Index(fields=["document", "id"])]

    def __str__(self) -> str:
        return f"{self.document_id}:{self.id} {self.stage} {self.progress}"