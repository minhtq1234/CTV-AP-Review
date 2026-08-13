import ast
import builtins
from datetime import date
from io import BytesIO
from pathlib import Path
import socket
import struct
import tempfile
import zipfile

from openpyxl import Workbook
from openpyxl.drawing.image import Image as WorkbookImage
from PIL import Image
import pytest

from ctv_inspection_model import InspectionLimits


PRIVATE_SHEET_NAMES = (
    "Bảng kê CTV riêng 079123456789",
    "Hỗ trợ nội bộ có dấu",
    "Ảnh đính kèm bí mật",
)
PRIVATE_CELL_VALUES = (
    "NGUYEN VAN KIEM THU 079123456789",
    "=SUM(C3:C4)+987654321",
    "13/08/2026",
    "1250000",
)
PRIVATE_MEMBER_NAME = "xl/media/private-identity-079123456789.png"
PRIVATE_EXTERNAL_VALUE = "EXTERNAL-PRIVATE-079123456789"


def _save(workbook):
    stream = BytesIO()
    workbook.save(stream)
    workbook.close()
    return stream.getvalue()


def _workbook_with_sheets(sheet_specs):
    workbook = Workbook()
    workbook.remove(workbook.active)
    for name, state, rows in sheet_specs:
        sheet = workbook.create_sheet(name)
        sheet.sheet_state = state
        for row in rows:
            sheet.append(row)
    return workbook


def _synthetic_png():
    stream = BytesIO()
    with Image.new("RGB", (2, 2), (12, 34, 56)) as image:
        image.save(stream, format="PNG")
    stream.seek(0)
    return stream


def _roster_workbook(*, with_image=False):
    workbook = _workbook_with_sheets(
        (
            (
                PRIVATE_SHEET_NAMES[0],
                "visible",
                (
                    ("DANH SACH CHI TRA", None, None, None),
                    ("Ho ten", "Ma so nhan vien", "So tien", "Cong thuc"),
                    (
                        PRIVATE_CELL_VALUES[0],
                        "CTV-001",
                        1_250_000,
                        PRIVATE_CELL_VALUES[1],
                    ),
                    ("Nguoi thu hai", "CTV-002", date(2026, 8, 13), 250_000),
                ),
            ),
            (
                PRIVATE_SHEET_NAMES[1],
                "hidden",
                (("MA SO NHAN VIEN",),),
            ),
            (
                PRIVATE_SHEET_NAMES[2],
                "veryHidden",
                (("TAI LIEU KEM THEO", PRIVATE_CELL_VALUES[2], PRIVATE_CELL_VALUES[3]),),
            ),
        )
    )
    if with_image:
        workbook.worksheets[2].add_image(WorkbookImage(_synthetic_png()), "D4")
    return workbook


def _inspect(snapshot, *, limits=None):
    from ctv_inspection_workbook import inspect_workbook

    return inspect_workbook(snapshot, limits=limits or InspectionLimits())


def _rewrite_package(snapshot, *, replacements=None, additions=None, drop=()):
    replacements = replacements or {}
    additions = additions or {}
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(snapshot), "r") as source:
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as target:
            for info in source.infolist():
                if info.filename in drop:
                    continue
                content = source.read(info)
                target.writestr(info.filename, replacements.get(info.filename, content))
            for name, content in additions.items():
                target.writestr(name, content)
    return output.getvalue()


def _patch_central_sizes(snapshot, patches):
    data = bytearray(snapshot)
    cursor = 0
    seen = set()
    signature = b"PK\x01\x02"
    while True:
        cursor = data.find(signature, cursor)
        if cursor < 0:
            break
        name_length, extra_length, comment_length = struct.unpack_from(
            "<HHH", data, cursor + 28
        )
        name_start = cursor + 46
        name = bytes(data[name_start:name_start + name_length]).decode("utf-8")
        if name in patches:
            compressed_size, uncompressed_size = patches[name]
            struct.pack_into("<II", data, cursor + 20, compressed_size, uncompressed_size)
            seen.add(name)
        cursor = name_start + name_length + extra_length + comment_length
    assert seen == set(patches)
    return bytes(data)


