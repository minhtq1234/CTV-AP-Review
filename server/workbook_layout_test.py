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


import openpyxl as _openpyxl
import pytest

from roster_workbook import RosterWorkbookError, preflight_roster_workbook
from workbook_layout import missing_required_columns


def _workbook_with_only(path, headers):
    wb = _openpyxl.Workbook()
    ws = wb.active
    for col, text in enumerate(headers, start=1):
        ws.cell(row=1, column=col, value=text)
    ws.cell(row=2, column=1, value=1)
    wb.save(path)
    return path


def test_missing_required_columns_names_what_is_absent():
    rows = [["STT", "Họ tên", "Số CCCD"], [1, "NGUYEN VAN MOT", "001100000001"]]
    assert missing_required_columns(rows) == ["money"]
    rows_no_name = [["STT", "Số CCCD"], [1, "001100000001"]]
    assert "name" in missing_required_columns(rows_no_name)


def test_preflight_refuses_a_workbook_with_no_usable_roster_sheet():
    path = _workbook_with_only(os.path.join(tempfile.mkdtemp(), "bad.xlsx"),
                               ["STT", "Họ tên", "Số CCCD"])
    with open(path, "rb") as handle:
        with pytest.raises(RosterWorkbookError) as caught:
            preflight_roster_workbook(handle)
    assert "roster" in str(caught.value)


def test_preflight_accepts_both_real_templates():
    for builder in (build, build_july):
        path = builder(os.path.join(tempfile.mkdtemp(), "ok.xlsx"))
        with open(path, "rb") as handle:
            preflight_roster_workbook(handle)     # must not raise


def test_the_upload_response_names_the_sheet_read_and_what_was_missing(tmp_path, monkeypatch):
    """Task 4's whole point: the reviewer must be able to tell a wrong-sheet
    read from a legitimately empty column, and before a full processing run."""
    import app as appmod
    from fastapi.testclient import TestClient

    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    path = _workbook_with_only(os.path.join(tempfile.mkdtemp(), "bad.xlsx"),
                               ["STT", "Họ tên", "Số CCCD"])
    with open(path, "rb") as handle:
        payload = handle.read()

    response = TestClient(appmod.app).post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "roster": (
                "roster.xlsx",
                payload,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 422
    detail = response.json()["detail"]
    assert detail["code"] == "invalid-roster-workbook"
    assert "money" in detail["reason"]
    assert "Sheet" in detail["reason"]        # names the sheet it actually read


from workbook_layout import classify_image_columns


def test_a_merged_header_covers_both_card_columns():
    # "Hình CCCD" merged across D:E -- one label, two columns, front and back.
    header = {3: "Hình CCCD", 4: "Hình CCCD", 5: "STK", 6: "Hình Ảnh"}
    kinds = classify_image_columns(header, sheet_name="CCCD")
    assert kinds[3] == "card"
    assert kinds[4] == "card"


def test_an_image_column_beside_stk_is_a_bank_screenshot():
    header = {3: "Hình CCCD", 4: "Hình CCCD", 5: "STK", 6: "Hình Ảnh"}
    kinds = classify_image_columns(header, sheet_name="CCCD")
    assert kinds[6] == "bank"


def test_an_image_column_on_an_mst_sheet_is_a_tax_screenshot():
    header = {0: "STT", 1: "Họ tên", 2: "MST", 3: "Hình Ảnh"}
    kinds = classify_image_columns(header, sheet_name="MST")
    assert kinds[3] == "tax"


def test_a_sheet_with_no_image_headers_classifies_nothing():
    assert classify_image_columns({0: "STT", 1: "Họ và tên"}, sheet_name="Thông tin CK") == {}
