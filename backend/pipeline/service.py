"""Pipeline service: ties probing, routing, and extraction together.

Order of operations:
  stage("detecting") -> build_probe -> route -> stage("extracting") -> extract

Probe warnings are merged into the result warnings.
"""

from __future__ import annotations

# `dataclass` declares the immutable PipelineOutput bundle.
from dataclasses import dataclass

# Transient vs permanent error distinction is preserved from errors module.
from .errors import ExtractionError
# The Extractor base type returned by routing.
from .extractors.base import Extractor
# Optional OCR client forwarded to the default registry for scanned files.
from .ocr.base import OcrClient
# FileProbe and its factory `build_probe` used in the detecting stage.
from .probe import FileProbe, build_probe
# ProgressReporter protocol; every stage update goes through this interface.
from .progress import ProgressReporter
# Registry plus the default built-in wiring for production use.
from .registry import ExtractorRegistry, default_registry
# Two-layer routing: pick extractor, then produce the plan.
from .router import route
# The plan and result objects carried through and returned to the caller.
from .schema import ExtractionPlan, ExtractionResult


# Immutable bundle of everything produced for one file.
@dataclass(frozen=True)
class PipelineOutput:
    # The sniffing outcome (path, size, kind, extension, warnings).
    probe: FileProbe
    # Routing plan with units/strategies and the human-readable summary.
    plan: ExtractionPlan
    # The final blocks, method, page count, confidence, and merged warnings.
    result: ExtractionResult


# Orchestrate probe -> route -> extract and return the full output bundle.
def run_pipeline(
    path: str,
    filename: str,
    progress: ProgressReporter,
    registry: ExtractorRegistry | None = None,
    ocr: OcrClient | None = None,
) -> PipelineOutput:
    if registry is None:
        # Caller passed no registry, so build the default one (with OCR if given).
        registry = default_registry(ocr=ocr)

    # Begin the detecting stage: sniff the file's real format from its bytes.
    progress.stage("detecting", "Sniffing file type")
    probe = build_probe(path, filename)
    # Select the extractor and have it plan the per-unit work for this probe.
    extractor, plan = route(probe, registry)
    # Report the plan's human-readable summary to complete the detecting stage.
    progress.stage("detecting", plan.summary)

    # Move into the extracting stage and run the extractor with progress updates.
    progress.stage("extracting", "Extracting content")
    result = extractor.extract(probe, plan, progress)

    # Concatenate probe warnings (e.g. extension mismatches) with result warnings.
    merged_warnings = list(probe.warnings) + list(result.warnings)
    # Rebuild the result only to replace warnings with the merged list.
    result = ExtractionResult(
        blocks=result.blocks,
        method=result.method,
        page_count=result.page_count,
        warnings=merged_warnings,
        confidence=result.confidence,
    )
    # Return everything the caller needs: probe, plan, and final result.
    return PipelineOutput(probe=probe, plan=plan, result=result)