from pathlib import Path

from PIL import Image

import cccd_ocr as co
from cccd_ocr import OcrWord, classify_side, locate_number_region
from cccd_workbook import Anchor, EmbeddedDrawing


def _drawing(tmp_path: Path, width: int = 400, height: int = 250) -> EmbeddedDrawing:
    return EmbeddedDrawing(
        id="drawing-0001",
        anchor=Anchor("Synthetic", 0, 0, 1, 1),
        media_type="image/png",
        extension="png",
        width=width,
        height=height,
        sha256="0" * 64,
        stored_path=str(tmp_path / "synthetic.png"),
    )


FRONT_WORDS = [
    OcrWord("CĂN", 20, 10, 40, 15, .98),
    OcrWord("CƯỚC", 65, 10, 50, 15, .98),
    OcrWord("CÔNG", 120, 10, 45, 15, .98),
    OcrWord("DÂN", 170, 10, 35, 15, .98),
    OcrWord("Số:", 20, 80, 30, 18, .96),
    OcrWord("000000000001", 60, 80, 150, 18, .94),
    OcrWord("Họ", 20, 130, 20, 18, .95),
    OcrWord("và", 45, 130, 20, 18, .95),
    OcrWord("tên:", 70, 130, 35, 18, .95),
]


def test_label_anchored_number_remains_preferred():
    side, confidence = classify_side(FRONT_WORDS)

    assert side == "front"
    assert confidence >= .9
    assert locate_number_region(FRONT_WORDS, 400, 250) == {
        "x": 54,
        "y": 74,
        "width": 162,
        "height": 30,
    }


def test_unique_twelve_digit_word_recovers_region_when_label_is_misread():
    words = [
        OcrWord("CĂN", 20, 10, 40, 15, .98),
        OcrWord("CƯỚC", 65, 10, 50, 15, .98),
        OcrWord("CÔNG", 120, 10, 45, 15, .98),
        OcrWord("DÂN", 170, 10, 35, 15, .98),
        OcrWord("6s:", 20, 80, 30, 18, .71),
        OcrWord("000000000001", 60, 80, 150, 18, .94),
    ]

    assert locate_number_region(words, 400, 250) == {
        "x": 54,
        "y": 74,
        "width": 162,
        "height": 30,
    }


def test_competing_twelve_digit_words_do_not_recover_region():
    words = [
        OcrWord("000000000001", 20, 80, 150, 18, .94),
        OcrWord("000000000002", 20, 120, 150, 18, .93),
    ]

    assert locate_number_region(words, 400, 250) is None


def test_dates_and_short_identity_tokens_do_not_recover_region():
    words = [
        OcrWord("01/02/2026", 20, 80, 100, 18, .99),
        OcrWord("123456789", 20, 120, 100, 18, .99),
    ]

    assert locate_number_region(words, 400, 250) is None


def test_recovered_number_and_front_heading_classify_front():
    words = [
        OcrWord("CĂN", 20, 10, 40, 15, .98),
        OcrWord("CƯỚC", 65, 10, 50, 15, .98),
        OcrWord("CÔNG", 120, 10, 45, 15, .98),
        OcrWord("DÂN", 170, 10, 35, 15, .98),
        OcrWord("000000000001", 60, 80, 150, 18, .94),
    ]

    assert classify_side(words)[0] == "front"


def test_mrz_signature_classifies_back():
    words = [
        OcrWord("IDVNM000000000001<<<<<<<<<<<<<<<", 20, 80, 300, 18, .94),
        OcrWord("0001018M3001012VNM<<<<<<<<<<<8", 20, 110, 300, 18, .93),
    ]

    assert classify_side(words)[0] == "back"


def test_conflicting_structural_signals_stay_unknown():
    words = [
        OcrWord("CĂN", 20, 10, 40, 15, .98),
        OcrWord("CƯỚC", 65, 10, 50, 15, .98),
        OcrWord("CÔNG", 120, 10, 45, 15, .98),
        OcrWord("DÂN", 170, 10, 35, 15, .98),
        OcrWord("000000000001", 60, 80, 150, 18, .94),
        OcrWord("IDVNM000000000001<<<<<<<<<<<<<<<", 20, 160, 300, 18, .94),
    ]

    assert classify_side(words) == ("unknown", 0.0)


def test_analyze_drawing_reocrs_the_recovered_crop(tmp_path, monkeypatch):
    drawing = _drawing(tmp_path)
    words = [
        OcrWord("CĂN", 20, 10, 40, 15, .98),
        OcrWord("CƯỚC", 65, 10, 50, 15, .98),
        OcrWord("CÔNG", 120, 10, 45, 15, .98),
        OcrWord("DÂN", 170, 10, 35, 15, .98),
        OcrWord("6s:", 20, 80, 30, 18, .71),
        OcrWord("000000000001", 60, 80, 150, 18, .94),
    ]
    monkeypatch.setattr(co, "_upright_image", lambda path: Image.new("RGB", (400, 250)))
    monkeypatch.setattr(co, "_full_image_words", lambda image: words)
    seen = {}

    def fake_digits(image, bbox):
        seen["bbox"] = bbox
        return "000000000001", .91

    monkeypatch.setattr(co, "_region_digits", fake_digits)
    monkeypatch.setattr(co, "_name_from_words", lambda words: ("", 0.0))

    result = co.analyze_drawing(drawing)

    assert result.cccd == "000000000001"
    assert result.cccd_confidence == .91
    assert seen["bbox"] == result.number_bbox
