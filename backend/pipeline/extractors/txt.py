"""Plain-text extractor.

Each non-empty line becomes a paragraph block (page=None, like DOCX).
Plain text has no magic bytes, so routing relies on the declared ``.txt``
extension (see ``can_handle``). Decoding is strict UTF-8; undecodable files
are reported as corrupt (permanent) rather than retried.
"""

# Defer evaluation of annotations (PEP 563).
from __future__ import annotations

# CorruptDocumentError marks undecodable files as permanent failures.
from ..errors import CorruptDocumentError
# ProgressReporter callback + band_progress maps into the extracting band.
from ..progress import ProgressReporter, band_progress
# Block is one extracted unit; ExtractionPlan/Result are plan/final objects.
from ..schema import Block, ExtractionPlan, ExtractionResult
# Shared helper that describes an extractor's capabilities.
from .base import describe_extractor


class TxtExtractor:
    # Identifier used in plans and results.
    name = "txt"
    # Logical document kind this extractor claims.
    kinds = frozenset({"txt"})
    # File extensions handled.
    extensions = (".txt",)
    # MIME type served.
    mime_types = ("text/plain",)

    # Accepts .txt files: plain text has no magic bytes so probe.kind is
    # None; fall back to the declared extension. Also accepts kind == "txt"
    # for forward-compatibility if probing ever sniffs text.
    def can_handle(self, probe) -> bool:
        return probe.kind == "txt" or (probe.kind is None and probe.declared_ext == ".txt")

    # Returns the serialisable capability description for this extractor.
    def describe(self) -> dict[str, object]:
        return describe_extractor(self)

    # Plain text is a single unit; no per-page routing needed.
    def plan(self, probe) -> ExtractionPlan:
        return ExtractionPlan(
            extractor=self.name,
            units=1,
            strategies=["text"],
            summary="TXT: plain text",
        )

    def extract(
        self,
        probe,
        plan: ExtractionPlan,
        progress: ProgressReporter,
    ) -> ExtractionResult:
        # Signal the start of the reading phase.
        progress.progress(band_progress("extracting", 0.0), "Reading plain text")
        try:
            # Strict UTF-8 so binary files misnamed .txt fail loudly.
            text = probe.path.read_text(encoding="utf-8")
        except UnicodeDecodeError as exc:
            raise CorruptDocumentError(f"Could not decode TXT as UTF-8: {exc}") from exc
        except OSError as exc:
            raise CorruptDocumentError(f"Could not read TXT: {exc}") from exc

        # One paragraph block per non-empty line; blank lines only separate.
        blocks: list[Block] = []
        warnings: list[str] = []
        lines = text.splitlines()
        total = len(lines)
        for i, line in enumerate(lines):
            stripped = line.strip()
            if not stripped:
                continue
            blocks.append(Block(type="paragraph", text=stripped, metadata={}))
            # Report incremental progress across lines (cheap, bounded).
            if total:
                progress.progress(
                    band_progress("extracting", (i + 1) / total),
                    "Reading plain text",
                )

        if not blocks:
            warnings.append("File contains no extractable text.")

        # Plain text has no pagination in our model, so page_count is null.
        return ExtractionResult(
            blocks=blocks,
            method="txt",
            page_count=None,
            warnings=warnings,
            confidence=None,
        )
