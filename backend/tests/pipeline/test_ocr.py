"""Tests for the Tesseract OCR client wrapper.

``pytesseract`` is stubbed so the tests are deterministic and do not require a
Tesseract installation.
"""

from __future__ import annotations

import pytest
from PIL import Image

from pipeline.ocr.tesseract import TesseractOcrClient


class FakePytesseract:
    def __init__(self, text: str = "hello world", conf: list[str] | None = None) -> None:
        self.text = text
        self.conf = conf if conf is not None else ["90", "-1", "70"]
        self.calls: list[tuple] = []

    def image_to_data(self, image, lang, config, output_type):
        self.calls.append(("data", lang, config, output_type))
        return {"conf": self.conf}

    def image_to_string(self, image, lang, config):
        self.calls.append(("string", lang, config))
        return self.text


def test_recognize_returns_text_and_mean_confidence():
    fake = FakePytesseract(text="Hello world", conf=["90", "-1", "70"])
    client = TesseractOcrClient(languages="eng", _pytesseract=fake)
    result = client.recognize(Image.new("RGB", (10, 10)), page=1)
    assert result.text == "Hello world"
    assert result.confidence == pytest.approx(0.8)


def test_recognize_handles_missing_confidences():
    fake = FakePytesseract(text="", conf=["-1", "-1"])
    client = TesseractOcrClient(_pytesseract=fake)
    result = client.recognize(Image.new("RGB", (10, 10)), page=2)
    assert result.text == ""
    assert result.confidence == 0.0


def test_recognize_passes_languages_and_psm():
    fake = FakePytesseract()
    client = TesseractOcrClient(languages="eng", psm=6, _pytesseract=fake)
    client.recognize(Image.new("RGB", (10, 10)), page=1)
    assert fake.calls[0][1] == "eng"
    assert fake.calls[0][2] == "--psm 6"
    assert fake.calls[0][3] == "dict"
