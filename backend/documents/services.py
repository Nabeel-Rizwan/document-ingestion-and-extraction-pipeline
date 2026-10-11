"""Single retrieval implementation shared by the REST API and agent tools."""

from __future__ import annotations

# Postgres full-text search primitives: highlighting, query parsing, ranking, vectors.
from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
# Raised for invalid values such as a malformed UUID primary key.
from django.core.exceptions import ValidationError
# Q object used to build complex ORM lookups (imported for callers).
from django.db.models import Q

# Renderers that turn blocks into the supported output formats.
from pipeline.renderers import render_csv, render_html, render_markdown, render_text

# Models this service layer queries.
from .models import Block, Document

# Output formats the content endpoint can render (json is handled by the API).
CONTENT_FORMATS = ("json", "markdown", "text", "html", "csv")

# Unicode left/right markers wrapped around matched terms in headlines.
SEARCH_START_SEL = "\u27e6"  # ⟦
SEARCH_STOP_SEL = "\u27e7"  # ⟧


def list_documents(status: str | None = None):
    # Start from all documents; the caller may add ordering/slicing.
    qs = Document.objects.all()
    # Optionally narrow to a single lifecycle status.
    if status:
        qs = qs.filter(status=status)
    return qs


def get_document(document_id: str) -> Document | None:
    try:
        # get() raises DoesNotExist if absent and ValidationError for a bad UUID.
        return Document.objects.get(pk=document_id)
    except (Document.DoesNotExist, ValidationError):
        # Normalise both failure modes to a simple None result.
        return None


def get_content(document: Document, fmt: str, page: int | None = None) -> str:
    """Render a document's blocks in a text format (json is handled by the API)."""
    # Load all blocks for the document.
    blocks = list(document.blocks.all())
    # When a page is specified, keep only that page's blocks.
    if page is not None:
        blocks = [b for b in blocks if b.page == page]
    # Dispatch to the renderer matching the requested format.
    if fmt == "markdown":
        return render_markdown(blocks)
    if fmt == "html":
        return render_html(blocks)
    if fmt == "csv":
        return render_csv(blocks)
    # Plain text is the fallback for "text" and any unrecognised format.
    return render_text(blocks)


def search_blocks(query: str, limit: int = 20):
    """Full-text search across done documents, with highlighted headlines."""
    # English-configured tsvector over the block text.
    vector = SearchVector("text", config="english")
    # websearch syntax lets users type natural web-style queries.
    search_query = SearchQuery(query, search_type="websearch", config="english")
    # Headline annotation wraps matching words in the chosen markers.
    headline = SearchHeadline(
        "text",
        search_query,
        start_sel=SEARCH_START_SEL,
        stop_sel=SEARCH_STOP_SEL,
        max_words=35,
        min_words=15,
    )
    return (
        # Only search documents that finished processing successfully.
        Block.objects.filter(document__status="done")
        # Keep blocks whose tsvector matches the query.
        .filter(search=search_query)
        # Compute a relevance score for ordering.
        .annotate(rank=SearchRank(vector, search_query))
        # Attach the highlighted excerpt for display.
        .annotate(headline=headline)
        # Avoid an extra query when accessing block.document.filename.
        .select_related("document")
        # Highest-ranked matches first, capped at the limit.
        .order_by("-rank")[:limit]
    )


def document_block_for_page(document: Document, page: int) -> list[Block]:
    # Return this page's blocks in reading order as a concrete list.
    return list(document.blocks.filter(page=page).order_by("idx"))