def _patch_encrypted_flag(snapshot, member_name):
    data = bytearray(snapshot)
    central = data.find(b"PK\x01\x02")
    patched_local = False
    patched_central = False
    while central >= 0:
        name_length, extra_length, comment_length = struct.unpack_from(
            "<HHH", data, central + 28
        )
        name_start = central + 46
        name = bytes(data[name_start:name_start + name_length]).decode("utf-8")
        if name == member_name:
            flag = struct.unpack_from("<H", data, central + 8)[0] | 1
            struct.pack_into("<H", data, central + 8, flag)
            local_offset = struct.unpack_from("<I", data, central + 42)[0]
            local_flag = struct.unpack_from("<H", data, local_offset + 6)[0] | 1
            struct.pack_into("<H", data, local_offset + 6, local_flag)
            patched_local = patched_central = True
            break
        central = data.find(
            b"PK\x01\x02",
            name_start + name_length + extra_length + comment_length,
        )
    assert patched_local and patched_central
    return bytes(data)


def _assert_private_values_absent(value, *extra_fragments):
    public = f"{value!s}\n{value!r}"
    forbidden = (
        *PRIVATE_SHEET_NAMES,
        *PRIVATE_CELL_VALUES,
        PRIVATE_MEMBER_NAME,
        PRIVATE_EXTERNAL_VALUE,
        "079123456789",
        "987654321",
        "1250000",
        "13/08/2026",
        *extra_fragments,
    )
    assert not any(fragment in public for fragment in forbidden)


def test_workbook_emits_one_ordered_unit_for_every_sheet_with_fixed_signals_only():
    snapshot = _save(_roster_workbook(with_image=True))

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert result.unit_count == 3
    assert result.source_issue_codes == ()
    assert [unit.unit_index for unit in result.units] == [1, 2, 3]
    assert [unit.unit_kind for unit in result.units] == ["worksheet"] * 3
    assert [unit.inspection_method for unit in result.units] == [
        "worksheet-structure",
        "worksheet-structure",
        "worksheet-structure",
    ]
    assert result.units[0].signal_codes == (
        "roster-column-pattern",
        "roster-row-pattern",
        "identity-number-pattern-present",
        "mostly-text-page",
    )
    assert result.units[0].issue_codes == ()
    assert result.units[1].signal_codes == (
        "roster-column-pattern",
        "worksheet-hidden",
        "mostly-text-page",
    )
    assert result.units[1].issue_codes == ("worksheet-hidden",)
    assert result.units[2].signal_codes == (
        "supporting-document-heading",
        "embedded-media-present",
        "worksheet-hidden",
        "mostly-text-page",
    )
    assert result.units[2].issue_codes == (
        "embedded-media-present",
        "worksheet-hidden",
    )
    _assert_private_values_absent(result)


def test_workbook_passes_only_bytesio_and_exact_safe_openpyxl_options(monkeypatch):
    import ctv_inspection_workbook as workbook_adapter

    snapshot = _save(_roster_workbook())
    real_loader = workbook_adapter.openpyxl.load_workbook
    calls = []

    def recording_loader(source, **kwargs):
        calls.append((source, kwargs))
        return real_loader(source, **kwargs)

    monkeypatch.setattr(workbook_adapter.openpyxl, "load_workbook", recording_loader)

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert len(calls) == 1
    assert isinstance(calls[0][0], BytesIO)
    assert calls[0][0].getvalue() == snapshot
    assert calls[0][1] == {
        "read_only": True,
        "data_only": False,
        "keep_links": False,
    }


@pytest.mark.parametrize("sheet_count", [100, 101])
def test_actual_worksheet_count_has_exact_operation_boundary(sheet_count):
    workbook = Workbook()
    workbook.active.title = "sheet-000"
    for index in range(1, sheet_count):
        workbook.create_sheet(f"sheet-{index:03d}")
    snapshot = _save(workbook)

    if sheet_count == 100:
        result = _inspect(snapshot)
        assert result.inspection_status == "inspected"
        assert result.unit_count == 100
        assert [unit.unit_index for unit in result.units] == list(range(1, 101))
        return

    from ctv_inspection_workbook import WorkbookWorksheetCountExceededError

    with pytest.raises(WorkbookWorksheetCountExceededError) as raised:
        _inspect(snapshot)
    assert str(raised.value) == "inspection-worksheet-count-exceeded"
    _assert_private_values_absent(raised.value)


