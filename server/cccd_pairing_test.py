from itertools import permutations

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
            side_confidence=0.99,
            cccd="",
            cccd_confidence=0.0,
            name="",
            name_confidence=0.0,
            number_bbox=None,
        ),
    )


def _ids(candidate):
    return (
        candidate.id,
        candidate.front.drawing.id if candidate.front else None,
        candidate.back.drawing.id if candidate.back else None,
        candidate.issues,
    )


def test_pairs_mutual_nearest_opposite_sides_with_margin():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    back = analyzed("b1", "back", anchor=(1, 1, 10, 2))
    far_back = analyzed("b2", "back", anchor=(30, 1, 39, 2))

    out = pair_drawings([far_back, back, front])

    paired = next(candidate for candidate in out if candidate.front and candidate.front.drawing.id == "f1")
    assert paired.back.drawing.id == "b1"
    assert paired.issues == ()


def test_ambiguous_neighbor_is_not_paired():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    back_one = analyzed("b1", "back", anchor=(1, 1, 10, 2))
    back_two = analyzed("b2", "back", anchor=(2, 1, 11, 2))

    out = pair_drawings([front, back_one, back_two])

    candidate = next(candidate for candidate in out if candidate.front)
    assert candidate.back is None
    assert "ambiguous-pair" in candidate.issues


def test_same_side_images_remain_separate():
    first = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    second = analyzed("f2", "front", anchor=(1, 1, 10, 2))

    out = pair_drawings([first, second])

    assert [_ids(candidate) for candidate in out] == [
        ("card-f1", "f1", None, ("missing-back",)),
        ("card-f2", "f2", None, ("missing-back",)),
    ]


def test_images_on_other_sheets_remain_separate():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1), sheet="A")
    back = analyzed("b1", "back", anchor=(1, 1, 10, 2), sheet="B")

    out = pair_drawings([front, back])

    assert [_ids(candidate) for candidate in out] == [
        ("card-b1", None, "b1", ("missing-front",)),
        ("card-f1", "f1", None, ("missing-back",)),
    ]


def test_images_without_row_overlap_or_nearby_starts_remain_separate():
    front = analyzed("f1", "front", anchor=(1, 0, 3, 1))
    back = analyzed("b1", "back", anchor=(10, 1, 12, 2))

    out = pair_drawings([front, back])

    assert [_ids(candidate) for candidate in out] == [
        ("card-b1", None, "b1", ("missing-front",)),
        ("card-f1", "f1", None, ("missing-back",)),
    ]


def test_incomplete_and_unknown_images_are_preserved_for_manual_handling():
    front = analyzed("f1", "front", anchor=(1, 0, 10, 1))
    back = analyzed("b1", "back", anchor=(20, 1, 29, 2))
    unknown = analyzed("u1", "unknown", anchor=(30, 0, 39, 1))

    out = pair_drawings([unknown, back, front])

    assert [_ids(candidate) for candidate in out] == [
        ("card-b1", None, "b1", ("missing-front",)),
        ("card-f1", "f1", None, ("missing-back",)),
        ("card-u1", None, None, ("unknown-side",)),
    ]


def test_output_order_and_candidate_ids_do_not_depend_on_input_order():
    images = [
        analyzed("b1", "back", anchor=(1, 1, 10, 2)),
        analyzed("f1", "front", anchor=(1, 0, 10, 1)),
        analyzed("u1", "unknown", anchor=(20, 0, 29, 1)),
    ]

    results = [[_ids(candidate) for candidate in pair_drawings(list(order))] for order in permutations(images)]

    assert results == [
        [
            ("card-f1-b1", "f1", "b1", ()),
            ("card-u1", None, None, ("unknown-side",)),
        ]
    ] * len(results)


def test_a_drawing_cannot_be_assigned_to_two_candidates():
    first_front = analyzed("f1", "front", anchor=(0, 0, 10, 1))
    second_front = analyzed("f2", "front", anchor=(1, 10, 2, 11))
    back = analyzed("b1", "back", anchor=(0, 1, 10, 2))

    out = pair_drawings([second_front, back, first_front])

    assigned_ids = [
        drawing.drawing.id
        for candidate in out
        for drawing in (candidate.front, candidate.back)
        if drawing
    ]
    assert assigned_ids.count("b1") == 1
    assert next(candidate for candidate in out if candidate.front and candidate.front.drawing.id == "f1").back.drawing.id == "b1"
    assert next(candidate for candidate in out if candidate.front and candidate.front.drawing.id == "f2").back is None
