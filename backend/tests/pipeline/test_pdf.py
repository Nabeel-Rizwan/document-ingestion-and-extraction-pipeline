"""End-to-end PDF extraction tests: strategy routing, methods, OCR usage."""

from __future__ import annotations

import pytest

from PIL import Image

from pipeline.errors import CorruptDocumentError, EncryptedDocumentError
from pipeline.extractors.pdf import PdfExtractor
from pipeline.extractors.pdf_classifier import PdfConfig
from pipeline.probe import build_probe
from pipeline.progress import RecordingProgressReporter
from pipeline.registry import default_registry
from pipeline.service import run_pipeline


class FakeOcrClient:
    """Records every call so we can prove only scanned pages are OCR'd."""

    def __init__(self) -> None:
        self.calls: list[int] = []
        self.confidence = 0.92

    def recognize(self, image: Image.Image, *, page: int):
        self.calls.append(page)
        return _FakeResult(self.confidence)


class _FakeResult:
    def __init__(self, confidence):
        self.text = f"[OCR] page content {confidence}"
        self.confidence = confidence


def _plan_for(path, filename, ocr=None):
    extractor = PdfExtractor(ocr=ocr)
    probe = build_probe(path, filename)
    return extractor.plan(probe)


def test_digital_pdf_all_text(digital_pdf):
    plan = _plan_for(digital_pdf, digital_pdf.name)
    assert plan.strategies == ["text"] * 3
    assert plan.units == 3
    assert "text pages" in plan.summary


def test_scanned_pdf_all_ocr(scanned_pdf):
    plan = _plan_for(scanned_pdf, scanned_pdf.name)
    assert plan.strategies == ["ocr"] * 2
    assert "2 scanned pages" in plan.summary


def test_mixed_pdf_strategies(mixed_pdf):
    plan = _plan_for(mixed_pdf, mixed_pdf.name)
    assert plan.strategies == ["text", "text", "ocr"]
    assert "1 scanned page" in plan.summary


def test_only_scanned_pages_are_ocrd(mixed_pdf):
    ocr = FakeOcrClient()
    extractor = PdfExtractor(ocr=ocr)
    probe = build_probe(mixed_pdf, mixed_pdf.name)
    plan = extractor.plan(probe)
    reporter = RecordingProgressReporter()
    result = extractor.extract(probe, plan, reporter)
    assert ocr.calls == [3]  # only the single scanned page
    assert result.method == "pdf_mixed"
    assert result.page_count == 3
    assert result.confidence == pytest.approx(0.92)


def test_all_digital_method(digital_pdf):
    ocr = FakeOcrClient()
    extractor = PdfExtractor(ocr=ocr)
    probe = build_probe(digital_pdf, digital_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert result.method == "pdf_text"
    assert ocr.calls == []


def test_all_scanned_method(scanned_pdf):
    ocr = FakeOcrClient()
    extractor = PdfExtractor(ocr=ocr)
    probe = build_probe(scanned_pdf, scanned_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert result.method == "pdf_ocr"
    assert len(ocr.calls) == 2


def test_text_blocks_carry_page_and_method(digital_pdf):
    extractor = PdfExtractor()
    probe = build_probe(digital_pdf, digital_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert all(b.page == 1 or b.page == 2 or b.page == 3 for b in result.blocks)
    assert all(b.metadata["method"] == "text" for b in result.blocks)


def test_ocr_blocks_carry_confidence(scanned_pdf):
    extractor = PdfExtractor(ocr=FakeOcrClient())
    probe = build_probe(scanned_pdf, scanned_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert all(b.metadata["method"] == "ocr" for b in result.blocks)
    assert all(b.metadata["confidence"] == pytest.approx(0.92) for b in result.blocks)


def test_low_confidence_warning(scanned_pdf):
    class LowConf:
        def recognize(self, image, *, page):
            return _FakeResult(0.3)  # below ocr_min_confidence=0.6

    extractor = PdfExtractor(ocr=LowConf())
    probe = build_probe(scanned_pdf, scanned_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert len(result.warnings) == 2
    assert any("low confidence" in w for w in result.warnings)


def test_encrypted_pdf_raises(encrypted_pdf):
    extractor = PdfExtractor()
    probe = build_probe(encrypted_pdf, encrypted_pdf.name)
    with pytest.raises(EncryptedDocumentError):
        extractor.plan(probe)


def test_truncated_pdf_raises(truncated_pdf):
    extractor = PdfExtractor()
    probe = build_probe(truncated_pdf, truncated_pdf.name)
    with pytest.raises(CorruptDocumentError):
        extractor.plan(probe)


def test_progress_is_monotonic_and_bounded(mixed_pdf):
    reporter = RecordingProgressReporter()
    registry = default_registry(ocr=FakeOcrClient())
    run_pipeline(str(mixed_pdf), mixed_pdf.name, reporter, registry=registry)
    fractions = [e.progress for e in reporter.events if e.stage != "detecting"]
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert all(b >= a for a, b in zip(fractions, fractions[1:]))


def test_pipeline_output_merges_warnings(tmp_path, digital_pdf):
    import shutil

    renamed = tmp_path / "weird.txt"
    shutil.copyfile(digital_pdf, renamed)
    reporter = RecordingProgressReporter()
    out = run_pipeline(str(renamed), "weird.txt", reporter, registry=default_registry())
    assert any("extension" in w for w in out.result.warnings)
    assert out.probe.kind == "pdf"