def test_global_100000_cell_budget_keeps_later_sheets_as_known_unknown_units():
    workbook = Workbook()
    first = workbook.active
    first.title = "private-budget-first"
    first["A1"] = "DANH SACH CHI TRA"
    first["A100000"] = "bounded-tail"
    second = workbook.create_sheet("private-budget-second")
    second["A1"] = "TAI LIEU KEM THEO"
    snapshot = _save(workbook)

    result = _inspect(snapshot)

    assert result.unit_count == 2
    assert result.units[0].inspection_method == "worksheet-structure"
    assert result.units[0].issue_codes == ()
    assert result.units[1].inspection_method == "none"
    assert result.units[1].signal_codes == ()
    assert result.units[1].issue_codes == ("unit-over-limit",)
    _assert_private_values_absent(result, "private-budget-first", "private-budget-second")


@pytest.mark.parametrize("character_count", [256, 257])
def test_per_cell_text_boundary_is_exact_and_never_returns_a_prefix(character_count):
    marker = "DANH SACH CHI TRA"
    private_value = marker + " " + "Z" * (character_count - len(marker) - 1)
    workbook = Workbook()
    workbook.active["A1"] = private_value
    snapshot = _save(workbook)

    result = _inspect(snapshot)

    unit = result.units[0]
    if character_count == 256:
        assert unit.inspection_method == "worksheet-structure"
        assert "roster-column-pattern" in unit.signal_codes
        assert unit.issue_codes == ()
    else:
        assert unit.inspection_method == "none"
        assert unit.signal_codes == ()
        assert unit.issue_codes == ("unit-over-limit",)
    assert private_value not in repr(result)


def test_workbook_source_byte_limit_is_inclusive_and_source_only_when_exceeded():
    snapshot = _save(_roster_workbook())

    accepted = _inspect(
        snapshot,
        limits=InspectionLimits(max_workbook_source_bytes=len(snapshot)),
    )
    rejected = _inspect(
        snapshot,
        limits=InspectionLimits(max_workbook_source_bytes=len(snapshot) - 1),
    )

    assert accepted.inspection_status == "inspected"
    assert rejected.inspection_status == "over-limit"
    assert rejected.unit_count is None
    assert rejected.source_issue_codes == ("document-over-limit",)
    assert rejected.units == ()


@pytest.mark.parametrize(
    "snapshot",
    (
        bytearray(b"private-mutable-079123456789"),
        memoryview(b"private-view-079123456789"),
        "private-text-079123456789",
    ),
)
def test_workbook_accepts_only_exact_immutable_bytes(snapshot):
    with pytest.raises(TypeError) as raised:
        _inspect(snapshot)
    assert str(raised.value) == "inspection snapshot must be bytes"
    _assert_private_values_absent(
        raised.value,
        "private-mutable",
        "private-view",
        "private-text",
    )


@pytest.mark.parametrize(
    ("snapshot", "status", "issue"),
    (
        (b"not-a-private-workbook-079123456789", "unreadable", "document-unreadable"),
        (
            b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1encrypted-like-private",
            "encrypted",
            "document-encrypted",
        ),
    ),
)
def test_corrupt_and_encrypted_like_sources_return_only_safe_source_status(
    snapshot, status, issue
):
    result = _inspect(snapshot)

    assert result.inspection_status == status
    assert result.unit_count is None
    assert result.source_issue_codes == (issue,)
    assert result.units == ()
    _assert_private_values_absent(result)


def test_zip_encryption_flag_returns_encrypted_without_opening_members(monkeypatch):
    snapshot = _patch_encrypted_flag(
        _save(_roster_workbook()), "[Content_Types].xml"
    )
    opened = []
    original_open = zipfile.ZipFile.open

    def recording_open(self, name, *args, **kwargs):
        opened.append(name)
        return original_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", recording_open)

    result = _inspect(snapshot)

    assert result.inspection_status == "encrypted"
    assert result.source_issue_codes == ("document-encrypted",)
    assert opened == []


