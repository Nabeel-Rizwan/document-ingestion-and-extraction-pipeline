"""REST API views.

All endpoints return the contract's error envelope
``{"error": {"code", "message"}}`` on failure.
"""

# Enable postponed evaluation of annotations (PEP 563).
from __future__ import annotations

# hashlib computes the SHA-256 content hash used for deduplication.
import hashlib
# tempfile buffers streamed uploads to disk before probing/persisting.
import tempfile

# settings exposes project configuration (limits, REST_FRAMEWORK, etc.).
from django.conf import settings
# File wraps a Python file object for saving into a model FileField.
from django.core.files import File
# transaction.atomic() makes document+job creation a single atomic unit.
from django.db import transaction
# Http404 is translated by the exception handler into the contract envelope.
from django.http import Http404
# status provides named HTTP status codes; viewsets is the DRF base class.
from rest_framework import status, viewsets
# api_view decorates function-based views and restricts allowed HTTP methods.
from rest_framework.decorators import api_view
# APIException is the base class for DRF exceptions we subclass.
from rest_framework.exceptions import APIException
# DefaultContentNegotiation is subclassed to neutralize ?format= handling.
from rest_framework.negotiation import DefaultContentNegotiation
# MultiPartParser parses multipart/form-data file uploads.
from rest_framework.parsers import MultiPartParser
# JSONRenderer is forced for content_view to avoid renderer-driven 404s.
from rest_framework.renderers import JSONRenderer
# Response builds the DRF response object.
from rest_framework.response import Response
# DRF's default exception handler, used as a fallback in our custom handler.
from rest_framework.views import exception_handler as drf_exception_handler

# Domain errors and helpers from the processing pipeline.
from pipeline.errors import EmptyDocumentError
from pipeline.probe import build_probe
from pipeline.registry import default_registry

# ORM models and service-layer helpers used by the endpoints.
from ..models import Document, Job
from ..services import CONTENT_FORMATS, get_content, get_document, list_documents, search_blocks
# Serializers that shape the JSON payloads.
from .serializers import BlockSerializer, DocumentSerializer


class ContractError(APIException):
    """Carries the contract's machine code alongside the HTTP status."""

    def __init__(self, code: str, message: str, http_status: int) -> None:
        # Store the machine-readable error code for the envelope.
        self.code = code
        # Override the HTTP status DRF will use for this exception.
        self.status_code = http_status
        # Body follows the documented {"error": {"code", "message"}} shape.
        self.detail = {"error": {"code": code, "message": message}}


def api_exception_handler(exc, context):
    """Translate DRF exceptions into the contract's error envelope."""
    # Our own ContractError already has the exact desired body and status.
    if isinstance(exc, ContractError):
        return Response(exc.detail, status=exc.status_code)
    # Map Django's Http404 to a canonical not_found envelope.
    if isinstance(exc, Http404):
        return Response(
            {"error": {"code": "not_found", "message": "Not found."}},
            status=status.HTTP_404_NOT_FOUND,
        )
    # Otherwise defer to DRF's standard handling to get a base response.
    response = drf_exception_handler(exc, context)
    # Only reshape the response when DRF produced one (unhandled errors stay 500s).
    if response is not None:
        data = response.data
        # If the body already matches the envelope, leave it untouched.
        if isinstance(data, dict) and "error" in data:
            return response
        # Fallback message/code for generic DRF errors.
        message = str(data) if data else "Bad request."
        code = "bad_request"
        # Refine the machine code based on the HTTP status.
        if response.status_code == status.HTTP_404_NOT_FOUND:
            code = "not_found"
        elif response.status_code in (status.HTTP_400_BAD_REQUEST, status.HTTP_405_METHOD_NOT_ALLOWED):
            code = "bad_request"
        # Wrap the original payload text in the contract envelope.
        response.data = {"error": {"code": code, "message": message}}
    return response


