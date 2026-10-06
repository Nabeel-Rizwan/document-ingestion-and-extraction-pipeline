"""OCR engine selection tests."""

from __future__ import annotations

import shutil

import pytest

from documents.processing import build_ocr_client
from pipeline.ocr.mock import MockOcrClient


def test_mock_engine_selected(settings):
    settings.OCR_ENGINE = "mock"
    assert isinstance(build_ocr_client(), MockOcrClient)


def test_tesseract_engine_selected_when_available(settings):
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract binary not installed")
    from pipeline.ocr.tesseract import TesseractOcrClient

    settings.OCR_ENGINE = "tesseract"
    assert isinstance(build_ocr_client(), TesseractOcrClient)


def test_falls_back_to_mock_without_tesseract(settings, monkeypatch):
    import documents.processing as processing

    settings.OCR_ENGINE = "tesseract"
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert isinstance(build_ocr_client(), MockOcrClient)
