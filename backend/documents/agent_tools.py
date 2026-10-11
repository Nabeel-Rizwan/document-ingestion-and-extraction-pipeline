"""Agent tool interface: OpenAI-style function schemas and dispatch.

The same retrieval code (documents.services) backs the REST API and these
tools. Bad arguments return a structured ``{"error": ...}`` instead of raising.
"""

from __future__ import annotations

# Raised by Django when a field lookup gets an invalid value (e.g. bad UUID).
from django.core.exceptions import ValidationError

# Document model used only for the type hint on _doc_to_dict.
from .models import Document
# Shared retrieval functions reused by the REST API and these tools.
from .services import get_content, get_document, list_documents, search_blocks


def _doc_to_dict(doc: Document) -> dict:
    # Projects a Document into the compact JSON shape returned to agents.
    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "status": doc.status,
        "method": doc.method,
        "page_count": doc.page_count,
        "block_count": doc.block_count,
    }


def _search_documents(query: str, limit: int = 20) -> dict:
    # Reject too-short queries to avoid expensive, low-signal searches.
    if not query or len(query) < 2:
        return {"error": "query must be at least 2 characters"}
    # Delegate to the shared full-text search implementation.
    results = search_blocks(query, limit=limit)
    # Shape the ORM search result rows into plain JSON-serialisable dicts.
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
    # Materialise the queryset so it can be counted and iterated.
    docs = list(list_documents(status=status))
    # Return a count plus each document's compact projection.
    return {"count": len(docs), "results": [_doc_to_dict(d) for d in docs]}


def _get_document(document_id: str, format: str = "json") -> dict:
    # Look up the document; a bad or missing id yields None.
    doc = get_document(document_id)
    if doc is None:
        return {"error": "document not found"}
    # The default json format returns metadata without needing full content.
    if format == "json":
        return _doc_to_dict(doc)
    # Content formats require the extraction pipeline to have finished.
    if doc.status != "done":
        return {"error": "document is not ready", "status": doc.status}
    # Render the full document in the requested text format.
    if format in ("markdown", "text"):
        return {"document_id": str(doc.id), "format": format, "content": get_content(doc, format)}
    return {"error": "unsupported format"}


def _get_document_page(document_id: str, page: int, format: str = "json") -> dict:
    # Look up the document; missing/invalid id returns None.
    doc = get_document(document_id)
    if doc is None:
        return {"error": "document not found"}
    # Page content is only meaningful once extraction has completed.
    if doc.status != "done":
        return {"error": "document is not ready", "status": doc.status}
    # json format returns structured blocks for the requested page.
    if format == "json":
        # Query only this page's blocks, ordered by their in-document position.
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
    # Any other format is rendered text for just this page.
    return {
        "document_id": str(doc.id),
        "page": page,
        "content": get_content(doc, format, page=page),
    }


# OpenAI-style function-calling schemas advertised to the agent/model.
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
                # The model must supply a query; limit is optional.
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
                        # Restricts status to the known lifecycle values.
                        "enum": ["queued", "processing", "done", "failed"],
                        "description": "Filter by status",
                    },
                },
                # No arguments are mandatory.
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
                    # Allowed output encodings; defaults to json.
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

# Maps tool name to the Python callable that implements it.
_DISPATCH = {
    "search_documents": _search_documents,
    "list_documents": _list_documents,
    "get_document": _get_document,
    "get_document_page": _get_document_page,
}


def dispatch(name: str, arguments: dict):
    """Call a tool by name. Returns a JSON-serialisable result, never raises."""
    # Unknown tool names are reported rather than raising.
    if name not in _DISPATCH:
        return {"error": f"unknown tool: {name}"}
    # Arguments must be a mapping so they can be splatted as keyword args.
    if not isinstance(arguments, dict):
        return {"error": "arguments must be an object"}
    try:
        # Call the registered function with the supplied keyword arguments.
        return _DISPATCH[name](**arguments)
    except TypeError as exc:
        # Wrong/missing/extra arguments surface as TypeError.
        return {"error": f"invalid arguments: {exc}"}
    except ValidationError:
        # Django raises this for invalid values (e.g. malformed document_id).
        return {"error": "invalid arguments"}