def test_generic_zip_and_missing_required_member_are_not_treated_as_workbooks():
    generic = BytesIO()
    with zipfile.ZipFile(generic, "w") as archive:
        archive.writestr("private-member-079123456789.txt", b"private bytes")
    missing = _rewrite_package(
        _save(_roster_workbook()), drop=("xl/workbook.xml",)
    )

    for snapshot in (generic.getvalue(), missing):
        result = _inspect(snapshot)
        assert result.inspection_status == "unreadable"
        assert result.unit_count is None
        assert result.source_issue_codes == ("document-unreadable",)
        assert result.units == ()
        _assert_private_values_absent(result, "private-member-079123456789.txt")


@pytest.mark.parametrize("declaration", [b"<!DOCTYPE workbook>", b"<!ENTITY private 'x'>"])
def test_malformed_or_entity_declaring_ooxml_is_safely_unreadable(declaration):
    snapshot = _save(_roster_workbook())
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        workbook_xml = archive.read("xl/workbook.xml")
    mutated = declaration + workbook_xml + b"PRIVATE-PARSER-TOKEN-079123456789"
    snapshot = _rewrite_package(
        snapshot,
        replacements={"xl/workbook.xml": mutated},
    )

    result = _inspect(snapshot)

    assert result.inspection_status == "unreadable"
    assert result.source_issue_codes == ("document-unreadable",)
    _assert_private_values_absent(result, "PRIVATE-PARSER-TOKEN-079123456789")


def test_xml_pull_parser_is_fed_only_bounded_chunks(monkeypatch):
    import ctv_inspection_workbook as workbook_adapter

    workbook = Workbook()
    sheet = workbook.active
    bounded_value = "Z" * 256
    for row in range(1, 401):
        sheet.cell(row=row, column=1, value=bounded_value)
    snapshot = _save(workbook)
    original_parser = workbook_adapter.ElementTree.XMLPullParser
    feed_sizes = []

    class TrackingPullParser:
        def __init__(self, *args, **kwargs):
            self.parser = original_parser(*args, **kwargs)

        def feed(self, data):
            feed_sizes.append(len(data))
            return self.parser.feed(data)

        def read_events(self):
            return self.parser.read_events()

        def close(self):
            return self.parser.close()

    monkeypatch.setattr(
        workbook_adapter.ElementTree,
        "XMLPullParser",
        TrackingPullParser,
    )

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert feed_sizes
    assert max(feed_sizes) <= 64 * 1024


def test_missing_worksheet_dimension_is_not_silently_treated_as_an_empty_sheet():
    snapshot = _save(_roster_workbook())
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    dimension_start = sheet_xml.index(b"<dimension")
    dimension_end = sheet_xml.index(b"/>", dimension_start) + 2
    sheet_xml = sheet_xml[:dimension_start] + sheet_xml[dimension_end:]
    snapshot = _rewrite_package(
        snapshot,
        replacements={"xl/worksheets/sheet1.xml": sheet_xml},
    )

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert result.unit_count == 3
    assert result.units[0].inspection_method == "none"
    assert result.units[0].signal_codes == ()
    assert result.units[0].issue_codes == ("unit-over-limit",)
    _assert_private_values_absent(result)


def test_underreported_worksheet_dimension_cannot_hide_private_cells():
    snapshot = _save(_roster_workbook())
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    dimension_start = sheet_xml.index(b"<dimension")
    dimension_end = sheet_xml.index(b"/>", dimension_start) + 2
    sheet_xml = (
        sheet_xml[:dimension_start]
        + b'<dimension ref="A1:A1"/>'
        + sheet_xml[dimension_end:]
    )
    snapshot = _rewrite_package(
        snapshot,
        replacements={"xl/worksheets/sheet1.xml": sheet_xml},
    )

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert result.unit_count == 3
    assert result.units[0].inspection_method == "none"
    assert result.units[0].signal_codes == ()
    assert result.units[0].issue_codes == ("unit-over-limit",)
    _assert_private_values_absent(result)


def test_lazy_cell_parse_failure_retains_hidden_sheet_signal_without_diagnostics():
    workbook = _workbook_with_sheets(
        (
            ("visible-private", "visible", (("safe",),)),
            ("hidden-private", "hidden", ((123,),)),
        )
    )
    snapshot = _save(workbook)
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        sheet_xml = archive.read("xl/worksheets/sheet2.xml")
    sheet_xml = sheet_xml.replace(b"<v>123</v>", b"<v>PRIVATE-NOT-A-NUMBER</v>")
    snapshot = _rewrite_package(
        snapshot,
        replacements={"xl/worksheets/sheet2.xml": sheet_xml},
    )

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert result.units[1].inspection_method == "none"
    assert result.units[1].signal_codes == ("worksheet-hidden",)
    assert result.units[1].issue_codes == ("unit-over-limit", "worksheet-hidden")
    _assert_private_values_absent(
        result,
        "visible-private",
        "hidden-private",
        "PRIVATE-NOT-A-NUMBER",
        "invalid literal",
    )


