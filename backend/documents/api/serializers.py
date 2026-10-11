"""DRF serializers matching the API contract exactly."""

# Enable postponed evaluation of annotations (PEP 563).
from __future__ import annotations

# DRF's serializer toolkit (serializers, ModelSerializer, field classes).
from rest_framework import serializers

# Import the ORM models that these serializers wrap.
from ..models import Block, Document


class DocumentSerializer(serializers.ModelSerializer):
    # Explicitly declare nullable/typed fields as read-only so clients cannot write them.
    id = serializers.UUIDField(read_only=True)
    method = serializers.CharField(read_only=True)
    page_count = serializers.IntegerField(read_only=True)
    block_count = serializers.IntegerField(read_only=True)
    warnings = serializers.JSONField(read_only=True)
    error = serializers.CharField(read_only=True)
    error_code = serializers.CharField(read_only=True)
    progress = serializers.FloatField(read_only=True)

    class Meta:
        # Bind this serializer to the Document model.
        model = Document
        # Whitelist the exact field set exposed by the API contract.
        fields = [
            "id",
            "filename",
            "mime",
            "size",
            "sha256",
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
        ]
        # Every listed field is read-only; documents are created implicitly via upload.
        read_only_fields = fields


class BlockSerializer(serializers.ModelSerializer):
    # Declare typed fields as read-only; blocks are server-generated, never client-written.
    id = serializers.IntegerField(read_only=True)
    idx = serializers.IntegerField(read_only=True)
    page = serializers.IntegerField(read_only=True)
    metadata = serializers.JSONField(read_only=True)

    class Meta:
        # Bind this serializer to the Block model.
        model = Block
        # Fields returned for each extracted content block.
        fields = ["id", "idx", "type", "text", "page", "metadata"]
        # Blocks are read-only representations.
        read_only_fields = fields