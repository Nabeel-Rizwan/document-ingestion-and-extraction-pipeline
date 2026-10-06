"""REST API views.

All endpoints return the contract's error envelope
``{"error": {"code", "message"}}`` on failure.
"""

from __future__ import annotations

import hashlib
import tempfile

from django.conf import settings
from django.core.files import File
from django.db import transaction
from django.http import Http404
from rest_framework import status, viewsets
from rest_framework.decorators import api_view
from rest_framework.exceptions import APIException
from rest_framework.negotiation import DefaultContentNegotiation
from rest_framework.parsers import MultiPartParser
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from pipeline.errors import EmptyDocumentError
from pipeline.probe import build_probe
from pipeline.registry import default_registry

from ..models import Document, Job
from ..services import CONTENT_FORMATS, get_content, get_document, list_documents, search_blocks
from .serializers import BlockSerializer, DocumentSerializer


class ContractError(APIException):
    """Carries the contract's machine code alongside the HTTP status."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        self.code = code
        self.status_code = http_status
        self.detail = {"error": {"code": code, "message": message}}


def api_exception_handler(exc, context):
    """Translate DRF exceptions into the contract's error envelope."""
    if isinstance(exc, ContractError):
        return Response(exc.detail, status=exc.status_code)
    if isinstance(exc, Http404):
        return Response(
            {"error": {"code": "not_found", "message": "Not found."}},
            status=status.HTTP_404_NOT_FOUND,
        )
    response = drf_exception_handler(exc, context)
    if response is not None:
        data = response.data
        if isinstance(data, dict) and "error" in data:
            return response
        message = str(data) if data else "Bad request."
        code = "bad_request"
        if response.status_code == status.HTTP_404_NOT_FOUND:
            code = "not_found"
        elif response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_405_METHOD_NOT_ALLOWED):
            code = "bad_request"
        response.data = {"error": {"code": code, "message": message}}
    return response


class DocumentViewSet(viewsets.ViewSet):
    parser_classes = [MultiPartParser]
    registry = None

    def _get_or_404(self, pk: str) -> Document:
        doc = get_document(pk)
        if doc is None:
            raise ContractError("not_found", "Document not found.", 404)
        return doc

    def list(self, request):
        status_filter = request.query_params.get("status")
        qs = list_documents(status=status_filter)
        page = request.query_params.get("page", "1")
        page_size = getattr(settings, "REST_FRAMEWORK", {}).get("PAGE_SIZE", 20)
        try:
            page_num = max(1, int(page))
        except ValueError:
            page_num = 1
        total = qs.count()
        start = (page_num - 1) * page_size
        end = start + page_size
        results = list(qs[start:end])
        serializer = DocumentSerializer(results, many=True)
        has_next = end < total
        has_prev = page_num > 1
        next_url = f"?page={page_num + 1}" if has_next else None
        prev_url = f"?page={page_num - 1}" if has_prev else None
        return Response(
            {
                "count": total,
                "next": next_url,
                "previous": prev_url,
                "results": serializer.data,
            }
        )

    def create(self, request):
        upload = request.FILES.get("file")
        if upload is None:
            raise ContractError("bad_request", "No file field named 'file'.", 400)

        temp = tempfile.NamedTemporaryFile(delete=False)
        sha = hashlib.sha256()
        size = 0
        try:
            for chunk in upload.chunks():
                size += len(chunk)
                if size > settings.MAX_UPLOAD_BYTES:
                    raise ContractError(
                        "too_large",
                        f"File exceeds the {settings.MAX_UPLOAD_BYTES}-byte limit.",
                        413,
                    )
                sha.update(chunk)
                temp.write(chunk)
            temp.flush()
        finally:
            temp.close()

        sha256 = sha.hexdigest()
        existing = Document.objects.filter(sha256=sha256).first()
        if existing is not None:
            return Response(
                {"document": DocumentSerializer(existing).data, "duplicate": True},
                status=status.HTTP_200_OK,
            )

        try:
            probe = build_probe(temp.name, upload.name)
        except EmptyDocumentError as exc:
            raise ContractError("bad_request", exc.message, 400) from exc

        registry = self.registry or default_registry()
        if probe.kind not in registry.supported_kinds():
            raise ContractError(
                "unsupported_type",
                f"Unsupported file type (kind={probe.kind!r}).",
                415,
            )

        with open(temp.name, "rb") as fh:
            doc = Document(
                filename=upload.name,
                mime=upload.content_type or "",
                size=size,
                sha256=sha256,
                warnings=probe.warnings,
            )
            doc.file.save(upload.name, File(fh), save=False)
            with transaction.atomic():
                doc.save()
                Job.objects.create(document=doc)

        return Response(
            {"document": DocumentSerializer(doc).data, "duplicate": False},
            status=status.HTTP_202_ACCEPTED,
        )

    def retrieve(self, request, pk=None):
        doc = self._get_or_404(pk)
        return Response(DocumentSerializer(doc).data)

    def destroy(self, request, pk=None):
        doc = self._get_or_404(pk)
        if doc.file:
            doc.file.delete(save=False)
        doc.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def config_view(request):
    registry = default_registry()
    return Response(
        {
            "max_upload_bytes": settings.MAX_UPLOAD_BYTES,
            "supported": registry.describe(),
        }
    )


