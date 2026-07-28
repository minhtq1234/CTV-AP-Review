import io
import zipfile

import openpyxl
import pytest

import roster_workbook
from roster_workbook import (
    RosterWorkbookError,
    load_roster_rows,
    preflight_roster_workbook,
)


def _workbook_bytes() -> bytes:
    content = io.BytesIO()
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["Họ và tên", "Số CCCD"])
    worksheet.append(["Synthetic A", "079123456789"])
    workbook.save(content)
    workbook.close()
    return content.getvalue()


def _replace_part(content: bytes, member: str, replacement: bytes) -> bytes:
    target_bytes = io.BytesIO()
    with (
        zipfile.ZipFile(io.BytesIO(content)) as source,
        zipfile.ZipFile(target_bytes, "w") as target,
    ):
        for info in source.infolist():
            target.writestr(
                info,
                replacement if info.filename == member else source.read(info),
            )
    return target_bytes.getvalue()


def test_valid_roster_is_preflighted_and_loaded():
    rows = load_roster_rows(io.BytesIO(_workbook_bytes()))

    assert rows == [
        ["Họ và tên", "Số CCCD"],
        ["Synthetic A", "079123456789"],
    ]


@pytest.mark.parametrize(
    ("member", "replacement"),
    [
        ("xl/workbook.xml", b"<workbook"),
        ("xl/worksheets/sheet1.xml", b"<worksheet"),
    ],
)
def test_malformed_workbook_or_worksheet_xml_is_rejected(member, replacement):
    malformed = _replace_part(_workbook_bytes(), member, replacement)

    with pytest.raises(RosterWorkbookError, match="invalid-workbook"):
        preflight_roster_workbook(io.BytesIO(malformed))


@pytest.mark.parametrize(
    ("limit_name", "error_code"),
    [
        ("MAX_WORKBOOK_BYTES", "workbook-too-large"),
        ("MAX_ARCHIVE_MEMBERS", "archive-member-limit"),
        ("MAX_ARCHIVE_MEMBER_BYTES", "archive-member-too-large"),
        ("MAX_ARCHIVE_UNCOMPRESSED_BYTES", "archive-uncompressed-too-large"),
        ("MAX_XML_BYTES", "xml-too-large"),
    ],
)
def test_container_and_xml_limits_are_hard_failures(
    monkeypatch,
    limit_name,
    error_code,
):
    monkeypatch.setattr(roster_workbook, limit_name, 1)

    with pytest.raises(RosterWorkbookError, match=error_code):
        preflight_roster_workbook(io.BytesIO(_workbook_bytes()))


@pytest.mark.parametrize(
    ("limit_name", "error_code"),
    [
        ("MAX_WORKSHEET_ROWS", "worksheet-row-limit"),
        ("MAX_WORKSHEET_COLUMNS", "worksheet-column-limit"),
        ("MAX_WORKSHEET_CELLS", "worksheet-cell-limit"),
        ("MAX_STRING_CHARACTERS", "string-too-large"),
    ],
)
def test_worksheet_shape_and_string_limits_are_hard_failures(
    monkeypatch,
    limit_name,
    error_code,
):
    monkeypatch.setattr(roster_workbook, limit_name, 1)

    with pytest.raises(RosterWorkbookError, match=error_code):
        preflight_roster_workbook(io.BytesIO(_workbook_bytes()))
