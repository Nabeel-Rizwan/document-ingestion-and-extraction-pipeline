"""Django admin configuration."""

from __future__ import annotations

from django.contrib import admin

from .models import Block, Document, Job, ProgressEvent


class JobInline(admin.TabularInline):
    model = Job
    extra = 0
    readonly_fields = ("id", "status", "attempts", "locked_at", "last_error", "created_at", "updated_at")
    can_delete = False


class BlockInline(admin.TabularInline):
    model = Block
    extra = 0
    readonly_fields = ("idx", "type", "text", "page", "metadata")


@admin.register(Document)
class DocumentAdmin(admin.ModelAdmin):
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
    list_filter = ("status", "stage", "method", "error_code")
    search_fields = ("filename", "sha256")
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
    inlines = [JobInline, BlockInline]


@admin.register(Block)
class BlockAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "idx", "type", "page")
    list_filter = ("type",)
    search_fields = ("text",)
    readonly_fields = ("document", "idx", "type", "text", "page", "metadata", "search")


@admin.register(Job)
class JobAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "status", "attempts", "locked_at", "created_at")
    list_filter = ("status",)
    readonly_fields = ("id", "document", "status", "attempts", "locked_at", "last_error", "created_at")


@admin.register(ProgressEvent)
class ProgressEventAdmin(admin.ModelAdmin):
    list_display = ("id", "document", "stage", "progress", "status", "created_at")
    list_filter = ("stage", "status")
    readonly_fields = ("document", "stage", "message", "progress", "status", "created_at")