from dataclasses import replace
from pathlib import Path

from PIL import Image
import pytest

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


class TestAPortraitCardIsTurnedBeforeItIsGivenUpOn:
    """A CCCD is 85.6x54mm -- always landscape. A portrait one is a photograph
    taken sideways, and the number region is looked for horizontally, so it is
    never found and the card reports `no-number-region`.

    Measured on case 935e37e5 (2026-09-04): 2 of its 4 cards were stored
    portrait, and both read at exactly one rotation, at 0.94 and 0.96 -- higher
    than most, because a sideways photo is otherwise a perfectly good one. OSD
    already runs in `_upright_image` and did not save them: it answered 0.48 and
    0.12 confidence against a 1.5 gate, and for one of the two its answer was
    wrong anyway. So the shape is the signal, not OSD's guess.
    """

    @staticmethod
    def _portrait(monkeypatch, reads_at: int):
        """A portrait image whose number is legible only at `reads_at` degrees."""
        seen = []

        def words_for(image):
            # Only the correctly-turned image yields the number line.
            if image.info.get("_test_angle") == reads_at:
                return [OcrWord("000000000001", 60, 80, 150, 18, .94)]
            return [OcrWord("CĂN", 20, 10, 40, 15, .98)]

        def rotate_recording(image, angle, expand=False):
            turned = Image.new("RGB", (image.height, image.width))
            turned.info.update(image.info)
            turned.info["_test_angle"] = (image.info.get("_test_angle", 0) + angle) % 360
            seen.append(angle)
            return turned

        base = Image.new("RGB", (289, 415))
        base.info["_test_angle"] = 0
        monkeypatch.setattr(co, "_upright_image", lambda path: base)
        monkeypatch.setattr(co, "_full_image_words", words_for)
        monkeypatch.setattr(co, "_name_from_words", lambda w: ("", 0.0))
        monkeypatch.setattr(co, "_region_digits", lambda img, box: ("000000000001", .94))
        monkeypatch.setattr(co.Image.Image, "rotate", rotate_recording, raising=False)
        return seen

    def test_a_portrait_card_reads_after_the_quarter_turn_that_works(
        self, tmp_path, monkeypatch,
    ):
        self._portrait(monkeypatch, reads_at=270)

        result = co.analyze_drawing(_drawing(tmp_path))

        assert result.cccd == "000000000001"

    def test_the_other_quarter_turn_is_tried_too(self, tmp_path, monkeypatch):
        """Which way a photograph was taken is not knowable from its shape, and
        OSD was measured wrong on one of the two real cards. So try both and let
        a valid twelve digits decide -- never guess the direction."""
        self._portrait(monkeypatch, reads_at=90)

        result = co.analyze_drawing(_drawing(tmp_path))

        assert result.cccd == "000000000001"

    def test_a_landscape_card_is_never_turned(self, tmp_path, monkeypatch):
        """The 500+ packets that already read must not move. A card that is
        landscape is left exactly as `_upright_image` returned it."""
        turns = []
        image = Image.new("RGB", (783, 481))
        monkeypatch.setattr(co, "_upright_image", lambda path: image)
        monkeypatch.setattr(co, "_full_image_words",
                            lambda img: [OcrWord("000000000001", 60, 80, 150, 18, .96)])
        monkeypatch.setattr(co, "_name_from_words", lambda w: ("", 0.0))
        monkeypatch.setattr(co, "_region_digits", lambda img, box: ("000000000001", .96))
        monkeypatch.setattr(co.Image.Image, "rotate",
                            lambda self, angle, expand=False: turns.append(angle) or self,
                            raising=False)

        result = co.analyze_drawing(_drawing(tmp_path))

        assert result.cccd == "000000000001"
        assert turns == []

    def test_a_portrait_card_that_reads_at_no_turn_is_left_alone(
        self, tmp_path, monkeypatch,
    ):
        """Turning is a last resort. If the number is already legible, the image
        is not touched -- a rotated evidence crop the reviewer did not need is a
        worse artefact than none."""
        turns = []
        image = Image.new("RGB", (289, 415))
        monkeypatch.setattr(co, "_upright_image", lambda path: image)
        monkeypatch.setattr(co, "_full_image_words",
                            lambda img: [OcrWord("000000000001", 60, 80, 150, 18, .94)])
        monkeypatch.setattr(co, "_name_from_words", lambda w: ("", 0.0))
        monkeypatch.setattr(co, "_region_digits", lambda img, box: ("000000000001", .94))
        monkeypatch.setattr(co.Image.Image, "rotate",
                            lambda self, angle, expand=False: turns.append(angle) or self,
                            raising=False)

        co.analyze_drawing(_drawing(tmp_path))

        assert turns == []

    def test_a_portrait_card_that_reads_at_no_turn_and_never_will_stays_unread(
        self, tmp_path, monkeypatch,
    ):
        """Both turns tried, nothing found: the card reports no number exactly as
        it does today. The fallback must not invent one."""
        image = Image.new("RGB", (289, 415))
        monkeypatch.setattr(co, "_upright_image", lambda path: image)
        monkeypatch.setattr(co, "_full_image_words",
                            lambda img: [OcrWord("CĂN", 20, 10, 40, 15, .98)])
        monkeypatch.setattr(co, "_name_from_words", lambda w: ("", 0.0))

        result = co.analyze_drawing(_drawing(tmp_path))

        assert result.cccd == ""
        assert result.number_bbox is None


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


