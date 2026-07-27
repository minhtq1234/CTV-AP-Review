from pathlib import Path

from PIL import Image

import cccd_ocr as co
from cccd_ocr import OcrWord, classify_side, locate_number_region
from cccd_workbook import Anchor, EmbeddedDrawing


def test_front_markers_classify_front_and_locate_adjacent_number():
    words = [
        OcrWord("CĂN", 20, 10, 40, 15, .98),
        OcrWord("CƯỚC", 65, 10, 50, 15, .98),
        OcrWord("CÔNG", 120, 10, 45, 15, .98),
        OcrWord("DÂN", 170, 10, 35, 15, .98),
        OcrWord("Số:", 20, 80, 30, 18, .96),
        OcrWord("079123456789", 60, 80, 150, 18, .94),
        OcrWord("Họ", 20, 130, 20, 18, .95),
        OcrWord("và", 45, 130, 20, 18, .95),
        OcrWord("tên:", 70, 130, 35, 18, .95),
    ]

    side, confidence = classify_side(words)
    bbox = locate_number_region(words, 400, 250)

    assert side == "front"
    assert confidence >= .9
    assert bbox == {"x": 54, "y": 74, "width": 162, "height": 30}


def test_back_markers_classify_back():
    words = [
        OcrWord("Đặc", 20, 20, 30, 18, .94),
        OcrWord("điểm", 55, 20, 45, 18, .94),
        OcrWord("nhận", 105, 20, 40, 18, .94),
        OcrWord("dạng:", 150, 20, 50, 18, .94),
        OcrWord("Ngày", 20, 80, 40, 18, .96),
        OcrWord("cấp:", 65, 80, 35, 18, .96),
    ]

    side, confidence = classify_side(words)

    assert side == "back"
    assert confidence >= .9


def test_unknown_image_without_two_independent_marker_groups():
    words = [OcrWord("CĂN", 20, 20, 35, 18, .97), OcrWord("CƯỚC", 60, 20, 45, 18, .97)]

    assert classify_side(words) == ("unknown", 0.0)


def test_digits_elsewhere_without_number_label_produce_no_region():
    words = [OcrWord("01/02/2026", 20, 100, 100, 18, .99)]

    assert locate_number_region(words, 400, 250) is None


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
    OcrWord("079123456789", 60, 80, 150, 18, .94),
    OcrWord("Họ", 20, 130, 20, 18, .95),
    OcrWord("và", 45, 130, 20, 18, .95),
    OcrWord("tên:", 70, 130, 35, 18, .95),
]


def test_analyze_drawing_reads_digits_only_from_located_crop(tmp_path, monkeypatch):
    drawing = _drawing(tmp_path)
    monkeypatch.setattr(co, "_upright_image", lambda path: Image.new("RGB", (400, 250)))
    monkeypatch.setattr(co, "_full_image_words", lambda image: FRONT_WORDS)
    seen = {}

    def fake_digits(image, bbox):
        seen["bbox"] = bbox
        return "079123456789", .93

    monkeypatch.setattr(co, "_region_digits", fake_digits)
    monkeypatch.setattr(co, "_name_from_words", lambda words: ("Nguyen Van A", .91))

    result = co.analyze_drawing(drawing)

    assert result.cccd == "079123456789"
    assert result.cccd_confidence == .93
    assert seen["bbox"] == result.number_bbox


def test_analyze_drawing_skips_region_ocr_without_number_label(tmp_path, monkeypatch):
    drawing = _drawing(tmp_path)
    words = [OcrWord("CĂN", 20, 10, 40, 15, .98), OcrWord("CƯỚC", 65, 10, 50, 15, .98)]
    monkeypatch.setattr(co, "_upright_image", lambda path: Image.new("RGB", (400, 250)))
    monkeypatch.setattr(co, "_full_image_words", lambda image: words)
    monkeypatch.setattr(co, "_region_digits", lambda image, bbox: (_ for _ in ()).throw(AssertionError("must not OCR a whole image")))

    result = co.analyze_drawing(drawing)

    assert result.number_bbox is None
    assert result.cccd == ""
