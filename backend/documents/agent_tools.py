"""Agent tool interface: OpenAI-style function schemas and dispatch.

The same retrieval code (documents.services) backs the REST API and these
tools. Bad arguments return a structured ``{"error": ...}`` instead of raising.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from .models import Document
from .services import get_content, get_document, list_documents, search_blocks


def _doc_to_dict(doc: Document) -> dict:
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "status": doc.status,
        "method": doc.method,
        "page_count": doc.page_count,
        "block_count": doc.block_count,
    }


def _search_documents(query: str, limit: int = 20) -> dict:
    if not query or len(query) < 2:
        return {"error": "query must be at least 2 characters"}
    results = search_blocks(query, limit=limit)
    return {
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


def _list_documents(status: str | None = None) -> dict:
    docs = list(list_documents(status=status))
    return {"count": len(docs), "results": [_doc_to_dict(d) for d in docs]}


def _get_document(document_id: str, format: str = "json") -> dict:
    doc = get_document(document_id)
    if doc is None:
        return {"error": "document not found"}
    if format == "json":
        return _doc_to_dict(doc)
    if doc.status != "done":
        return {"error": "document is not ready", "status": doc.status}
    if format in ("markdown", "text"):
        return {"document_id": str(doc.id), "format": format, "content": get_content(doc, format)}
    return {"error": "unsupported format"}


def _get_document_page(document_id: str, page: int, format: str = "json") -> dict:
    doc = get_document(document_id)
    if doc is None:
        return {"error": "document not found"}
    if doc.status != "done":
        return {"error": "document is not ready", "status": doc.status}
    if format == "json":
        blocks = [b for b in doc.blocks.filter(page=page).order_by("idx")]
        return {
            "document_id": str(doc.id),
            "page": page,
            "blocks": [
                {
                    "id": b.id,
                    "idx": b.idx,
                    "type": b.type,
                    "text": b.text,
                    "page": b.page,
                    "metadata": b.metadata,
                }
                for b in blocks
            ],
        }
    return {
        "document_id": str(doc.id),
        "page": page,
        "content": get_content(doc, format, page=page),
    }


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "Full-text search across extracted document content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "description": "Max results", "default": 20},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_documents",
            "description": "List ingested documents, optionally filtered by status.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["queued", "processing", "done", "failed"],
                        "description": "Filter by status",
                    },
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document",
            "description": "Fetch a document's summary or its full content.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "format": {"type": "string", "enum": ["json", "markdown", "text"], "default": "json"},
                },
                "required": ["document_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_document_page",
            "description": "Fetch a single page of a PDF document.",
            "parameters": {
                "type": "object",
                "properties": {
                    "document_id": {"type": "string"},
                    "page": {"type": "integer"},
                    "format": {"type": "string", "enum": ["json", "markdown", "text"], "default": "json"},
                },
                "required": ["document_id", "page"],
            },
        },
    },
]

_DISPATCH = {
    "search_documents": _search_documents,
    "list_documents": _list_documents,
    "get_document": _get_document,
    "get_document_page": _get_document_page,
}


def dispatch(name: str, arguments: dict):
    """Call a tool by name. Returns a JSON-serialisable result, never raises."""
    if name not in _DISPATCH:
        return {"error": f"unknown tool: {name}"}
    if not isinstance(arguments, dict):
        return {"error": "arguments must be an object"}
    try:
        return _DISPATCH[name](**arguments)
    except TypeError as exc:
        return {"error": f"invalid arguments: {exc}"}
    except ValidationError:
        return {"error": "invalid arguments"}