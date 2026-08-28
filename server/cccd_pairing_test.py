import dataclasses

from cccd_ocr import CccdImageOcr
from cccd_pairing import AnalyzedDrawing, pair_drawings
from cccd_workbook import Anchor, EmbeddedDrawing


def analyzed(
    drawing_id,
    side,
    *,
    anchor,
    sheet="Cards",
    from_col_offset=0,
):
    from_row, from_col, to_row, to_col = anchor
    return AnalyzedDrawing(
        drawing=EmbeddedDrawing(
            id=drawing_id,
            anchor=Anchor(
                sheet,
                from_row,
                from_col,
                to_row,
                to_col,
                from_col_offset=from_col_offset,
            ),
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


def test_pairs_unknown_sides_by_left_right_layout():
    right = analyzed("drawing-0001", "unknown", anchor=(2, 4, 12, 6))
    left = analyzed("drawing-0099", "unknown", anchor=(2, 1, 12, 3))

    result = pair_drawings([right, left])

    assert len(result) == 1
    assert result[0].id == "card-drawing-0099-drawing-0001"
    assert result[0].front is left
    assert result[0].back is right
    assert result[0].unknown is None
    assert result[0].issues == ()


def test_pairs_start_rows_differing_by_one():
    left = analyzed("left", "unknown", anchor=(2, 1, 3, 3))
    right = analyzed("right", "unknown", anchor=(3, 4, 4, 6))

    result = pair_drawings([right, left])

    assert [(candidate.front, candidate.back) for candidate in result] == [
        (left, right),
    ]


def test_orders_same_column_by_from_column_offset():
    right = analyzed(
        "drawing-0001",
        "unknown",
        anchor=(2, 4, 12, 6),
        from_col_offset=900,
    )
    left = analyzed(
        "drawing-0099",
        "unknown",
        anchor=(2, 4, 12, 6),
        from_col_offset=100,
    )

    result = pair_drawings([right, left])

    assert result[0].front is left
    assert result[0].back is right


def test_singleton_preserves_side_specific_provenance():
    front = analyzed("front", "front", anchor=(2, 1, 12, 3))
    back = analyzed("back", "back", anchor=(30, 1, 40, 3))
    unknown = analyzed("unknown", "unknown", anchor=(60, 1, 70, 3))

    result = pair_drawings([unknown, back, front])

    assert [(candidate.id, candidate.issues) for candidate in result] == [
        ("card-back", ("missing-front",)),
        ("card-front", ("missing-back",)),
        ("card-unknown", ("unknown-side",)),
    ]


def test_drawings_on_different_sheets_remain_separate():
    left = analyzed("left", "unknown", anchor=(2, 1, 12, 3), sheet="A")
    right = analyzed("right", "unknown", anchor=(2, 4, 12, 6), sheet="B")

    result = pair_drawings([right, left])

    assert [(candidate.id, candidate.issues) for candidate in result] == [
        ("card-left", ("unknown-side",)),
        ("card-right", ("unknown-side",)),
    ]


def test_distant_row_bands_remain_separate():
    left = analyzed("left", "unknown", anchor=(2, 1, 12, 3))
    right = analyzed("right", "unknown", anchor=(20, 4, 30, 6))

    result = pair_drawings([right, left])

    assert [(candidate.id, candidate.issues) for candidate in result] == [
        ("card-left", ("unknown-side",)),
        ("card-right", ("unknown-side",)),
    ]


def test_connected_three_image_row_group_is_ambiguous():
    left = analyzed("left", "unknown", anchor=(2, 1, 12, 3))
    middle = analyzed("middle", "unknown", anchor=(2, 4, 12, 6))
    right = analyzed("right", "unknown", anchor=(2, 7, 12, 9))

    result = pair_drawings([right, left, middle])

    assert len(result) == 3
    assert all(candidate.issues == ("ambiguous-pair",) for candidate in result)
    assert not any(candidate.front and candidate.back for candidate in result)


def test_equal_horizontal_starts_are_ambiguous():
    first = analyzed("first", "unknown", anchor=(2, 4, 12, 6))
    second = analyzed("second", "unknown", anchor=(2, 4, 12, 6))

    result = pair_drawings([second, first])

    assert [(candidate.id, candidate.issues) for candidate in result] == [
        ("card-first", ("ambiguous-pair",)),
        ("card-second", ("ambiguous-pair",)),
    ]


def test_layout_sides_win_over_conflicting_ocr_sides():
    left = analyzed("left", "back", anchor=(2, 1, 12, 3))
    right = analyzed("right", "front", anchor=(2, 4, 12, 6))

    result = pair_drawings([right, left])

    assert len(result) == 1
    assert result[0].front is left
    assert result[0].back is right
    assert result[0].issues == ("layout-side-conflict",)


def test_candidate_ids_and_output_order_are_deterministic_for_reversed_input():
    top_left = analyzed("z-left", "unknown", anchor=(2, 1, 12, 3))
    top_right = analyzed("z-right", "unknown", anchor=(2, 4, 12, 6))
    bottom_left = analyzed("a-left", "unknown", anchor=(30, 1, 40, 3))
    bottom_right = analyzed("a-right", "unknown", anchor=(30, 4, 40, 6))

    result = pair_drawings(
        [bottom_right, bottom_left, top_right, top_left]
    )

    assert [candidate.id for candidate in result] == [
        "card-a-left-a-right",
        "card-z-left-z-right",
    ]


def test_aggregate_layout_groups_yield_29_pairs_and_3_singles():
    images = []
    for index in range(29):
        row = index * 20
        images.extend([
            analyzed(
                f"pair-{index:02d}-right",
                "unknown",
                anchor=(row, 4, row + 10, 6),
            ),
            analyzed(
                f"pair-{index:02d}-left",
                "unknown",
                anchor=(row, 1, row + 10, 3),
            ),
        ])
    for index in range(3):
        row = 600 + index * 20
        images.append(
            analyzed(
                f"single-{index:02d}",
                "unknown",
                anchor=(row, 1, row + 10, 3),
            )
        )

    result = pair_drawings(list(reversed(images)))

    assert len(result) == 32
    assert sum(
        candidate.front is not None and candidate.back is not None
        for candidate in result
    ) == 29
    assert sum(
        candidate.front is None or candidate.back is None
        for candidate in result
    ) == 3


def analyzed_kind(drawing_id, side, *, anchor, kind, sheet="Cards"):
    """Same as `analyzed`, but with the drawing's declared image kind set."""
    base = analyzed(drawing_id, side, anchor=anchor, sheet=sheet)
    return AnalyzedDrawing(
        drawing=dataclasses.replace(base.drawing, kind=kind),
        ocr=base.ocr,
    )


def test_a_card_front_is_never_paired_with_a_bank_screenshot():
    """On the combined template the card columns (D:E) and the bank screenshot
    column (G) sit on the same row. A packet missing its back leaves the front
    and the screenshot alone together, and proximity alone pairs them."""
    front = analyzed_kind("drawing-0001", "front", anchor=(2, 3, 12, 4), kind="card")
    bank = analyzed_kind("drawing-0002", "unknown", anchor=(2, 6, 12, 7), kind="bank")

    result = pair_drawings([front, bank])

    # The screenshot is not paired with the front -- and no longer becomes a
    # candidate of its own either, since it is not a card at all. This assertion
    # was `len(result) == 2` while a non-card still entered the pool.
    assert len(result) == 1
    assert result[0].front is front
    assert result[0].back is None
    referenced = {
        drawing.drawing.id
        for candidate in result
        for drawing in (candidate.front, candidate.back, candidate.unknown)
        if drawing
    }
    assert "drawing-0002" not in referenced


def test_two_card_columns_still_pair_normally():
    front = analyzed_kind("drawing-0001", "front", anchor=(2, 3, 12, 3), kind="card")
    back = analyzed_kind("drawing-0002", "back", anchor=(2, 4, 12, 4), kind="card")

    result = pair_drawings([front, back])

    assert len(result) == 1
    assert result[0].front is front
    assert result[0].back is back


def test_drawings_with_no_declared_kind_keep_todays_proximity_behaviour():
    """The July cccd.xlsx has no image headers, so every drawing has kind None.
    That path must be byte-for-byte what it was before kinds existed."""
    right = analyzed("drawing-0001", "unknown", anchor=(2, 4, 12, 6))
    left = analyzed("drawing-0099", "unknown", anchor=(2, 1, 12, 3))

    result = pair_drawings([right, left])

    assert len(result) == 1
    assert result[0].front is left
    assert result[0].back is right


def test_screenshots_do_not_enter_the_candidate_pool():
    """A bank or tax screenshot is not half a card and not a whole one either.
    They used to become single candidates with `unknown-side`, so the combined
    workbook offered the reviewer 81 unresolved cards where about five need
    attention -- which made the CCCD review step unusable on that template."""
    images = [
        analyzed_kind("front-1", "front", anchor=(1, 3, 11, 3), kind="card"),
        analyzed_kind("back-1", "back", anchor=(1, 4, 11, 4), kind="card"),
        analyzed_kind("bank-1", "unknown", anchor=(1, 6, 11, 6), kind="bank"),
        analyzed_kind("tax-1", "unknown", anchor=(1, 3, 11, 3), kind="tax"),
    ]

    candidates = pair_drawings(images)

    assert len(candidates) == 1
    ids = {d.drawing.id for c in candidates for d in (c.front, c.back) if d}
    assert ids == {"front-1", "back-1"}


def test_an_unclassified_drawing_still_becomes_a_candidate():
    """`kind is None` means the sheet declared no image headers -- the July
    cccd.xlsx. That path keeps proximity pairing exactly as it was, so an
    unclassified drawing must still be offered to the reviewer."""
    images = [analyzed_kind("lone", "unknown", anchor=(1, 3, 11, 3), kind=None)]
    assert len(pair_drawings(images)) == 1


def analyzed_emu(drawing_id, side, *, kind, row, col, top, bottom, sheet="Cards"):
    """A drawing that sits inside a single row, carrying real EMU geometry.

    This is the shape the combined template actually produces -- `to_row ==
    from_row` -- which a row-span measure cannot size at all.
    """
    base = analyzed(drawing_id, side, anchor=(row, col, row, col), sheet=sheet)
    return AnalyzedDrawing(
        drawing=dataclasses.replace(
            base.drawing,
            kind=kind,
            anchor=dataclasses.replace(
                base.drawing.anchor, top_emu=top, bottom_emu=bottom,
            ),
        ),
        ocr=base.ocr,
    )


def test_two_sides_inside_one_row_pair_on_their_real_geometry():
    """The combined template's cards sit inside a single row each, so
    `to_row - from_row` is 0 and the old ratio returned 0.0 for every one of
    them. Nothing paired: all 48 sides chained into one component instead."""
    front = analyzed_emu("front-1", "front", kind="card", row=4, col=3,
                         top=1_733_550, bottom=3_400_000)
    back = analyzed_emu("back-1", "back", kind="card", row=4, col=4,
                        top=1_740_000, bottom=3_410_000)

    result = pair_drawings([front, back])

    assert len(result) == 1
    assert result[0].front is front
    assert result[0].back is back


def test_a_drawing_in_the_next_row_is_not_a_neighbour():
    """The rule that broke the combined template: row adjacency made every card
    eligible with the card below it, so consecutive rows chained into one
    component. Real geometry must keep rows apart."""
    first = analyzed_emu("row-4", "front", kind="card", row=4, col=3,
                         top=1_733_550, bottom=3_400_000)
    second = analyzed_emu("row-5", "front", kind="card", row=5, col=3,
                          top=3_467_100, bottom=5_133_000)

    result = pair_drawings([first, second])

    assert len(result) == 2, "consecutive rows must not chain into one component"
    assert all(candidate.back is None for candidate in result)


def test_a_drifted_side_still_pairs_when_it_genuinely_overlaps():
    """A side whose anchor starts a row lower than its partner still pairs, so
    long as the drawings really do overlap -- the requirement the old row
    tolerance existed to serve, now measured rather than assumed."""
    front = analyzed_emu("front-2", "front", kind="card", row=14, col=3,
                         top=1_000_000, bottom=2_000_000)
    back = analyzed_emu("back-2", "back", kind="card", row=15, col=4,
                        top=1_040_000, bottom=2_040_000)

    result = pair_drawings([front, back])

    assert len(result) == 1
    assert result[0].front is front and result[0].back is back