class _IgnoreFormatNegotiation(DefaultContentNegotiation):
    """content_view uses ``?format=json|markdown|text|html|csv`` for its OWN
    purposes; prevent DRF from treating that query param as a renderer hint
    (which would raise Http404 for unknown formats)."""

    def select_renderer(self, request, renderers, format_suffix):
        return (renderers[0], renderers[0].media_type)


CONTENT_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "text": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}
CONTENT_EXTENSIONS = {"markdown": "md", "text": "txt", "html": "html", "csv": "csv", "json": "json"}
_TRUTHY = {"1", "true", "yes", "on"}


def content_view(request, pk):
    from pathlib import Path

    from ..models import Document

    try:
        doc = Document.objects.get(pk=pk)
    except (Document.DoesNotExist, ValueError):
        raise ContractError("not_found", "Document not found.", 404)

    if doc.status != "done":
        raise ContractError(
            "not_ready",
            f"Document is not ready (status={doc.status}).",
            409,
        )

    fmt = request.query_params.get("format", "json")
    if fmt not in CONTENT_FORMATS:
        raise ContractError(
            "bad_request",
            f"format must be one of: {', '.join(CONTENT_FORMATS)}.",
            400,
        )

    page_param = request.query_params.get("page")
    page = None
    if page_param is not None:
        try:
            page = int(page_param)
        except ValueError:
            raise ContractError("bad_request", "page must be an integer.", 400)
        if doc.page_count is None:
            raise ContractError("bad_request", "This document has no pages.", 400)

    if fmt == "json":
        blocks = list(doc.blocks.all())
        if page is not None:
            blocks = [b for b in blocks if b.page == page]
        payload = {
            "document_id": str(doc.id),
            "page_count": doc.page_count,
            "blocks": BlockSerializer(blocks, many=True).data,
        }
        response = Response(payload)
    else:
        from django.http import HttpResponse

        content = get_content(doc, fmt, page=page)
        response = HttpResponse(content, content_type=CONTENT_TYPES[fmt])

    if request.query_params.get("download", "").lower() in _TRUTHY:
        ext = CONTENT_EXTENSIONS[fmt]
        base = Path(doc.filename).stem or "document"
        response["Content-Disposition"] = f'attachment; filename="{base}.{ext}"'

    return response


content_view.content_negotiation_class = _IgnoreFormatNegotiation
content_view.renderer_classes = [JSONRenderer]
content_view = api_view(["GET"])(content_view)


@api_view(["GET"])
def download_view(request, pk):
    try:
        doc = Document.objects.get(pk=pk)
    except (Document.DoesNotExist, ValueError):
        raise ContractError("not_found", "Document not found.", 404)
    if not doc.file:
        raise ContractError("not_found", "File is missing.", 404)
    from django.http import FileResponse

    return FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.filename)


@api_view(["GET"])
def search_view(request):
    query = request.query_params.get("q", "")
    if len(query) < 2:
        raise ContractError(
            "bad_request", "q must be at least 2 characters.", 400
        )
    try:
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        limit = 20
    results = search_blocks(query, limit=limit)
    return Response(
        {
            "query": query,
            "count": len(results),
            "results": [
                {
                    "document_id": str(r.document_id),
                    "filename": r.document.filename,
                    "block_id": r.id,
                    "idx": r.idx,
                    "page": r.page,
                    "type": r.type,
                    "headline": r.headline,
                    "rank": float(r.rank),
                }
                for r in results
            ],
        }
    )


@api_view(["GET"])
def agent_tools_view(request):
    from ..agent_tools import TOOLS

    return Response(TOOLS)


@api_view(["POST"])
def agent_tools_call_view(request):
    from .. import agent_tools

    name = request.data.get("name")
    arguments = request.data.get("arguments", {})
    if not isinstance(name, str) or not name:
        raise ContractError("bad_request", "name is required.", 400)
    result = agent_tools.dispatch(name, arguments)
    return Response(result)