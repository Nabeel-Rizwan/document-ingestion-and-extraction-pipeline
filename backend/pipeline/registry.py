"""Extractor registry.

The registry is the single source of truth for which formats the backend
supports. Upload validation (Django) and the frontend's accepted-file list both
derive from :meth:`ExtractorRegistry.describe` via ``GET /api/config/``, so a
new format requires only one new registered extractor.
"""

from __future__ import annotations

from .errors import UnsupportedFormatError
from .extractors.base import Extractor
from .probe import FileProbe
from .ocr.base import OcrClient


class ExtractorRegistry:
    def __init__(self) -> None:
        self._extractors: list[Extractor] = []

    def register(self, extractor: Extractor) -> None:
        if not hasattr(extractor, "name"):
            raise TypeError("extractor must satisfy the Extractor protocol")
        self._extractors.append(extractor)

    def select(self, probe: FileProbe) -> Extractor:
        for extractor in self._extractors:
            if extractor.can_handle(probe):
                return extractor
        raise UnsupportedFormatError(
            f"Unsupported file type (kind={probe.kind!r}, extension={probe.declared_ext!r}).",
        )

    def describe(self) -> list[dict[str, object]]:
        seen: dict[str, dict[str, object]] = {}
        for extractor in self._extractors:
            entry = {
                "kind": extractor.name,
                "extensions": list(extractor.extensions),
                "mime_types": list(extractor.mime_types),
            }
            for kind in extractor.kinds:
                seen.setdefault(kind, entry)
        return list(seen.values())

    def supported_kinds(self) -> frozenset[str]:
        kinds: set[str] = set()
        for extractor in self._extractors:
            kinds.update(extractor.kinds)
        return frozenset(kinds)


def default_registry(ocr: OcrClient | None = None) -> ExtractorRegistry:
    """Build the registry with the built-in extractors wired up."""
    from .extractors.pdf import PdfExtractor
    from .extractors.docx import DocxExtractor

    registry = ExtractorRegistry()
    registry.register(PdfExtractor(ocr=ocr))
    registry.register(DocxExtractor())
    return registry