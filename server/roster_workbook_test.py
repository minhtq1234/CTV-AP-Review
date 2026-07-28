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
    worksheet.append(["Synthetic A", "000000000001"])
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
    assert load_roster_rows(io.BytesIO(_workbook_bytes())) == [
        ["Họ và tên", "Số CCCD"],
        ["Synthetic A", "000000000001"],
    ]


def test_external_worksheet_relationship_is_rejected():
    content = _workbook_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        relationships = archive.read("xl/_rels/workbook.xml.rels")
    malformed = _replace_part(
        content,
        "xl/_rels/workbook.xml.rels",
        relationships.replace(
            b'Id="rId1"',
            b'TargetMode="External" Id="rId1"',
            1,
        ),
    )

    with pytest.raises(RosterWorkbookError, match="external-relationship"):
        preflight_roster_workbook(io.BytesIO(malformed))


def test_traversal_worksheet_relationship_is_rejected():
    content = _workbook_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        relationships = archive.read("xl/_rels/workbook.xml.rels")
    malformed = _replace_part(
        content,
        "xl/_rels/workbook.xml.rels",
        relationships.replace(
            b'Target="/xl/worksheets/sheet1.xml"',
            b'Target="../../outside.xml"',
            1,
        ),
    )

    with pytest.raises(RosterWorkbookError, match="invalid-target"):
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
def test_archive_and_xml_limits_are_hard_failures(
    monkeypatch,
    limit_name,
    error_code,
):
    monkeypatch.setattr(roster_workbook, limit_name, 1)

    with pytest.raises(RosterWorkbookError, match=error_code):
        preflight_roster_workbook(io.BytesIO(_workbook_bytes()))


def test_unbounded_workbook_never_reaches_openpyxl(monkeypatch):
    content = _workbook_bytes()
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        worksheet = archive.read("xl/worksheets/sheet1.xml")
    malformed = _replace_part(
        content,
        "xl/worksheets/sheet1.xml",
        worksheet.replace(b"A1:B2", b"A1:B200001"),
    )
    loader_calls = 0

    def unbounded_loader(*_args, **_kwargs):
        nonlocal loader_calls
        loader_calls += 1
        raise AssertionError("OpenPyXL must not run before bounded preflight")

    monkeypatch.setattr(roster_workbook.openpyxl, "load_workbook", unbounded_loader)

    with pytest.raises(RosterWorkbookError, match="worksheet-row-limit"):
        load_roster_rows(io.BytesIO(malformed))

    assert loader_calls == 0
