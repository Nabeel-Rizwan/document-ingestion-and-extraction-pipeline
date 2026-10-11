"""Two-layer routing.

The router picks an :class:`Extractor` from the probe's sniffed kind; the
extractor's :meth:`plan` then makes finer decisions (per-page text/OCR for
PDFs).
"""

from __future__ import annotations

# The Extractor base type; the concrete extractor returned by selection.
from .extractors.base import Extractor
# FileProbe carries the sniffed format information the selector relies on.
from .probe import FileProbe
# The registry maps a probe to the extractor that can handle it.
from .registry import ExtractorRegistry
# ExtractionPlan describes the per-unit strategies decided during planning.
from .schema import ExtractionPlan


# Serialize the two-layer routing decision for this probe.
def route(
    probe: FileProbe,
    registry: ExtractorRegistry,
) -> tuple[Extractor, ExtractionPlan]:
    # Layer 1: pick the extractor whose can_handle() accepts the sniffed kind.
    extractor = registry.select(probe)
    # Layer 2: let the chosen extractor plan finer per-unit work (text vs OCR).
    plan = extractor.plan(probe)
    # Return both so the caller can extract with the plan already in hand.
    return extractor, plan