class DocumentViewSet(viewsets.ViewSet):
    # Accept multipart uploads for the create action.
    parser_classes = [MultiPartParser]
    # Optional registry override; falls back to default_registry() when None.
    registry = None

    def _get_or_404(self, pk: str) -> Document:
        # Fetch via the service layer, returning None instead of raising.
        doc = get_document(pk)
        # Convert a missing document into the contract's not_found error.
        if doc is None:
            raise ContractError("not_found", "Document not found.", 404)
        return doc

    def list(self, request):
        # Optional ?status= filter applied by the service layer.
        status_filter = request.query_params.get("status")
        # Base queryset of documents (filtered by status when provided).
        qs = list_documents(status=status_filter)
        # Requested page number as a string, defaulting to the first page.
        page = request.query_params.get("page", "1")
        # Page size from DRF settings, defaulting to 20.
        page_size = getattr(settings, "REST_FRAMEWORK", {}).get("PAGE_SIZE", 20)
        try:
            # Coerce page to an int, clamping to a minimum of 1.
            page_num = max(1, int(page))
        except ValueError:
            # Non-numeric page falls back to page 1.
            page_num = 1
        # Total row count for the pagination metadata.
        total = qs.count()
        # Zero-based slice bounds for the requested page.
        start = (page_num - 1) * page_size
        end = start + page_size
        # Materialize only the current page's rows.
        results = list(qs[start:end])
        # Serialize the page's documents.
        serializer = DocumentSerializer(results, many=True)
        # Pagination flags derived from the slice bounds and total.
        has_next = end < total
        has_prev = page_num > 1
        # Relative pagination links (or None) returned to the client.
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
        # Extract the uploaded file from the multipart body.
        upload = request.FILES.get("file")
        # A missing file field is a client error.
        if upload is None:
            raise ContractError("bad_request", "No file field named 'file'.", 400)

        # Named temporary file that persists after close so the pipeline can probe it.
        temp = tempfile.NamedTemporaryFile(delete=False)
        # Incremental SHA-256 hasher for deduplication.
        sha = hashlib.sha256()
        # Running total of received bytes for the size limit check.
        size = 0
        try:
            # Stream the upload in chunks rather than loading it all into memory.
            for chunk in upload.chunks():
                size += len(chunk)
                # Enforce the configured maximum upload size mid-stream.
                if size > settings.MAX_UPLOAD_BYTES:
                    raise ContractError(
                        "too_large",
                        f"File exceeds the {settings.MAX_UPLOAD_BYTES}-byte limit.",
                        413,
                    )
                # Feed the chunk into the hash and write it to the temp file.
                sha.update(chunk)
                temp.write(chunk)
            # Flush buffered data so the file on disk is complete.
            temp.flush()
        finally:
            # Always close the handle, even on error, before further use.
            temp.close()

        # Final hex digest used as the dedup key.
        sha256 = sha.hexdigest()
        # Look for an existing document with identical content.
        existing = Document.objects.filter(sha256=sha256).first()
        # Duplicate upload: return the existing document with a 200 (not a new job).
        if existing is not None:
            return Response(
                {"document": DocumentSerializer(existing).data, "duplicate": True},
                status=status.HTTP_200_OK,
            )

        try:
            # Probe the temp file to determine kind, pages, and warnings.
            probe = build_probe(temp.name, upload.name)
        except EmptyDocumentError as exc:
            # An empty/unreadable file is reported as a bad request.
            raise ContractError("bad_request", exc.message, 400) from exc

        # Use the injected registry or the project default.
        registry = self.registry or default_registry()
        # Reject file kinds the pipeline cannot process.
        if probe.kind not in registry.supported_kinds():
            raise ContractError(
                "unsupported_type",
                f"Unsupported file type (kind={probe.kind!r}).",
                415,
            )

        # Re-open the buffered file to persist it into the model's FileField.
        with open(temp.name, "rb") as fh:
            # Build the Document row from upload metadata and probe results.
            doc = Document(
                filename=upload.name,
                mime=upload.content_type or "",
                size=size,
                sha256=sha256,
                warnings=probe.warnings,
            )
            # Save the file contents without persisting the row yet.
            doc.file.save(upload.name, File(fh), save=False)
            # Create the document and its processing Job atomically.
            with transaction.atomic():
                doc.save()
                Job.objects.create(document=doc)

        # Accepted for async processing: return 202 with the new document.
        return Response(
            {"document": DocumentSerializer(doc).data, "duplicate": False},
            status=status.HTTP_202_ACCEPTED,
        )

    def retrieve(self, request, pk=None):
        # Resolve the document or raise not_found.
        doc = self._get_or_404(pk)
        # Return the serialized document body.
        return Response(DocumentSerializer(doc).data)

    def destroy(self, request, pk=None):
        # Resolve the document or raise not_found.
        doc = self._get_or_404(pk)
        # Remove the stored file from storage without re-saving the row.
        if doc.file:
            doc.file.delete(save=False)
        # Delete the document row itself.
        doc.delete()
        # 204 No Content on successful deletion.
        return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
def config_view(request):
    # Load the default pipeline registry.
    registry = default_registry()
    return Response(
        {
            # Expose the upload size limit for client-side validation.
            "max_upload_bytes": settings.MAX_UPLOAD_BYTES,
            # Describe supported file kinds/formats to the client.
            "supported": registry.describe(),
        }
    )


class _IgnoreFormatNegotiation(DefaultContentNegotiation):
    """content_view uses ``?format=json|markdown|text|html|csv`` for its OWN
    purposes; prevent DRF from treating that query param as a renderer hint
    (which would raise Http404 for unknown formats)."""

    def select_renderer(self, request, renderers, format_suffix):
        # Always use the first (and only) renderer, ignoring the format_suffix.
        return (renderers[0], renderers[0].media_type)


# Mapping of content formats to their response Content-Type headers.
CONTENT_TYPES = {
    "markdown": "text/markdown; charset=utf-8",
    "text": "text/plain; charset=utf-8",
    "html": "text/html; charset=utf-8",
    "csv": "text/csv; charset=utf-8",
}
# Mapping of content formats to the file extension used for downloads.
CONTENT_EXTENSIONS = {"markdown": "md", "text": "txt", "html": "html", "csv": "csv", "json": "json"}
# Query-string values treated as boolean true for the ?download flag.
_TRUTHY = {"1", "true", "yes", "on"}


