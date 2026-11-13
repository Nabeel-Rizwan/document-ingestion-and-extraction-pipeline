"""Extractor registry.

The registry is the single source of truth for which formats the backend
supports. Upload validation (Django) and the frontend's accepted-file list both
derive from :meth:`ExtractorRegistry.describe` via ``GET /api/config/``, so a
new format requires only one new registered extractor.
"""

from __future__ import annotations

# Raised when no registered extractor can handle the probed file.
from .errors import UnsupportedFormatError
# The Extractor base/protocol every registered extractor must satisfy.
from .extractors.base import Extractor
# FileProbe carries the sniffed kind/extensions used for selection.
from .probe import FileProbe
# Optional OCR client forwarded to extractors that support OCR.
from .ocr.base import OcrClient


# Holds every known extractor and answers "which extractor handles this probe?".
class ExtractorRegistry:
    def __init__(self) -> None:
        # Ordered list of registered extractors; order defines selection priority.
        self._extractors: list[Extractor] = []

    def register(self, extractor: Extractor) -> None:
        # Guard: require the Extractor protocol's `name` attribute up front.
        if not hasattr(extractor, "name"):
            raise TypeError("extractor must satisfy the Extractor protocol")
        # Add the extractor to the end of the candidate list.
        self._extractors.append(extractor)

    def select(self, probe: FileProbe) -> Extractor:
        # Walk candidates in registration order and take the first that matches.
        for extractor in self._extractors:
            if extractor.can_handle(probe):
                return extractor
        # No extractor claimed the probe; classify as a permanent unsupported error.
        raise UnsupportedFormatError(
            f"Unsupported file type (kind={probe.kind!r}, extension={probe.declared_ext!r}).",
        )

    def describe(self) -> list[dict[str, object]]:
        # `seen` deduplicates entries by the extension kinds they cover.
        seen: dict[str, dict[str, object]] = {}
        for extractor in self._extractors:
            # Compose the public description for this extractor.
            entry = {
                "kind": extractor.name,
                "extensions": list(extractor.extensions),
                "mime_types": list(extractor.mime_types),
            }
            # Map every kind this extractor handles to the same description entry.
            for kind in extractor.kinds:
                # setdefault keeps the FIRST entry for each kind (registration order).
                seen.setdefault(kind, entry)
        # Return one description per distinct kind, in first-seen order.
        return list(seen.values())

    def supported_kinds(self) -> frozenset[str]:
        # Accumulate every kind across all registered extractors.
        kinds: set[str] = set()
        for extractor in self._extractors:
            kinds.update(extractor.kinds)
        # Immutable set so callers cannot corrupt the registry's support list.
        return frozenset(kinds)


# Build the registry pre-wired with the built-in extractors.
def default_registry(ocr: OcrClient | None = None) -> ExtractorRegistry:
    """Build the registry with the built-in extractors wired up."""
    # Imports are deferred to avoid loading extractors (and OCR deps) at import time.
    from .extractors.pdf import PdfExtractor
    from .extractors.docx import DocxExtractor
    from .extractors.txt import TxtExtractor

    registry = ExtractorRegistry()
    # PDF extractor may receive the shared OCR client for scanned pages.
    registry.register(PdfExtractor(ocr=ocr))
    # DOCX extractor uses the same client to OCR embedded images.
    registry.register(DocxExtractor(ocr=ocr))
    # Plain-text extractor needs no OCR; routed by .txt extension.
    registry.register(TxtExtractor())
    return registry