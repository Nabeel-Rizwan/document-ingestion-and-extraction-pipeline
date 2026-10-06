"""Normalised data structures for the extraction pipeline.

Pure Python; no Django imports. These frozen dataclasses flow through the
pipeline from probing, through planning, to the final extraction result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass(frozen=True)
class Block:
    """A single extracted unit of content."""

    type: str
    text: str
    page: Optional[int] = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": None,
            "idx": None,
            "type": self.type,
            "text": self.text,
            "page": self.page,
            "metadata": self.metadata,
        }


@dataclass(frozen=True)
class ExtractionPlan:
    """The result of cheap, pre-extraction analysis used for routing.

    ``units`` is the number of fine-grained work items the extractor expects
    (e.g. PDF pages). ``strategies`` lists the per-unit strategies that will be
    applied (e.g. "text"/"ocr"). The plan doubles as a human-readable status
    line reported to the user during the detecting stage.
    """

    extractor: str
    units: int
    strategies: list[str]
    summary: str
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ExtractionResult:
    """Everything produced by running an extractor."""

    blocks: list[Block]
    method: str
    page_count: Optional[int] = None
    warnings: list[str] = field(default_factory=list)
    confidence: Optional[float] = None