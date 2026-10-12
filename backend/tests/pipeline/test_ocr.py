"""Tests for the Tesseract OCR client wrapper.

``pytesseract`` is stubbed so the tests are deterministic and do not require a
Tesseract installation.

What it does:
    Verifies TesseractOcrClient.recognize() returns text + mean word
    confidence, handles all-missing confidences as 0.0, and forwards
    languages/PSM/output-type correctly to pytesseract.

How it works:
    - ``FakePytesseract`` mimics image_to_data (word confidences) and
      image_to_string (full text), recording every call's args.
    - Tests inject the fake via the ``_pytesseract`` constructor hook and run
      recognize() on a blank 10x10 Pillow image.
"""

from __future__ import annotations

import pytest
from PIL import Image

from pipeline.ocr.tesseract import TesseractOcrClient


class FakePytesseract:
    # What: deterministic pytesseract double. How: stores canned text + conf
    #   strings; image_to_data/image_to_string log their args and return them.
    def __init__(self, text: str = "hello world", conf: list[str] | None = None) -> None:
        self.text = text
        # "-1" entries are Tesseract's sentinel for non-word tokens, ignored
        # when averaging confidence.
        self.conf = conf if conf is not None else ["90", "-1", "70"]
        self.calls: list[tuple] = []  # (kind, lang/config...) per invocation

    def image_to_data(self, image, lang, config, output_type):
        # What: fakes word-level confidence output. How: logs (data, lang,
        #   config, output_type) then returns {"conf": [...]} dict.
        self.calls.append(("data", lang, config, output_type))
        return {"conf": self.conf}

    def image_to_string(self, image, lang, config):
        # What: fakes full-text output. How: logs (string, lang, config),
        #   returns the canned text.
        self.calls.append(("string", lang, config))
        return self.text


def test_recognize_returns_text_and_mean_confidence():
    # What: normal case averages valid word confidences, ignoring -1.
    # How: feeds conf ["90","-1","70"] -> mean(90,70)/100 = 0.8; asserts text
    #   passthrough + approx 0.8 confidence.
    fake = FakePytesseract(text="Hello world", conf=["90", "-1", "70"])
    client = TesseractOcrClient(languages="eng", _pytesseract=fake)
    result = client.recognize(Image.new("RGB", (10, 10)), page=1)
    assert result.text == "Hello world"
    assert result.confidence == pytest.approx(0.8)


def test_recognize_handles_missing_confidences():
    # What: all -1 confidences collapse to 0.0 (not NaN/div-zero).
    # How: feeds conf ["-1","-1"] with empty text, asserts "" + 0.0.
    fake = FakePytesseract(text="", conf=["-1", "-1"])
    client = TesseractOcrClient(_pytesseract=fake)
    result = client.recognize(Image.new("RGB", (10, 10)), page=2)
    assert result.text == ""
    assert result.confidence == 0.0


def test_recognize_passes_languages_and_psm():
    # What: constructor languages/psm reach pytesseract as lang/config args.
    # How: constructs with eng + psm 6, runs recognize, asserts first data
    #   call logged lang "eng", config "--psm 6", output_type "dict".
    fake = FakePytesseract()
    client = TesseractOcrClient(languages="eng", psm=6, _pytesseract=fake)
    client.recognize(Image.new("RGB", (10, 10)), page=1)
    assert fake.calls[0][1] == "eng"
    assert fake.calls[0][2] == "--psm 6"
    assert fake.calls[0][3] == "dict"
