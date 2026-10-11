"""Extractor protocol and base helpers.

An :class:`Extractor` knows which files it can handle, can cheaply produce an
:class:`ExtractionPlan` (making finer routing decisions, e.g. per-page PDF
classification), and performs the actual extraction.
"""

# Enables PEP 563 semantics so annotations are stored as strings and forward
# references (e.g. the protocol referring to itself) are not evaluated at runtime.
from __future__ import annotations

# Protocol is the typing construct used to define a structural (duck-typed) interface.
from typing import Protocol

# ExtractionPlan/Result are the per-file plan and final output value objects.
from ..schema import ExtractionPlan, ExtractionResult
# FileProbe carries cheap metadata (path, kind, sniffed type) about the input file.
from ..probe import FileProbe
# ProgressReporter is the callback interface used to report incremental progress.
from ..progress import ProgressReporter


class Extractor(Protocol):
    """Protocol every extractor must satisfy."""

    # Human-readable identifier of the extractor (e.g. "pdf", "docx").
    name: str
    # Set of logical document kinds this extractor supports (e.g. {"pdf"}).
    kinds: frozenset[str]
    # File extensions this extractor claims (e.g. (".pdf",)).
    extensions: tuple[str, ...]
    # MIME types this extractor claims.
    mime_types: tuple[str, ...]

    # Decides whether this extractor is able to process the probed file.
    def can_handle(self, probe: FileProbe) -> bool: ...

    # Produces a cheap extraction plan (e.g. per-page text/OCR routing) before work begins.
    def plan(self, probe: FileProbe) -> ExtractionPlan: ...

    # Performs the actual extraction, reporting progress as it goes.
    def extract(
        self,
        probe: FileProbe,
        plan: ExtractionPlan,
        progress: ProgressReporter,
    ) -> ExtractionResult: ...


# Builds a JSON-serialisable description of an extractor's kind, extensions and MIME types.
def describe_extractor(extractor: Extractor) -> dict[str, object]:
    return {
        # Collapse a single-element kind set to that string; otherwise emit the sorted list.
        "kind": sorted(extractor.kinds)[0] if len(extractor.kinds) == 1 else sorted(extractor.kinds),
        # Materialise the tuples as lists for JSON friendliness.
        "extensions": list(extractor.extensions),
        "mime_types": list(extractor.mime_types),
    }