def test_spoofed_worksheet_relationship_type_is_rejected_before_openpyxl(monkeypatch):
    import ctv_inspection_workbook as workbook_adapter

    snapshot = _save(_roster_workbook())
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        rels = archive.read("xl/_rels/workbook.xml.rels")
    rels = rels.replace(
        b"http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
        b"https://private.invalid/worksheet",
    )
    snapshot = _rewrite_package(
        snapshot,
        replacements={"xl/_rels/workbook.xml.rels": rels},
    )
    loader_calls = []

    def forbidden_loader(*args, **kwargs):
        loader_calls.append((args, kwargs))
        raise AssertionError("preflight must reject spoofed relationship types")

    monkeypatch.setattr(workbook_adapter.openpyxl, "load_workbook", forbidden_loader)

    result = _inspect(snapshot)

    assert result.inspection_status == "unreadable"
    assert result.source_issue_codes == ("document-unreadable",)
    assert loader_calls == []
    _assert_private_values_absent(result, "private.invalid")


def test_relationship_pull_parser_retains_only_requested_ids():
    import ctv_inspection_workbook as workbook_adapter

    unrelated = b"".join(
        (
            b'<Relationship Id="private-%d" Type="private-type" '
            b'Target="private-target-%d"/>'
        ) % (index, index)
        for index in range(1_000)
    )
    content = (
        b'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        + unrelated
        + b'<Relationship Id="rIdWanted" Type="wanted-type" Target="wanted-target"/>'
        + b"</Relationships>"
    )

    relationships = workbook_adapter._relationships(content, {"rIdWanted"})

    assert relationships == {
        "rIdWanted": ("wanted-type", "wanted-target", False),
    }
    assert "private-target" not in repr(relationships)


def test_worksheet_pull_parser_retains_only_one_drawing_presence_reference():
    import ctv_inspection_workbook as workbook_adapter

    drawings = b"".join(
        b'<drawing r:id="rId%d"/>' % index
        for index in range(1_000)
    )
    content = (
        b'<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        b'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        b'<dimension ref="A1:A1"/>'
        + drawings
        + b"</worksheet>"
    )

    drawing_ids, cell_bound = workbook_adapter._worksheet_metadata(content)

    assert drawing_ids == ("rId0",)
    assert cell_bound == 1


def test_workbook_xml_sheet_limit_raises_while_relationship_ids_are_parsed():
    import ctv_inspection_workbook as workbook_adapter

    content = b"""<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
        xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
        <sheets><sheet name="private-one" sheetId="1" r:id="rId1"/>
        <sheet name="private-two" sheetId="2" r:id="rId2"/></sheets></workbook>"""

    with pytest.raises(
        workbook_adapter.WorkbookWorksheetCountExceededError
    ) as raised:
        workbook_adapter._workbook_sheet_relationship_ids(content, 1)
    assert str(raised.value) == "inspection-worksheet-count-exceeded"
    _assert_private_values_absent(raised.value, "private-one", "private-two")


