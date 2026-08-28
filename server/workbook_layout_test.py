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
