"""Tests for `sheet_identity`: which person an image on a sheet belongs to.

The synthetic series only -- `001100000001`, `NGUYEN VAN MOT`, MST `0011000001`.
"""
from __future__ import annotations

from dataclasses import dataclass

import pipeline
import sheet_identity as si


@dataclass(frozen=True)
class FakeAnchor:
    sheet: str
    center_row: int | None


@dataclass(frozen=True)
class FakeDrawing:
    id: str
    anchor: FakeAnchor


HEADER = ("STT", "Họ và tên", "CCCD", "MST")


def sheet(people: list[tuple[str, str, str]]) -> list[tuple]:
    """A titled, headed sheet of numbered person rows."""
    rows: list[tuple] = [("BẢNG KÊ THANH TOÁN", None, None, None), HEADER]
    for index, (name, cccd, mst) in enumerate(people, start=1):
        rows.append((str(index), name, cccd, mst))
    return rows


#: Three people, in this order, with the synthetic identity series.
THREE = [
    ("NGUYEN VAN MOT", "001100000001", "0011000001"),
    ("NGUYEN VAN HAI", "001100000002", "0011000002"),
    ("NGUYEN VAN BA", "001100000003", "0011000003"),
]


def index_for(people: list[tuple[str, str, str]]):
    return pipeline.build_roster_index(sheet(people))


class TestPeopleByRow:
    def test_rows_are_keyed_by_the_sheets_own_row_index(self):
        # The same index `Anchor.center_row` counts in, so no offset
        # arithmetic stands between a drawing and its row. Two header lines
        # here, so the first person is row 2.
        found = si.people_by_row(sheet(THREE))
        assert sorted(found) == [2, 3, 4]
        assert found[2].name == "NGUYEN VAN MOT"
        assert found[4].mst == "0011000003"

    def test_a_title_or_total_row_is_not_a_person(self):
        rows = list(sheet(THREE)) + [("Tổng cộng", None, None, None)]
        found = si.people_by_row(rows)
        assert len(found) == 3

    def test_a_row_with_no_identity_at_all_is_skipped(self):
        rows = list(sheet(THREE)) + [("4", None, None, None)]
        assert len(si.people_by_row(rows)) == 3

    def test_a_sheet_with_no_recognisable_columns_yields_nothing(self):
        assert si.people_by_row([("a", "b"), ("1", "2")]) == {}

    def test_an_empty_sheet_yields_nothing(self):
        assert si.people_by_row([]) == {}


class TestResolve:
    def test_cccd_wins(self):
        by_cccd, by_name, by_mst = index_for(THREE)
        person = si.SheetPerson(row=2, name="", cccd="001100000002", mst="")
        row, how = si.resolve(person, by_cccd, by_name, by_mst)
        assert how == "cccd" and row["name"] == "NGUYEN VAN HAI"

    def test_mst_resolves_a_sheet_that_carries_no_cccd(self):
        # This is what makes the tax sheet joinable at all: on the real
        # combined workbook the MST sheet carries MST numbers and no CCCD, and
        # all 25 of its screenshots resolve through this key.
        by_cccd, by_name, by_mst = index_for(THREE)
        person = si.SheetPerson(row=3, name="", cccd="", mst="0011000003")
        row, how = si.resolve(person, by_cccd, by_name, by_mst)
        assert how == "mst" and row["name"] == "NGUYEN VAN BA"

    def test_name_is_the_last_resort(self):
        by_cccd, by_name, by_mst = index_for(THREE)
        person = si.SheetPerson(row=2, name="NGUYEN VAN MOT", cccd="", mst="")
        row, how = si.resolve(person, by_cccd, by_name, by_mst)
        assert how == "name" and row["cccd"] == "001100000001"

    def test_an_unknown_person_resolves_to_nothing(self):
        by_cccd, by_name, by_mst = index_for(THREE)
        person = si.SheetPerson(row=9, name="AI DO KHAC", cccd="", mst="")
        row, how = si.resolve(person, by_cccd, by_name, by_mst)
        assert row is None and how == "unmatched"


