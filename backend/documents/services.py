"""Single retrieval implementation shared by the REST API and agent tools."""

from __future__ import annotations

from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.core.exceptions import ValidationError
from django.db.models import Q

from pipeline.renderers import render_csv, render_html, render_markdown, render_text

from .models import Block, Document

CONTENT_FORMATS = ("json", "markdown", "text", "html", "csv")

SEARCH_START_SEL = "\u27e6"  # ⟦
SEARCH_STOP_SEL = "\u27e7"  # ⟧


def list_documents(status: str | None = None):
    qs = Document.objects.all()
    if status:
        qs = qs.filter(status=status)
    return qs


def get_document(document_id: str) -> Document | None:
    try:
        return Document.objects.get(pk=document_id)
    except (Document.DoesNotExist, ValidationError):
        return None


def get_content(document: Document, fmt: str, page: int | None = None) -> str:
    """Render a document's blocks in a text format (json is handled by the API)."""
    blocks = list(document.blocks.all())
    if page is not None:
        blocks = [b for b in blocks if b.page == page]
    if fmt == "markdown":
        return render_markdown(blocks)
    if fmt == "html":
        return render_html(blocks)
    if fmt == "csv":
        return render_csv(blocks)
    return render_text(blocks)


def search_blocks(query: str, limit: int = 20):
    """Full-text search across done documents, with highlighted headlines."""
    vector = SearchVector("text", config="english")
    search_query = SearchQuery(query, search_type="websearch", config="english")
    headline = SearchHeadline(
        "text",
        search_query,
        start_sel=SEARCH_START_SEL,
        stop_sel=SEARCH_STOP_SEL,
        max_words=35,
        min_words=15,
    )
    return (
        Block.objects.filter(document__status="done")
        .filter(search=search_query)
        .annotate(rank=SearchRank(vector, search_query))
        .annotate(headline=headline)
        .select_related("document")
        .order_by("-rank")[:limit]
    )


def document_block_for_page(document: Document, page: int) -> list[Block]:
    return list(document.blocks.filter(page=page).order_by("idx"))