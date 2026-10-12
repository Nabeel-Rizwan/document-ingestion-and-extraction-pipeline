"""End-to-end PDF extraction tests: strategy routing, methods, OCR usage.

What it does:
    Verifies per-page text/OCR planning, that only scanned pages hit OCR,
    method labels (pdf_text/pdf_ocr/pdf_mixed), block metadata/confidence,
    error mapping, monotonic progress, and heading/list structure detection.

How it works:
    - ``FakeOcrClient`` records which pages were OCR'd and returns canned
      text + confidence, so tests prove routing without real Tesseract.
    - ``_plan_for`` / ``_extract`` are shortcuts: build_probe -> plan ->
      extract with a RecordingProgressReporter.
    - ``run_pipeline`` tests exercise the full registry+router+reporter path.
"""

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
        # What: in-memory OCR double. How: stores called page numbers + fixed
        #   confidence; recognize() returns a _FakeResult with canned text.
        self.calls: list[int] = []
        self.confidence = 0.92

    def recognize(self, image: Image.Image, *, page: int):
        # What: fake OCR for one page. How: logs the page number, returns a
        #   result object carrying "[OCR] page content <conf>" + confidence.
        self.calls.append(page)
        return _FakeResult(self.confidence)


class _FakeResult:
    def __init__(self, confidence):
        # What: minimal OCR result shape. How: stores text + confidence attrs
        #   mirroring the real client interface.
        self.text = f"[OCR] page content {confidence}"
        self.confidence = confidence


def _plan_for(path, filename, ocr=None):
    # What: shortcut returning just the ExtractionPlan for a file.
    # How: builds a PdfExtractor (optional OCR override), probes the file,
    #   then calls plan() to get per-page strategies.
    extractor = PdfExtractor(ocr=ocr)
    probe = build_probe(path, filename)
    return extractor.plan(probe)


def test_digital_pdf_all_text(digital_pdf):
    # What: 3-page digital PDF plans all pages as "text".
    # How: calls _plan_for, asserts strategies==["text"]*3, units==3, and
    #   summary mentions "text pages".
    plan = _plan_for(digital_pdf, digital_pdf.name)
    assert plan.strategies == ["text"] * 3
    assert plan.units == 3
    assert "text pages" in plan.summary


def test_scanned_pdf_all_ocr(scanned_pdf):
    # What: 2-page scanned PDF plans all pages as "ocr".
    # How: calls _plan_for, asserts strategies==["ocr"]*2 and summary has
    #   "2 scanned pages".
    plan = _plan_for(scanned_pdf, scanned_pdf.name)
    assert plan.strategies == ["ocr"] * 2
    assert "2 scanned pages" in plan.summary


def test_mixed_pdf_strategies(mixed_pdf):
    # What: hybrid PDF routes first 2 pages text, last page OCR.
    # How: plans the mixed fixture, asserts ["text","text","ocr"] + summary
    #   mentions "1 scanned page".
    plan = _plan_for(mixed_pdf, mixed_pdf.name)
    assert plan.strategies == ["text", "text", "ocr"]
    assert "1 scanned page" in plan.summary