def test_macro_external_link_and_image_members_are_never_read(monkeypatch):
    snapshot = _save(_roster_workbook(with_image=True))
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        workbook_xml = archive.read("xl/workbook.xml")
        workbook_rels = archive.read("xl/_rels/workbook.xml.rels")
        content_types = archive.read("[Content_Types].xml")
        media_names = [
            info.filename for info in archive.infolist()
            if info.filename.startswith("xl/media/")
        ]
        drawing_names = [
            info.filename for info in archive.infolist()
            if info.filename.startswith("xl/drawings/")
        ]
    assert len(media_names) == 1
    workbook_xml = workbook_xml.replace(
        b"</workbook>",
        b'<externalReferences><externalReference xmlns:r="http://schemas.'
        b'openxmlformats.org/officeDocument/2006/relationships" r:id="rId99"/>'
        b'</externalReferences></workbook>',
    )
    workbook_rels = workbook_rels.replace(
        b"</Relationships>",
        b'<Relationship Type="http://schemas.openxmlformats.org/officeDocument/2006/'
        b'relationships/externalLink" Target="externalLinks/externalLink1.xml" '
        b'Id="rId99"/></Relationships>',
    )
    content_types = content_types.replace(
        b"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
        b"application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    ).replace(
        b"</Types>",
        b'<Override PartName="/xl/vbaProject.bin" '
        b'ContentType="application/vnd.ms-office.vbaProject"/></Types>',
    )
    snapshot = _rewrite_package(
        snapshot,
        replacements={
            "xl/workbook.xml": workbook_xml,
            "xl/_rels/workbook.xml.rels": workbook_rels,
            "[Content_Types].xml": content_types,
        },
        additions={
            "xl/vbaProject.bin": b"PRIVATE-MACRO-079123456789",
            "xl/externalLinks/externalLink1.xml": (
                b"<externalLink>" + PRIVATE_EXTERNAL_VALUE.encode() + b"</externalLink>"
            ),
        },
    )
    prohibited = {
        *media_names,
        *drawing_names,
        "xl/vbaProject.bin",
        "xl/externalLinks/externalLink1.xml",
    }
    original_open = zipfile.ZipFile.open
    opened = []

    def guarded_open(self, name, *args, **kwargs):
        member_name = name.filename if isinstance(name, zipfile.ZipInfo) else name
        if member_name in prohibited:
            raise AssertionError("non-worksheet workbook member was read")
        opened.append(member_name)
        return original_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", guarded_open)

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert "embedded-media-present" in result.units[2].signal_codes
    assert prohibited.isdisjoint(opened)
    _assert_private_values_absent(result, "PRIVATE-MACRO-079123456789")


def test_zip_entry_count_boundary_raises_before_zipfile_allocation(monkeypatch):
    snapshot = _save(_roster_workbook())
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        existing_count = len(archive.infolist())
    additions = {
        f"private-extra/{index:05d}.bin": b""
        for index in range(10_000 - existing_count)
    }
    snapshot = _rewrite_package(snapshot, additions=additions)

    accepted = _inspect(snapshot)

    assert accepted.inspection_status == "inspected"
    assert accepted.unit_count == 3
    snapshot = _rewrite_package(
        snapshot,
        additions={"private-extra/over-limit.bin": b""},
    )

    def forbidden_zipfile(*_args, **_kwargs):
        raise AssertionError("oversized central directory was allocated")

    monkeypatch.setattr(zipfile, "ZipFile", forbidden_zipfile)

    from ctv_inspection_workbook import WorkbookParserBoundaryExceededError

    with pytest.raises(WorkbookParserBoundaryExceededError) as raised:
        _inspect(snapshot)
    assert str(raised.value) == "inspection-parser-boundary-exceeded"
    _assert_private_values_absent(raised.value, "private-extra")


