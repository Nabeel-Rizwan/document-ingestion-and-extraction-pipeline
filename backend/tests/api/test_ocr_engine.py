"""OCR engine selection tests.

What it does:
    Verifies build_ocr_client() picks the configured OCR backend: explicit
    mock, real Tesseract when available, and graceful fallback to mock when
    the tesseract binary is missing.

How it works:
    - Overrides settings.OCR_ENGINE per test (Django settings fixture).
    - Uses shutil.which to detect the real binary; skips the Tesseract test
      when not installed, and monkeypatches which()->None to simulate a
      missing binary for the fallback test.
"""

from __future__ import annotations

import shutil

import pytest

from documents.processing import build_ocr_client
from pipeline.ocr.mock import MockOcrClient


def test_mock_engine_selected(settings):
    # What: OCR_ENGINE=mock returns the deterministic in-memory client.
    # How: sets the setting, calls the factory, asserts isinstance mock.
    settings.OCR_ENGINE = "mock"
    assert isinstance(build_ocr_client(), MockOcrClient)


def test_tesseract_engine_selected_when_available(settings):
    # What: OCR_ENGINE=tesseract returns the real client when the binary exists.
    # How: skips if `tesseract` not on PATH; otherwise sets the setting and
    #   asserts isinstance TesseractOcrClient.
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract binary not installed")
    from pipeline.ocr.tesseract import TesseractOcrClient

    settings.OCR_ENGINE = "tesseract"
    assert isinstance(build_ocr_client(), TesseractOcrClient)


def test_falls_back_to_mock_without_tesseract(settings, monkeypatch):
    # What: missing tesseract binary falls back to mock instead of crashing.
    # How: sets ENGINE=tesseract but patches shutil.which to return None
    #   (simulating no binary), then asserts a MockOcrClient is returned.
    import documents.processing as processing

    settings.OCR_ENGINE = "tesseract"
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    assert isinstance(build_ocr_client(), MockOcrClient)