def test_only_scanned_pages_are_ocrd(mixed_pdf):
    # What: extraction OCRs exactly the scanned page (page 3), nothing else.
    # How: extracts with FakeOcrClient, asserts calls==[3], method pdf_mixed,
    #   page_count 3, confidence ~0.92.
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
    # What: all-text extraction labels method pdf_text and skips OCR.
    # How: extracts digital PDF with fake OCR, asserts method + zero calls.
    ocr = FakeOcrClient()
    extractor = PdfExtractor(ocr=ocr)
    probe = build_probe(digital_pdf, digital_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert result.method == "pdf_text"
    assert ocr.calls == []


def test_all_scanned_method(scanned_pdf):
    # What: all-OCR extraction labels method pdf_ocr and OCRs every page.
    # How: extracts scanned PDF, asserts method pdf_ocr + 2 OCR calls.
    ocr = FakeOcrClient()
    extractor = PdfExtractor(ocr=ocr)
    probe = build_probe(scanned_pdf, scanned_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert result.method == "pdf_ocr"
    assert len(ocr.calls) == 2


def test_text_blocks_carry_page_and_method(digital_pdf):
    # What: text blocks carry 1-based page numbers + method=text metadata.
    # How: extracts digital PDF, asserts every block page in {1,2,3} and
    #   metadata method equals "text".
    extractor = PdfExtractor()
    probe = build_probe(digital_pdf, digital_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert all(b.page == 1 or b.page == 2 or b.page == 3 for b in result.blocks)
    assert all(b.metadata["method"] == "text" for b in result.blocks)


def test_ocr_blocks_carry_confidence(scanned_pdf):
    # What: OCR blocks carry method=ocr + the client's confidence score.
    # How: extracts with FakeOcrClient (0.92), asserts all blocks have
    #   method ocr and confidence approx 0.92.
    extractor = PdfExtractor(ocr=FakeOcrClient())
    probe = build_probe(scanned_pdf, scanned_pdf.name)
    plan = extractor.plan(probe)
    result = extractor.extract(probe, plan, RecordingProgressReporter())
    assert all(b.metadata["method"] == "ocr" for b in result.blocks)
    assert all(b.metadata["confidence"] == pytest.approx(0.92) for b in result.blocks)


def test_low_confidence_warning(scanned_pdf):
    # What: sub-threshold OCR confidence emits one warning per page.
    # How: uses an inline LowConf client returning 0.3 (< 0.6 min), extracts,
    #   asserts 2 warnings (one per scanned page) mentioning low confidence.
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
    # What: encrypted PDF raises EncryptedDocumentError at plan time.
    # How: probes the encrypted fixture, asserts plan() raises the error.
    extractor = PdfExtractor()
    probe = build_probe(encrypted_pdf, encrypted_pdf.name)
    with pytest.raises(EncryptedDocumentError):
        extractor.plan(probe)


def test_truncated_pdf_raises(truncated_pdf):
    # What: truncated PDF raises CorruptDocumentError at plan time.
    # How: probes the truncated fixture, asserts plan() raises corrupt error.
    extractor = PdfExtractor()
    probe = build_probe(truncated_pdf, truncated_pdf.name)
    with pytest.raises(CorruptDocumentError):
        extractor.plan(probe)


def test_progress_is_monotonic_and_bounded(mixed_pdf):
    # What: progress fractions stay in [0,1] and never go backwards.
    # How: runs the full pipeline with a recording reporter, collects
    #   progress values (skipping "detecting" stage), asserts bounds +
    #   pairwise monotonicity.
    reporter = RecordingProgressReporter()
    registry = default_registry(ocr=FakeOcrClient())
    run_pipeline(str(mixed_pdf), mixed_pdf.name, reporter, registry=registry)
    fractions = [e.progress for e in reporter.events if e.stage != "detecting"]
    assert all(0.0 <= f <= 1.0 for f in fractions)
    assert all(b >= a for a, b in zip(fractions, fractions[1:]))


def test_pipeline_output_merges_warnings(tmp_path, digital_pdf):
    # What: extension-mismatch warnings from probing survive run_pipeline.
    # How: copies a PDF to weird.txt, runs the pipeline, asserts some result
    #   warning mentions "extension" and probe.kind is still pdf.
    import shutil

    renamed = tmp_path / "weird.txt"
    shutil.copyfile(digital_pdf, renamed)
    reporter = RecordingProgressReporter()
    out = run_pipeline(str(renamed), "weird.txt", reporter, registry=default_registry())
    assert any("extension" in w for w in out.result.warnings)
    assert out.probe.kind == "pdf"


# --- structural typing (title / heading / list / paragraph) ---------------


def _extract(path):
    # What: shortcut returning the full ExtractionResult for a PDF path.
    # How: probes, plans, and extracts with default settings + recording
    #   reporter in one call.
    extractor = PdfExtractor()
    probe = build_probe(path, path.name)
    plan = extractor.plan(probe)
    return extractor.extract(probe, plan, RecordingProgressReporter())


def test_structured_pdf_detects_headings_and_levels(structured_pdf):
    # What: font-size heuristics map title->h1 and Findings->h2.
    # How: extracts structured.pdf, filters heading blocks, asserts first
    #   text is "Quarterly Report" level 1 and "Findings" is level 2.
    result = _extract(structured_pdf)
    headings = [b for b in result.blocks if b.type == "heading"]
    texts = [b.text for b in headings]
    assert texts[0] == "Quarterly Report"
    assert headings[0].metadata["level"] == 1
    findings = next(b for b in headings if b.text == "Findings")
    assert findings.metadata["level"] == 2


def test_structured_pdf_detects_list_items(structured_pdf):
    # What: bullet + numbered lines become list_item blocks, markers stripped.
    # How: extracts, collects list_item texts, asserts both bullets + the
    #   numbered item (without its "1." prefix) are present.
    result = _extract(structured_pdf)
    items = [b.text for b in result.blocks if b.type == "list_item"]
    assert "First bullet point" in items
    assert "Second bullet point" in items
    assert "Numbered item one" in items  # marker is stripped


def test_structured_pdf_groups_paragraphs(structured_pdf):
    # What: adjacent body lines on nearby y-positions merge into paragraphs.
    # How: extracts, collects paragraph texts, asserts the intro paragraph
    #   plus the merged revenue/costs paragraph both appear.
    result = _extract(structured_pdf)
    paragraphs = [b.text for b in result.blocks if b.type == "paragraph"]
    assert "This is the introduction paragraph." in paragraphs
    assert "Revenue grew over the quarter. Costs stayed flat across teams." in paragraphs


def test_digital_pdf_stays_paragraphs(digital_pdf):
    """A uniform-text PDF has no headings, just a paragraph per page."""
    # What: uniform body text yields only paragraph blocks (no false headings).
    # How: extracts the plain digital PDF, asserts the block-type set is
    #   exactly {"paragraph"}.
    result = _extract(digital_pdf)
    assert {b.type for b in result.blocks} == {"paragraph"}