def test_declared_member_ratio_and_aggregate_limits_are_inclusive():
    extra_names = tuple(f"private-boundary-{index}.bin" for index in range(4))
    snapshot = _rewrite_package(
        _save(_roster_workbook()),
        additions={name: b"X" for name in extra_names},
    )
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        ordinary_total = sum(
            info.file_size
            for info in archive.infolist()
            if info.filename not in extra_names
        )
    remaining = 100 * 1024 * 1024 - ordinary_total
    declared_sizes = []
    for _ in extra_names:
        size = min(25 * 1024 * 1024, remaining)
        declared_sizes.append(size)
        remaining -= size
    assert remaining == 0
    assert declared_sizes[0] == 25 * 1024 * 1024
    patches = {
        name: ((size + 99) // 100, size)
        for name, size in zip(extra_names, declared_sizes)
    }
    assert patches[extra_names[0]] == (256 * 1024, 25 * 1024 * 1024)
    snapshot = _patch_central_sizes(snapshot, patches)

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert result.unit_count == 3
    _assert_private_values_absent(result, "private-boundary")


@pytest.mark.parametrize("adversary", ["member", "aggregate", "ratio"])
def test_declared_zip_resource_boundaries_raise_only_stable_parser_error(adversary):
    snapshot = _save(_roster_workbook())
    with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
        names = [info.filename for info in archive.infolist()]
    if adversary == "member":
        patches = {names[0]: (1024 * 1024, 25 * 1024 * 1024 + 1)}
    elif adversary == "aggregate":
        patches = {
            name: (1024 * 1024, 25 * 1024 * 1024)
            for name in names[:5]
        }
    else:
        patches = {names[0]: (1, 101)}
    snapshot = _patch_central_sizes(snapshot, patches)

    from ctv_inspection_workbook import WorkbookParserBoundaryExceededError

    with pytest.raises(WorkbookParserBoundaryExceededError) as raised:
        _inspect(snapshot)
    assert str(raised.value) == "inspection-parser-boundary-exceeded"
    _assert_private_values_absent(raised.value)


def test_actual_member_decompression_is_counted_and_bounded(monkeypatch):
    snapshot = _save(_roster_workbook())
    original_open = zipfile.ZipFile.open

    class ExpandingReader:
        def __init__(self):
            self.remaining = 25 * 1024 * 1024 + 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self, size=-1):
            if self.remaining <= 0:
                return b""
            amount = self.remaining if size < 0 else min(size, self.remaining)
            self.remaining -= amount
            return b"X" * amount

    def expanding_open(self, name, *args, **kwargs):
        member_name = name.filename if isinstance(name, zipfile.ZipInfo) else name
        if member_name == "[Content_Types].xml":
            return ExpandingReader()
        return original_open(self, name, *args, **kwargs)

    monkeypatch.setattr(zipfile.ZipFile, "open", expanding_open)

    from ctv_inspection_workbook import WorkbookParserBoundaryExceededError

    with pytest.raises(WorkbookParserBoundaryExceededError) as raised:
        _inspect(snapshot)
    assert str(raised.value) == "inspection-parser-boundary-exceeded"


def test_actual_aggregate_decompression_budget_is_exact():
    import ctv_inspection_workbook as workbook_adapter

    budget = workbook_adapter._ActualByteBudget()
    for _ in range(4):
        budget.consume(25 * 1024 * 1024, 25 * 1024 * 1024)
    assert budget.used == 100 * 1024 * 1024

    with pytest.raises(
        workbook_adapter.WorkbookParserBoundaryExceededError
    ) as raised:
        budget.consume(1, 1)
    assert str(raised.value) == "inspection-parser-boundary-exceeded"


def test_inspection_never_extracts_writes_uses_temp_network_or_ocr(monkeypatch):
    snapshot = _save(_roster_workbook(with_image=True))

    def forbidden(*_args, **_kwargs):
        raise AssertionError("forbidden side effect")

    monkeypatch.setattr(zipfile.ZipFile, "extract", forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(Path, "write_bytes", forbidden)
    monkeypatch.setattr(Path, "write_text", forbidden)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    result = _inspect(snapshot)

    assert result.inspection_status == "inspected"
    assert result.unit_count == 3


def test_workbook_module_has_a_narrow_import_and_archive_surface():
    module_path = Path(__file__).with_name("ctv_inspection_workbook.py")
    tree = ast.parse(module_path.read_text())
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])
    assert imported_roots <= {
        "__future__",
        "datetime",
        "io",
        "openpyxl",
        "zipfile",
        "xml",
        "ctv_inspection_classifier",
        "ctv_inspection_model",
        "ooxml",
    }
    assert imported_roots.isdisjoint({
        "os",
        "pathlib",
        "tempfile",
        "socket",
        "subprocess",
        "tarfile",
        "rarfile",
        "pytesseract",
    })
    source = module_path.read_text()
    assert ".extract(" not in source
    assert ".extractall(" not in source

    inspection_modules = sorted(
        candidate
        for candidate in Path(__file__).parent.glob("ctv_inspection*.py")
        if not candidate.name.endswith("_test.py")
    )
    archive_importers = []
    for candidate in inspection_modules:
        candidate_tree = ast.parse(candidate.read_text())
        if any(
            (
                isinstance(node, ast.Import)
                and any(alias.name == "zipfile" for alias in node.names)
            )
            or (
                isinstance(node, ast.ImportFrom)
                and node.module == "zipfile"
            )
            for node in ast.walk(candidate_tree)
        ):
            archive_importers.append(candidate.name)
    assert archive_importers == ["ctv_inspection_workbook.py"]
