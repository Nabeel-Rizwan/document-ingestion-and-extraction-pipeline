"""DRF serializers matching the API contract exactly."""

from __future__ import annotations

from rest_framework import serializers

from ..models import Block, Document


class DocumentSerializer(serializers.ModelSerializer):
    id = serializers.UUIDField(read_only=True)
    method = serializers.CharField(read_only=True)
    page_count = serializers.IntegerField(read_only=True)
    block_count = serializers.IntegerField(read_only=True)
    warnings = serializers.JSONField(read_only=True)
    error = serializers.CharField(read_only=True)
    error_code = serializers.CharField(read_only=True)
    progress = serializers.FloatField(read_only=True)

    class Meta:
        model = Document
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
        read_only_fields = fields


class BlockSerializer(serializers.ModelSerializer):
    id = serializers.IntegerField(read_only=True)
    idx = serializers.IntegerField(read_only=True)
    page = serializers.IntegerField(read_only=True)
    metadata = serializers.JSONField(read_only=True)

    class Meta:
        model = Block
        fields = ["id", "idx", "type", "text", "page", "metadata"]
        read_only_fields = fields