def test_analyze_drawing_persists_upright_evidence_for_exif_rotation(
    tmp_path,
    monkeypatch,
):
    drawing = replace(
        _drawing(tmp_path, width=400, height=250),
        media_type="image/jpeg",
        extension="jpg",
        stored_path=str(tmp_path / "synthetic.jpg"),
    )
    image = Image.new("RGB", (400, 250), "white")
    exif = Image.Exif()
    exif[274] = 6
    image.save(drawing.stored_path, format="JPEG", exif=exif)
    monkeypatch.setattr(
        co.pytesseract,
        "image_to_osd",
        lambda *args, **kwargs: {"rotate": 0, "orientation_conf": 10.0},
    )
    monkeypatch.setattr(co, "_full_image_words", lambda image: FRONT_WORDS)
    monkeypatch.setattr(
        co,
        "_region_digits",
        lambda image, bbox: ("000000000001", .91),
    )
    monkeypatch.setattr(co, "_name_from_words", lambda words: ("", 0.0))

    result = co.analyze_drawing(drawing)

    assert result.evidence_path is not None
    assert result.evidence_path.endswith("-upright.jpg")
    assert Path(result.evidence_path).is_file()
    with Image.open(result.evidence_path) as evidence:
        assert evidence.size == (250, 400)
    assert (result.evidence_width, result.evidence_height) == (250, 400)


def test_upright_evidence_rejects_per_file_overflow_before_replace(tmp_path):
    drawing = _drawing(tmp_path, width=10, height=10)
    image = Image.new("RGB", (10, 10), "white")
    budget = co.EvidenceWriteBudget(per_file_limit=1, total_limit=1_000)

    with pytest.raises(ValueError, match="upright-evidence-too-large"):
        co._persist_upright_evidence(drawing, image, budget)

    assert not (tmp_path / "synthetic-upright.png").exists()
    assert not list(tmp_path.glob(".cccd-upright-*"))
    assert budget.used_bytes == 0


def test_upright_evidence_enforces_one_shared_cumulative_budget(tmp_path):
    first = _drawing(tmp_path, width=10, height=10)
    second = replace(
        first,
        id="drawing-0002",
        stored_path=str(tmp_path / "synthetic-2.png"),
    )
    image = Image.new("RGB", (10, 10), "white")
    probe = co._persist_upright_evidence(
        first,
        image,
        co.EvidenceWriteBudget(),
    )
    encoded_size = Path(probe).stat().st_size
    Path(probe).unlink()
    budget = co.EvidenceWriteBudget(
        per_file_limit=encoded_size,
        total_limit=encoded_size,
    )

    co._persist_upright_evidence(first, image, budget)
    with pytest.raises(ValueError, match="upright-evidence-total-too-large"):
        co._persist_upright_evidence(second, image, budget)

    assert budget.used_bytes == encoded_size
    assert not (tmp_path / "synthetic-2-upright.png").exists()
    assert not list(tmp_path.glob(".cccd-upright-*"))
