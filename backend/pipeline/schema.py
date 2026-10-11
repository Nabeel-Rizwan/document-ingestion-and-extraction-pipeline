"""Normalised data structures for the extraction pipeline.

Pure Python; no Django imports. These frozen dataclasses flow through the
pipeline from probing, through planning, to the final extraction result.
"""

from __future__ import annotations

# `dataclass`/`field` declare concise value objects; `field` allows mutable defaults.
from dataclasses import dataclass, field
# `Any` types metadata values; `Optional` marks fields that may be absent.
from typing import Any, Optional


# Immutable value object for a single extracted content unit.
@dataclass(frozen=True)
class Block:
    """A single extracted unit of content."""

    # Block category: "heading", "list_item", "table", or default paragraph-like.
    type: str
    # The extracted text content of this block.
    text: str
    # Source page number (None for formats without pages).
    page: Optional[int] = None
    # Extractor-specific extras (level, rows, confidence, method, ...).
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        # Serialize to the wire shape; id/idx are filled in later by the Django layer.
        return {
            "id": None,
            "idx": None,
            "type": self.type,
            "text": self.text,
            "page": self.page,
            "metadata": self.metadata,
        }


# Immutable analysis of a file produced before extraction begins.
@dataclass(frozen=True)
class ExtractionPlan:
    """The result of cheap, pre-extraction analysis used for routing.

    ``units`` is the number of fine-grained work items the extractor expects
    (e.g. PDF pages). ``strategies`` lists the per-unit strategies that will be
    applied (e.g. "text"/"ocr"). The plan doubles as a human-readable status
    line reported to the user during the detecting stage.
    """

    # Name of the extractor that produced this plan.
    extractor: str
    # Number of fine-grained work units (e.g. pages) the extractor expects.
    units: int
    # Per-unit strategies that will be applied (e.g. "text" / "ocr").
    strategies: list[str]
    # Human-readable status line shown during the detecting stage.
    summary: str
    # Non-fatal issues found during planning.
    warnings: list[str] = field(default_factory=list)


# Immutable bundle of everything an extractor produced for one file.
@dataclass(frozen=True)
class ExtractionResult:
    """Everything produced by running an extractor."""

    # The ordered content blocks extracted from the source file.
    blocks: list[Block]
    # How extraction was performed (e.g. "pdf-text", "pdf-ocr", "docx").
    method: str
    # Total pages detected in the source (None when not applicable).
    page_count: Optional[int] = None
    # Non-fatal issues surfaced during extraction.
    warnings: list[str] = field(default_factory=list)
    # Overall confidence for extracted text (0..1, None when unknown).
    confidence: Optional[float] = None