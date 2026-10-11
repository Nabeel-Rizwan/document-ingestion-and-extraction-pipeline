"""Django admin configuration."""

from __future__ import annotations

# Django's admin site registration API.
from django.contrib import admin

# Models exposed through the admin.
from .models import Block, Document, Job, ProgressEvent


class JobInline(admin.TabularInline):
    # Jobs are edited inline on the Document change page.
    model = Job
    # extra=0 renders no blank forms for adding new inline rows.
    extra = 0
    # All fields read-only because jobs are managed by the worker, not humans.
    readonly_fields = ("id", "status", "attempts", "locked_at", "last_error", "created_at", "updated_at")
    # Prevents deleting jobs from the inline (would break queue integrity).
    can_delete = False


class BlockInline(admin.TabularInline):
    # Extracted blocks are shown inline on the Document change page.
    model = Block
    # No blank add forms.
    extra = 0
    # Blocks are produced by the pipeline, so every field is read-only.
    readonly_fields = ("idx", "type", "text", "page", "metadata")


# Registers DocumentAdmin for the Document model on the admin site.
@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
    # Columns shown in the document changelist.
    list_display = (
        "filename",
        "status",
        "stage",
        "progress",
        "method",
        "block_count",
        "size",
        "created_at",
    )
    # Right-hand filters for the changelist.
    list_filter = ("status", "stage", "method", "error_code")
    # Fields included in the admin search box.
    search_fields = ("filename", "sha256")
    # Read-only fields enforcing that documents are written only by the app.
    readonly_fields = (
        "id",
        "sha256",
        "filename",
        "mime",
        "size",
        "status",
        "stage",
        "progress",
        "method",
        "page_count",
        "block_count",
        "warnings",
        "error",
        "error_code",
        "created_at",
        "updated_at",
    )
    # Embeds related jobs and blocks on the change page.
    inlines = [JobInline, BlockInline]


# Registers BlockAdmin for the Block model.
@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    # Columns shown in the block changelist.
    list_display = ("id", "document", "idx", "type", "page")
    # Filter blocks by their kind.
    list_filter = ("type",)
    # Full-text search over block content.
    search_fields = ("text",)
    # Blocks are pipeline-generated and read-only in the admin.
    readonly_fields = ("document", "idx", "type", "text", "page", "metadata", "search")


# Registers JobAdmin for the Job model.
@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    # Columns shown in the job changelist.
    list_display = ("id", "document", "status", "attempts", "locked_at", "created_at")
    # Filter jobs by state.
    list_filter = ("status",)
    # Jobs are managed by the worker and read-only here.
    readonly_fields = ("id", "document", "status", "attempts", "locked_at", "last_error", "created_at")


# Registers ProgressEventAdmin for the ProgressEvent model.
@admin.register(ProgressEvent)
class ProgressEventAdmin(admin.ModelAdmin):
    # Columns shown in the progress event changelist.
    list_display = ("id", "document", "stage", "progress", "status", "created_at")
    # Filters for narrowing events by stage or status.
    list_filter = ("stage", "status")
    # Progress events are append-only and read-only in the admin.
    readonly_fields = ("document", "stage", "message", "progress", "status", "created_at")