class TestAttribute:
    def test_a_permuted_sheet_still_attributes_correctly(self):
        """The whole reason this module exists.

        The image sheet lists the same people in a different order -- on the
        real combined workbook the MST sheet disagrees with the roster on 17 of
        25 positions. A positional join sends row 0's image to person 0; this
        reads the person off the image's own row instead.
        """
        by_cccd, by_name, by_mst = index_for(THREE)
        permuted = sheet([THREE[2], THREE[0], THREE[1]])
        drawings = [
            FakeDrawing("d0", FakeAnchor("MST", 2)),   # NGUYEN VAN BA
            FakeDrawing("d1", FakeAnchor("MST", 3)),   # NGUYEN VAN MOT
            FakeDrawing("d2", FakeAnchor("MST", 4)),   # NGUYEN VAN HAI
        ]
        matched, refused = si.attribute(
            drawings, {"MST": permuted}, by_cccd, by_name, by_mst)

        assert refused == {}
        assert matched["d0"]["name"] == "NGUYEN VAN BA"
        assert matched["d1"]["name"] == "NGUYEN VAN MOT"
        assert matched["d2"]["name"] == "NGUYEN VAN HAI"
        # and the positional answer would have been wrong for two of the three
        positional = [p["name"] for p in
                      [matched["d0"], matched["d1"], matched["d2"]]]
        assert positional != [name for name, _, _ in THREE]

    def test_a_drawing_with_no_centre_row_is_refused_not_guessed(self):
        # from_row is not a fallback: it is ragged for 24 of 75 drawings on the
        # real workbook, so guessing from it would misattribute silently.
        by_cccd, by_name, by_mst = index_for(THREE)
        drawings = [FakeDrawing("d0", FakeAnchor("MST", None))]
        matched, refused = si.attribute(
            drawings, {"MST": sheet(THREE)}, by_cccd, by_name, by_mst)
        assert matched == {} and refused == {"d0": "no-centre-row"}

    def test_a_drawing_on_a_row_with_no_person_is_refused(self):
        by_cccd, by_name, by_mst = index_for(THREE)
        drawings = [FakeDrawing("d0", FakeAnchor("MST", 0))]  # the title row
        matched, refused = si.attribute(
            drawings, {"MST": sheet(THREE)}, by_cccd, by_name, by_mst)
        assert refused == {"d0": "no-person-on-row"}

    def test_a_drawing_on_an_unknown_sheet_is_refused(self):
        by_cccd, by_name, by_mst = index_for(THREE)
        drawings = [FakeDrawing("d0", FakeAnchor("NOWHERE", 2))]
        matched, refused = si.attribute(
            drawings, {"MST": sheet(THREE)}, by_cccd, by_name, by_mst)
        assert refused == {"d0": "no-sheet-rows"}

    def test_a_person_absent_from_the_roster_is_refused(self):
        by_cccd, by_name, by_mst = index_for(THREE[:2])
        drawings = [FakeDrawing("d0", FakeAnchor("MST", 4))]
        matched, refused = si.attribute(
            drawings, {"MST": sheet(THREE)}, by_cccd, by_name, by_mst)
        assert matched == {}
        assert refused["d0"].startswith("unmatched")

    def test_each_sheet_is_read_once_however_many_drawings_it_holds(self):
        by_cccd, by_name, by_mst = index_for(THREE)
        calls = {"n": 0}
        real = si.people_by_row

        def counted(rows):
            calls["n"] += 1
            return real(rows)

        si.people_by_row = counted
        try:
            drawings = [FakeDrawing(f"d{i}", FakeAnchor("MST", 2 + i % 3))
                        for i in range(9)]
            matched, refused = si.attribute(
                drawings, {"MST": sheet(THREE)}, by_cccd, by_name, by_mst)
        finally:
            si.people_by_row = real
        assert len(matched) == 9 and refused == {}
        assert calls["n"] == 1
