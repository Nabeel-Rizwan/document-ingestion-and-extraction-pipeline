"""Pipeline service: ties probing, routing, and extraction together.

Order of operations:
  stage("detecting") -> build_probe -> route -> stage("extracting") -> extract

Probe warnings are merged into the result warnings.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import ExtractionError
from .extractors.base import Extractor
from .ocr.base import OcrClient
from .probe import FileProbe, build_probe
from .progress import ProgressReporter
from .registry import ExtractorRegistry, default_registry
from .router import route
from .schema import ExtractionPlan, ExtractionResult


@dataclass(frozen=True)
class PipelineOutput:
    probe: FileProbe
    plan: ExtractionPlan
    result: ExtractionResult


def run_pipeline(
    path: str,
    filename: str,
    progress: ProgressReporter,
    registry: ExtractorRegistry | None = None,
    ocr: OcrClient | None = None,
) -> PipelineOutput:
    if registry is None:
        registry = default_registry(ocr=ocr)

    progress.stage("detecting", "Sniffing file type")
    probe = build_probe(path, filename)
    extractor, plan = route(probe, registry)
    progress.stage("detecting", plan.summary)

    progress.stage("extracting", "Extracting content")
    result = extractor.extract(probe, plan, progress)

    merged_warnings = list(probe.warnings) + list(result.warnings)
    result = ExtractionResult(
        blocks=result.blocks,
        method=result.method,
        page_count=result.page_count,
        warnings=merged_warnings,
        confidence=result.confidence,
    )
    return PipelineOutput(probe=probe, plan=plan, result=result)