"""Extractor protocol and base helpers.

An :class:`Extractor` knows which files it can handle, can cheaply produce an
:class:`ExtractionPlan` (making finer routing decisions, e.g. per-page PDF
classification), and performs the actual extraction.
"""

from __future__ import annotations

from typing import Protocol

from ..schema import ExtractionPlan, ExtractionResult
from ..probe import FileProbe
from ..progress import ProgressReporter


class Extractor(Protocol):
    """Protocol every extractor must satisfy."""

    name: str
    kinds: frozenset[str]
    extensions: tuple[str, ...]
    mime_types: tuple[str, ...]

    def can_handle(self, probe: FileProbe) -> bool: ...

    def plan(self, probe: FileProbe) -> ExtractionPlan: ...

    def extract(
        self,
        probe: FileProbe,
        plan: ExtractionPlan,
        progress: ProgressReporter,
    ) -> ExtractionResult: ...


def describe_extractor(extractor: Extractor) -> dict[str, object]:
    return {
        "kind": sorted(extractor.kinds)[0] if len(extractor.kinds) == 1 else sorted(extractor.kinds),
        "extensions": list(extractor.extensions),
        "mime_types": list(extractor.mime_types),
    }