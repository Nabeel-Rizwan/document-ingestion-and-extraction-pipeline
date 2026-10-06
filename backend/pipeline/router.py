"""Two-layer routing.

The router picks an :class:`Extractor` from the probe's sniffed kind; the
extractor's :meth:`plan` then makes finer decisions (per-page text/OCR for
PDFs).
"""

from __future__ import annotations

from .extractors.base import Extractor
from .probe import FileProbe
from .registry import ExtractorRegistry
from .schema import ExtractionPlan


def route(
    probe: FileProbe,
    registry: ExtractorRegistry,
) -> tuple[Extractor, ExtractionPlan]:
    extractor = registry.select(probe)
    plan = extractor.plan(probe)
    return extractor, plan