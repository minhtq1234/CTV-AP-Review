import os
import tempfile

import openpyxl

from test_fixtures.combined_workbook import build, build_july


def test_the_fixture_reproduces_the_active_sheet_trap():
    """The real PUBGm file is saved with CCCD selected. If the fixture did not
    do the same, every test below would pass for the wrong reason."""
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["CTV", "CCCD", "MST"]
    assert wb.active.title == "CCCD"          # NOT the bảng kê


def test_the_fixture_has_a_merged_image_header():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    ws = openpyxl.load_workbook(path)["CCCD"]
    merged = {str(r) for r in ws.merged_cells.ranges}
    assert "D1:E1" in merged
    assert ws["D1"].value == "Hình CCCD"


def test_the_july_fixture_is_single_sheet():
    path = build_july(os.path.join(tempfile.mkdtemp(), "roster.xlsx"))
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["Thông tin CK"]


import openpyxl
from workbook_layout import score_roster_sheet, select_roster_sheet


def _rows(path, sheet):
    ws = openpyxl.load_workbook(path, data_only=True)[sheet]
    return [list(r) for r in ws.iter_rows(values_only=True)]


def test_the_ctv_sheet_outscores_its_neighbours():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    scores = {name: score_roster_sheet(_rows(path, name)) for name in ("CTV", "CCCD", "MST")}
    assert scores["CTV"] > scores["CCCD"]
    assert scores["CTV"] > scores["MST"]


def test_select_picks_ctv_even_though_cccd_is_the_active_sheet():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    wb = openpyxl.load_workbook(path, data_only=True)
    sheets = {name: _rows(path, name) for name in wb.sheetnames}
    assert wb.active.title == "CCCD"            # the trap
    assert select_roster_sheet(sheets) == "CTV"  # what we want instead


def test_select_on_a_single_sheet_workbook_picks_that_sheet():
    path = build_july(os.path.join(tempfile.mkdtemp(), "roster.xlsx"))
    sheets = {"Thông tin CK": _rows(path, "Thông tin CK")}
    assert select_roster_sheet(sheets) == "Thông tin CK"


def test_select_returns_none_when_no_sheet_looks_like_a_roster():
    assert select_roster_sheet({"Sheet1": [["hello"], ["world"]]}) is None


from roster_workbook import load_roster_rows


def test_load_roster_rows_reads_the_ctv_sheet_not_the_active_one():
    path = build(os.path.join(tempfile.mkdtemp(), "combined.xlsx"))
    with open(path, "rb") as handle:
        rows = load_roster_rows(handle)
    flat = [str(c) for row in rows for c in row if c is not None]
    # The bảng kê carries MST and a bank name; the CCCD sheet carries neither.
    assert any("MST" in s for s in flat), "read a sheet with no MST column — probably CCCD"
    assert any("Ngân hàng" in s for s in flat)


def test_load_roster_rows_still_reads_a_single_sheet_workbook():
    path = build_july(os.path.join(tempfile.mkdtemp(), "roster.xlsx"))
    with open(path, "rb") as handle:
        rows = load_roster_rows(handle)
    assert any("Họ và tên" in str(c) for row in rows for c in row if c is not None)