def content_view(request, pk):
    # Imported locally to keep module import time light.
    from pathlib import Path

    # Local import of the model to avoid a circular import at module load.
    from ..models import Document

    try:
        # Look up the document by UUID primary key.
        doc = Document.objects.get(pk=pk)
    except (Document.DoesNotExist, ValueError):
        # Missing or malformed PK -> not_found envelope.
        raise ContractError("not_found", "Document not found.", 404)

    # Content is only available once processing has completed.
    if doc.status != "done":
        raise ContractError(
            "not_ready",
            f"Document is not ready (status={doc.status}).",
            409,
        )

    # Requested output format, defaulting to JSON.
    fmt = request.query_params.get("format", "json")
    # Reject formats outside the supported set.
    if fmt not in CONTENT_FORMATS:
        raise ContractError(
            "bad_request",
            f"format must be one of: {', '.join(CONTENT_FORMATS)}.",
            400,
        )

    # Optional page filter supplied as a query parameter.
    page_param = request.query_params.get("page")
    page = None
    # Parse/validate the page filter only when provided.
    if page_param is not None:
        try:
            page = int(page_param)
        except ValueError:
            raise ContractError("bad_request", "page must be an integer.", 400)
        # Filtering by page is meaningless for documents without pages.
        if doc.page_count is None:
            raise ContractError("bad_request", "This document has no pages.", 400)

    # JSON format returns structured blocks directly.
    if fmt == "json":
        # Materialize the document's blocks.
        blocks = list(doc.blocks.all())
        # Apply the optional page filter in Python.
        if page is not None:
            blocks = [b for b in blocks if b.page == page]
        # Structured payload matching the contract.
        payload = {
            "document_id": str(doc.id),
            "page_count": doc.page_count,
            "blocks": BlockSerializer(blocks, many=True).data,
        }
        response = Response(payload)
    else:
        # Non-JSON formats are rendered to text by the service layer.
        from django.http import HttpResponse

        # Convert the document to the requested serialized format.
        content = get_content(doc, fmt, page=page)
        # Return raw bytes with the matching Content-Type (bypasses DRF renderers).
        response = HttpResponse(content, content_type=CONTENT_TYPES[fmt])

    # When ?download=true, force a browser download with a derived filename.
    if request.query_params.get("download", "").lower() in _TRUTHY:
        # Choose the file extension for the requested format.
        ext = CONTENT_EXTENSIONS[fmt]
        # Use the original filename stem, falling back to "document".
        base = Path(doc.filename).stem or "document"
        # Attachment disposition prompts a save-as dialog in the browser.
        response["Content-Disposition"] = f'attachment; filename="{base}.{ext}"'

    return response


# Configure the content_view function before wrapping it with @api_view.
content_view.content_negotiation_class = _IgnoreFormatNegotiation
content_view.renderer_classes = [JSONRenderer]
content_view = api_view(["GET"])(content_view)


@api_view(["GET"])
def download_view(request, pk):
    try:
        # Look up the document by UUID primary key.
        doc = Document.objects.get(pk=pk)
    except (Document.DoesNotExist, ValueError):
        # Missing or malformed PK -> not_found envelope.
        raise ContractError("not_found", "Document not found.", 404)
    # The associated file must exist on storage.
    if not doc.file:
        raise ContractError("not_found", "File is missing.", 404)
    # Imported locally to keep the top-level import list focused.
    from django.http import FileResponse

    # Stream the stored file to the client as an attachment.
    return FileResponse(doc.file.open("rb"), as_attachment=True, filename=doc.filename)


@api_view(["GET"])
def search_view(request):
    # Search query text; defaults to empty so the length check fails clearly.
    query = request.query_params.get("q", "")
    # Require at least two characters to search.
    if len(query) < 2:
        raise ContractError(
            "bad_request", "q must be at least 2 characters.", 400
        )
    try:
        # Maximum number of results, defaulting to 20.
        limit = int(request.query_params.get("limit", "20"))
    except ValueError:
        # Non-numeric limit falls back to 20.
        limit = 20
    # Run the full-text search over blocks.
    results = search_blocks(query, limit=limit)
    return Response(
        {
            "query": query,
            # Number of matches returned.
            "count": len(results),
            # Flatten each matching block into a client-friendly shape.
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
    # Imported locally to avoid loading the agent module at startup.
    from ..agent_tools import TOOLS

    # Return the tool catalog directly.
    return Response(TOOLS)


@api_view(["POST"])
def agent_tools_call_view(request):
    # Import the module (not just TOOLS) so dispatch() is reachable.
    from .. import agent_tools

    # Tool name to invoke, from the JSON body.
    name = request.data.get("name")
    # Tool arguments object; defaults to an empty dict.
    arguments = request.data.get("arguments", {})
    # The name must be a non-empty string.
    if not isinstance(name, str) or not name:
        raise ContractError("bad_request", "name is required.", 400)
    # Execute the tool and return its result payload.
    result = agent_tools.dispatch(name, arguments)
    return Response(result)