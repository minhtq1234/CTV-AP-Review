from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, pair_drawings
from cccd_workbook import Anchor, EmbeddedDrawing


def analyzed(drawing_id, side, *, anchor, sheet="Cards"):
    from_row, from_col, to_row, to_col = anchor
    return AnalyzedDrawing(
        drawing=EmbeddedDrawing(
            id=drawing_id,
            anchor=Anchor(sheet, from_row, from_col, to_row, to_col),
            media_type="image/png",
            extension="png",
            width=1,
            height=1,
            sha256=f"hash-{drawing_id}",
            stored_path=f"/synthetic/{drawing_id}.png",
        ),
        ocr=CccdImageOcr(
            side=side,
            side_confidence=.99,
            cccd="",
            cccd_confidence=0.0,
            name="",
            name_confidence=0.0,
            number_bbox=None,
        ),
    )


def test_pairs_mutual_nearest_opposite_sides_with_margin():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    back = analyzed("b1", "back", anchor=(1, 1, 10, 2))
    far_back = analyzed("b2", "back", anchor=(30, 1, 39, 2))

    result = pair_drawings([far_back, back, front])

    paired = next(candidate for candidate in result if candidate.front)
    assert paired.front.drawing.id == "f1"
    assert paired.back.drawing.id == "b1"
    assert paired.issues == ()


def test_zero_distance_tie_is_rejected():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    first_back = analyzed("b1", "back", anchor=(1, 0, 10, 1))
    second_back = analyzed("b2", "back", anchor=(1, 0, 10, 1))

    result = pair_drawings([second_back, front, first_back])

    assert not any(candidate.front and candidate.back for candidate in result)
    assert all("ambiguous-pair" in candidate.issues for candidate in result)


def test_other_sheet_and_unknown_images_remain_separate():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1), sheet="A")
    back = analyzed("b1", "back", anchor=(1, 1, 10, 2), sheet="B")
    unknown = analyzed("u1", "unknown", anchor=(1, 2, 10, 3), sheet="A")

    result = pair_drawings([unknown, back, front])

    assert [(candidate.id, candidate.issues) for candidate in result] == [
        ("card-b1", ("missing-front",)),
        ("card-f1", ("missing-back",)),
        ("card-u1", ("unknown-side",)),
    ]
    unknown_candidate = next(
        candidate for candidate in result if candidate.id == "card-u1"
    )
    assert unknown_candidate.front is None
    assert unknown_candidate.back is None
    assert unknown_candidate.unknown is unknown
