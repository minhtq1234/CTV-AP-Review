"""Bounded, byte-only OOXML workbook inspection."""
from __future__ import annotations

from datetime import date
from io import BytesIO
import zipfile
from xml.etree import ElementTree

import openpyxl

from ctv_inspection_classifier import TextSignalContext, signals_from_private_text
from ctv_inspection_model import (
    InspectionAdapterResult,
    InspectionLimits,
    InspectionUnitEvidence,
    SIGNAL_ORDER,
)
from ooxml import OoxmlRelationshipError, resolve_internal_relationship_target


_MAX_ARCHIVE_ENTRIES = 10_000
_MAX_DECOMPRESSED_BYTES = 100 * 1024 * 1024
_MAX_MEMBER_BYTES = 25 * 1024 * 1024
_MAX_COMPRESSION_RATIO = 100
_READ_CHUNK_BYTES = 64 * 1024
_CONTENT_TYPES_PART = "[Content_Types].xml"
_WORKBOOK_PART = "xl/workbook.xml"
_WORKBOOK_RELS_PART = "xl/_rels/workbook.xml.rels"
_OLE_COMPOUND_HEADER = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
_RELATIONSHIP_ID_ATTRIBUTE = (
    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
)
_WORKBOOK_CONTENT_TYPES = frozenset({
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml",
    "application/vnd.ms-excel.sheet.macroEnabled.main+xml",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template.main+xml",
    "application/vnd.ms-excel.template.macroEnabled.main+xml",
})
_WORKSHEET_RELATIONSHIP_TYPES = frozenset({
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/worksheet",
})
_DRAWING_RELATIONSHIP_TYPES = frozenset({
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing",
    "http://purl.oclc.org/ooxml/officeDocument/relationships/drawing",
})


class WorkbookParserBoundaryExceededError(RuntimeError):
    """Stable operation boundary for unsafe OOXML parser/decompression work."""

    def __init__(self) -> None:
        super().__init__("inspection-parser-boundary-exceeded")


class WorkbookWorksheetCountExceededError(RuntimeError):
    """Stable operation boundary raised before prohibited sheet iteration."""

    def __init__(self) -> None:
        super().__init__("inspection-worksheet-count-exceeded")


class _UnreadableWorkbookError(ValueError):
    pass


class _EncryptedWorkbookError(ValueError):
    pass


class _ActualByteBudget:
    def __init__(self) -> None:
        self.used = 0

    def consume(self, amount: int, member_used: int) -> None:
        if (
            amount < 0
            or member_used > _MAX_MEMBER_BYTES
            or self.used + amount > _MAX_DECOMPRESSED_BYTES
        ):
            raise WorkbookParserBoundaryExceededError()
        self.used += amount


def _source_problem(status: str, issue: str) -> InspectionAdapterResult:
    return InspectionAdapterResult(status, None, (issue,), ())


def _local_name(tag: object) -> str:
    if not isinstance(tag, str):
        return ""
    return tag.rsplit("}", 1)[-1]


def _safe_xml_events(content: bytes):
    upper_content = content.upper()
    if b"<!DOCTYPE" in upper_content or b"<!ENTITY" in upper_content:
        raise _UnreadableWorkbookError()
    parser = ElementTree.XMLPullParser(events=("start", "end"))
    try:
        for offset in range(0, len(content), _READ_CHUNK_BYTES):
            parser.feed(content[offset:offset + _READ_CHUNK_BYTES])
            yield from parser.read_events()
        parser.close()
        yield from parser.read_events()
    except Exception:
        raise _UnreadableWorkbookError() from None
    finally:
        content = b""


def _validate_eocd(snapshot: bytes) -> int:
    minimum_eocd_bytes = 22
    if len(snapshot) < minimum_eocd_bytes:
        raise _UnreadableWorkbookError()
    search_start = max(0, len(snapshot) - (65_535 + minimum_eocd_bytes))
    eocd_offset = snapshot.rfind(b"PK\x05\x06", search_start)
    if eocd_offset < 0 or eocd_offset + minimum_eocd_bytes > len(snapshot):
        raise _UnreadableWorkbookError()
    try:
        disk_number = int.from_bytes(snapshot[eocd_offset + 4:eocd_offset + 6], "little")
        central_disk = int.from_bytes(snapshot[eocd_offset + 6:eocd_offset + 8], "little")
        disk_entries = int.from_bytes(snapshot[eocd_offset + 8:eocd_offset + 10], "little")
        total_entries = int.from_bytes(snapshot[eocd_offset + 10:eocd_offset + 12], "little")
        central_size = int.from_bytes(snapshot[eocd_offset + 12:eocd_offset + 16], "little")
        central_offset = int.from_bytes(snapshot[eocd_offset + 16:eocd_offset + 20], "little")
        comment_size = int.from_bytes(snapshot[eocd_offset + 20:eocd_offset + 22], "little")
    except Exception:
        raise _UnreadableWorkbookError() from None
    if (
        disk_number != 0
        or central_disk != 0
        or disk_entries != total_entries
        or total_entries == 0xFFFF
        or central_size == 0xFFFFFFFF
        or central_offset == 0xFFFFFFFF
    ):
        raise WorkbookParserBoundaryExceededError()
    if total_entries > _MAX_ARCHIVE_ENTRIES:
        raise WorkbookParserBoundaryExceededError()
    if (
        eocd_offset + minimum_eocd_bytes + comment_size != len(snapshot)
        or central_offset + central_size != eocd_offset
    ):
        raise _UnreadableWorkbookError()
    return total_entries


def _central_directory(archive: zipfile.ZipFile, expected_entries: int):
    try:
        infos = archive.infolist()
    except Exception:
        raise _UnreadableWorkbookError() from None
    if len(infos) != expected_entries:
        raise _UnreadableWorkbookError()
    declared_total = 0
    members = {}
    for info in infos:
        member_name = info.filename
        if member_name in members:
            raise _UnreadableWorkbookError()
        if info.flag_bits & 1:
            raise _EncryptedWorkbookError()
        declared_size = info.file_size
        compressed_size = info.compress_size
        if (
            not isinstance(declared_size, int)
            or isinstance(declared_size, bool)
            or not isinstance(compressed_size, int)
            or isinstance(compressed_size, bool)
            or declared_size < 0
            or compressed_size < 0
        ):
            raise _UnreadableWorkbookError()
        if declared_size > _MAX_MEMBER_BYTES:
            raise WorkbookParserBoundaryExceededError()
        declared_total += declared_size
        if declared_total > _MAX_DECOMPRESSED_BYTES:
            raise WorkbookParserBoundaryExceededError()
        if declared_size and (
            compressed_size == 0
            or declared_size > compressed_size * _MAX_COMPRESSION_RATIO
        ):
            raise WorkbookParserBoundaryExceededError()
        members[member_name] = info
    if _CONTENT_TYPES_PART not in members or _WORKBOOK_PART not in members:
        raise _UnreadableWorkbookError()
    return members


def _read_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    budget: _ActualByteBudget,
) -> bytes:
    chunks = []
    member_used = 0
    try:
        with archive.open(info, "r") as stream:
            while True:
                chunk = stream.read(_READ_CHUNK_BYTES)
                if not chunk:
                    break
                if not isinstance(chunk, bytes):
                    raise _UnreadableWorkbookError()
                member_used += len(chunk)
                budget.consume(len(chunk), member_used)
                chunks.append(chunk)
    except WorkbookParserBoundaryExceededError:
        raise
    except RuntimeError:
        if info.flag_bits & 1:
            raise _EncryptedWorkbookError() from None
        raise _UnreadableWorkbookError() from None
    except Exception:
        raise _UnreadableWorkbookError() from None
    if member_used != info.file_size:
        raise _UnreadableWorkbookError()
    content = b"".join(chunks)
    chunks.clear()
    return content


def _content_types_are_workbook(content: bytes) -> bool:
    found = False
    root_seen = False
    for event, element in _safe_xml_events(content):
        local = _local_name(element.tag)
        if event == "start" and not root_seen:
            root_seen = local == "Types"
            if not root_seen:
                raise _UnreadableWorkbookError()
        if event == "start" and local == "Override":
            if (
                element.attrib.get("PartName") == "/xl/workbook.xml"
                and element.attrib.get("ContentType") in _WORKBOOK_CONTENT_TYPES
            ):
                found = True
        if event == "end":
            element.clear()
    return root_seen and found


def _workbook_sheet_relationship_ids(
    content: bytes,
    max_worksheets: int,
) -> tuple[str, ...]:
    relationship_ids = []
    seen_ids = set()
    root_seen = False
    for event, element in _safe_xml_events(content):
        local = _local_name(element.tag)
        if event == "start" and not root_seen:
            root_seen = local == "workbook"
            if not root_seen:
                raise _UnreadableWorkbookError()
        if event == "start" and local == "sheet":
            relationship_id = element.attrib.get(_RELATIONSHIP_ID_ATTRIBUTE)
            if not relationship_id or relationship_id in seen_ids:
                raise _UnreadableWorkbookError()
            relationship_ids.append(relationship_id)
            seen_ids.add(relationship_id)
            if len(relationship_ids) > max_worksheets:
                raise WorkbookWorksheetCountExceededError()
        if event == "end":
            element.clear()
    if not root_seen:
        raise _UnreadableWorkbookError()
    return tuple(relationship_ids)


def _relationships(content: bytes, wanted_ids):
    wanted_ids = frozenset(wanted_ids)
    relationships = {}
    root_seen = False
    for event, element in _safe_xml_events(content):
        local = _local_name(element.tag)
        if event == "start" and not root_seen:
            root_seen = local == "Relationships"
            if not root_seen:
                raise _UnreadableWorkbookError()
        if event == "start" and local == "Relationship":
            relationship_id = element.attrib.get("Id")
            if relationship_id not in wanted_ids:
                continue
            relationship_type = element.attrib.get("Type")
            target = element.attrib.get("Target")
            target_mode = element.attrib.get("TargetMode")
            if (
                not relationship_id
                or relationship_id in relationships
                or not relationship_type
                or not target
                or target_mode not in {None, "External"}
            ):
                raise _UnreadableWorkbookError()
            relationships[relationship_id] = (
                relationship_type,
                target,
                target_mode == "External",
            )
        if event == "end":
            element.clear()
    if not root_seen:
        raise _UnreadableWorkbookError()
    return relationships


def _cell_position(reference: object):
    if not isinstance(reference, str) or not reference:
        return None
    split_at = 0
    while split_at < len(reference) and "A" <= reference[split_at] <= "Z":
        split_at += 1
    letters = reference[:split_at]
    digits = reference[split_at:]
    if (
        not letters
        or len(letters) > 3
        or not digits
        or not digits.isascii()
        or not digits.isdigit()
    ):
        return None
    column = 0
    for letter in letters:
        column = column * 26 + ord(letter) - ord("A") + 1
    row = int(digits)
    if not 1 <= column <= 16_384 or not 1 <= row <= 1_048_576:
        return None
    return row, column


def _dimension_extent(reference: object):
    if not isinstance(reference, str) or reference.count(":") > 1:
        return None
    first_reference, separator, last_reference = reference.partition(":")
    first = _cell_position(first_reference)
    last = _cell_position(last_reference if separator else first_reference)
    if first is None or last is None or first[0] > last[0] or first[1] > last[1]:
        return None
    return last


def _worksheet_metadata(content: bytes):
    drawing_id = None
    root_seen = False
    dimension_seen = False
    dimension_extent = None
    cells_are_bounded = True
    actual_max_row = 0
    actual_max_column = 0
    for event, element in _safe_xml_events(content):
        local = _local_name(element.tag)
        if event == "start" and not root_seen:
            root_seen = local == "worksheet"
            if not root_seen:
                raise _UnreadableWorkbookError()
        if event == "start" and local == "dimension":
            if dimension_seen:
                cells_are_bounded = False
            dimension_seen = True
            dimension_extent = _dimension_extent(element.attrib.get("ref"))
            if dimension_extent is None:
                cells_are_bounded = False
        if event == "start" and local == "c":
            position = _cell_position(element.attrib.get("r"))
            if position is None:
                cells_are_bounded = False
            else:
                actual_max_row = max(actual_max_row, position[0])
                actual_max_column = max(actual_max_column, position[1])
        if event == "start" and local == "drawing":
            if drawing_id is None:
                drawing_id = element.attrib.get(_RELATIONSHIP_ID_ATTRIBUTE)
                if not drawing_id:
                    raise _UnreadableWorkbookError()
        if event == "end":
            element.clear()
    if not root_seen:
        raise _UnreadableWorkbookError()
    if (
        not dimension_seen
        or dimension_extent is None
        or actual_max_row > dimension_extent[0]
        or actual_max_column > dimension_extent[1]
    ):
        cells_are_bounded = False
    cell_bound = (
        dimension_extent[0] * dimension_extent[1]
        if cells_are_bounded and dimension_extent is not None
        else None
    )
    return ((drawing_id,) if drawing_id is not None else ()), cell_bound


def _relationship_part(source_part: str) -> str:
    parent, _, name = source_part.rpartition("/")
    return f"{parent}/_rels/{name}.rels"


def _resolve_part(source_part: str, target: str, external: bool) -> str:
    try:
        return resolve_internal_relationship_target(
            source_part,
            target,
            external=external,
        )
    except OoxmlRelationshipError:
        raise _UnreadableWorkbookError() from None


def _worksheet_package_metadata(
    archive: zipfile.ZipFile,
    members,
    budget: _ActualByteBudget,
    max_worksheets: int,
) -> tuple[bool, ...]:
    content_types = _read_member(archive, members[_CONTENT_TYPES_PART], budget)
    if not _content_types_are_workbook(content_types):
        raise _UnreadableWorkbookError()
    content_types = b""

    workbook_xml = _read_member(archive, members[_WORKBOOK_PART], budget)
    relationship_ids = _workbook_sheet_relationship_ids(
        workbook_xml,
        max_worksheets,
    )
    workbook_xml = b""
    if _WORKBOOK_RELS_PART not in members:
        raise _UnreadableWorkbookError()
    rels_xml = _read_member(archive, members[_WORKBOOK_RELS_PART], budget)
    workbook_relationships = _relationships(rels_xml, relationship_ids)
    rels_xml = b""

    worksheet_parts = []
    for relationship_id in relationship_ids:
        relationship = workbook_relationships.get(relationship_id)
        if relationship is None:
            raise _UnreadableWorkbookError()
        relationship_type, target, external = relationship
        if external or relationship_type not in _WORKSHEET_RELATIONSHIP_TYPES:
            raise _UnreadableWorkbookError()
        worksheet_part = _resolve_part(_WORKBOOK_PART, target, external)
        if (
            not worksheet_part.startswith("xl/worksheets/")
            or not worksheet_part.endswith(".xml")
            or worksheet_part not in members
            or worksheet_part in worksheet_parts
        ):
            raise _UnreadableWorkbookError()
        worksheet_parts.append(worksheet_part)
    workbook_relationships.clear()

    metadata = []
    for worksheet_part in worksheet_parts:
        worksheet_xml = _read_member(archive, members[worksheet_part], budget)
        drawing_ids, cell_bound = _worksheet_metadata(worksheet_xml)
        worksheet_xml = b""
        if not drawing_ids:
            metadata.append((False, cell_bound))
            continue
        rels_part = _relationship_part(worksheet_part)
        if rels_part not in members:
            raise _UnreadableWorkbookError()
        sheet_rels_xml = _read_member(archive, members[rels_part], budget)
        sheet_relationships = _relationships(sheet_rels_xml, drawing_ids)
        sheet_rels_xml = b""
        for drawing_id in drawing_ids:
            relationship = sheet_relationships.get(drawing_id)
            if relationship is None:
                raise _UnreadableWorkbookError()
            relationship_type, target, external = relationship
            if external or relationship_type not in _DRAWING_RELATIONSHIP_TYPES:
                raise _UnreadableWorkbookError()
            drawing_part = _resolve_part(worksheet_part, target, external)
            if drawing_part not in members:
                raise _UnreadableWorkbookError()
            drawing_part = ""
        sheet_relationships.clear()
        metadata.append((True, cell_bound))
    worksheet_parts.clear()
    return tuple(metadata)


def _preflight(snapshot: bytes, limits: InspectionLimits):
    expected_entries = _validate_eocd(snapshot)
    try:
        with zipfile.ZipFile(BytesIO(snapshot), "r") as archive:
            members = _central_directory(archive, expected_entries)
            return _worksheet_package_metadata(
                archive,
                members,
                _ActualByteBudget(),
                limits.max_worksheets_per_workbook,
            )
    except (WorkbookParserBoundaryExceededError, WorkbookWorksheetCountExceededError):
        raise
    except (_UnreadableWorkbookError, _EncryptedWorkbookError):
        raise
    except Exception:
        raise _UnreadableWorkbookError() from None


def _private_scalar_text(value: object, character_limit: int):
    if value is None:
        return "", False
    if isinstance(value, str):
        text = value
    elif isinstance(value, (bool, int, float, date)):
        try:
            text = str(value)
        except Exception:
            return "", True
    else:
        return "", True
    if len(text) > character_limit:
        text = ""
        return "", True
    return text[:character_limit], False


def _canonical_signals(signal_set) -> tuple[str, ...]:
    return tuple(code for code in SIGNAL_ORDER if code in signal_set)


def _structural_signals(*, embedded_media: bool, worksheet_hidden: bool):
    signals = set()
    if embedded_media:
        signals.add("embedded-media-present")
    if worksheet_hidden:
        signals.add("worksheet-hidden")
    return _canonical_signals(signals)


def _unit_issues(
    *, over_limit: bool, embedded_media: bool, worksheet_hidden: bool
) -> tuple[str, ...]:
    issues = set()
    if over_limit:
        issues.add("unit-over-limit")
    if embedded_media:
        issues.add("embedded-media-present")
    if worksheet_hidden:
        issues.add("worksheet-hidden")
    return tuple(
        code
        for code in (
            "unit-over-limit",
            "embedded-media-present",
            "worksheet-hidden",
        )
        if code in issues
    )


def _worksheet_cell_bound(worksheet) -> int | None:
    max_row = worksheet.max_row
    max_column = worksheet.max_column
    if max_row is None or max_column is None:
        return None
    if (
        not isinstance(max_row, int)
        or isinstance(max_row, bool)
        or not isinstance(max_column, int)
        or isinstance(max_column, bool)
        or max_row < 0
        or max_column < 0
    ):
        raise _UnreadableWorkbookError()
    return max_row * max_column


def _inspect_worksheet(
    worksheet,
    unit_index: int,
    *,
    embedded_media: bool,
    expected_cell_bound: int | None,
    remaining_cells: int,
    character_limit: int,
):
    state = worksheet.sheet_state
    if state not in {"visible", "hidden", "veryHidden"}:
        raise _UnreadableWorkbookError()
    worksheet_hidden = state != "visible"
    runtime_cell_bound = _worksheet_cell_bound(worksheet)
    cell_bound = (
        runtime_cell_bound
        if expected_cell_bound is not None and runtime_cell_bound == expected_cell_bound
        else None
    )
    forced_over_limit = cell_bound is None or cell_bound > remaining_cells
    quota = (
        remaining_cells
        if cell_bound is not None and forced_over_limit
        else cell_bound
    )
    if quota is None:
        quota = 0
    consumed = 0
    text_signals = set()
    roster_heading_seen = False
    row_pattern = False
    scalar_over_limit = False

    if quota:
        for row in worksheet.iter_rows():
            if consumed >= quota:
                break
            populated_cells = 0
            row_signals = set()
            for cell in row:
                if consumed >= quota:
                    break
                consumed += 1
                private_text, truncated = _private_scalar_text(
                    cell.value,
                    character_limit,
                )
                if truncated:
                    scalar_over_limit = True
                    private_text = ""
                    break
                if private_text:
                    populated_cells += 1
                    cell_signals = signals_from_private_text(
                        private_text,
                        TextSignalContext(
                            "worksheet",
                            mostly_image=False,
                            embedded_media=False,
                            worksheet_hidden=False,
                            row_pattern=False,
                        ),
                    )
                    private_text = ""
                    row_signals.update(cell_signals)
            if scalar_over_limit:
                break
            if roster_heading_seen and populated_cells >= 2:
                row_pattern = True
            if "roster-column-pattern" in row_signals:
                roster_heading_seen = True
            text_signals.update(row_signals)

    over_limit = forced_over_limit or scalar_over_limit
    if over_limit:
        return (
            InspectionUnitEvidence(
                "worksheet",
                unit_index,
                "none",
                _structural_signals(
                    embedded_media=embedded_media,
                    worksheet_hidden=worksheet_hidden,
                ),
                _unit_issues(
                    over_limit=True,
                    embedded_media=embedded_media,
                    worksheet_hidden=worksheet_hidden,
                ),
            ),
            consumed,
        )

    structural_signals = signals_from_private_text(
        "",
        TextSignalContext(
            "worksheet",
            mostly_image=False,
            embedded_media=embedded_media,
            worksheet_hidden=worksheet_hidden,
            row_pattern=row_pattern,
        ),
    )
    text_signals.update(structural_signals)
    return (
        InspectionUnitEvidence(
            "worksheet",
            unit_index,
            "worksheet-structure",
            _canonical_signals(text_signals),
            _unit_issues(
                over_limit=False,
                embedded_media=embedded_media,
                worksheet_hidden=worksheet_hidden,
            ),
        ),
        consumed,
    )


def inspect_workbook(
    snapshot: bytes,
    *,
    limits: InspectionLimits,
) -> InspectionAdapterResult:
    """Inspect each actual worksheet from one immutable in-memory snapshot."""
    if type(snapshot) is not bytes:
        raise TypeError("inspection snapshot must be bytes")
    if type(limits) is not InspectionLimits:
        raise TypeError("inspection limits must be valid")
    if len(snapshot) > limits.max_workbook_source_bytes:
        return _source_problem("over-limit", "document-over-limit")
    if snapshot.startswith(_OLE_COMPOUND_HEADER):
        return _source_problem("encrypted", "document-encrypted")

    try:
        worksheet_metadata = _preflight(snapshot, limits)
    except (WorkbookParserBoundaryExceededError, WorkbookWorksheetCountExceededError):
        raise
    except _EncryptedWorkbookError:
        return _source_problem("encrypted", "document-encrypted")
    except Exception:
        return _source_problem("unreadable", "document-unreadable")

    workbook = None
    try:
        workbook = openpyxl.load_workbook(
            BytesIO(snapshot),
            read_only=True,
            data_only=False,
            keep_links=False,
        )
        worksheets = workbook.worksheets
        worksheet_count = len(worksheets)
        if worksheet_count > limits.max_worksheets_per_workbook:
            raise WorkbookWorksheetCountExceededError()
        if worksheet_count != len(worksheet_metadata):
            raise _UnreadableWorkbookError()

        units = []
        remaining_cells = limits.max_cells_per_workbook
        for unit_index, (worksheet, sheet_metadata) in enumerate(
            zip(worksheets, worksheet_metadata),
            start=1,
        ):
            embedded_media, expected_cell_bound = sheet_metadata
            try:
                worksheet_hidden = worksheet.sheet_state in {"hidden", "veryHidden"}
            except Exception:
                worksheet_hidden = False
            try:
                unit, consumed = _inspect_worksheet(
                    worksheet,
                    unit_index,
                    embedded_media=embedded_media,
                    expected_cell_bound=expected_cell_bound,
                    remaining_cells=remaining_cells,
                    character_limit=limits.max_cell_text_characters,
                )
            except Exception:
                unit = InspectionUnitEvidence(
                    "worksheet",
                    unit_index,
                    "none",
                    _structural_signals(
                        embedded_media=embedded_media,
                        worksheet_hidden=worksheet_hidden,
                    ),
                    _unit_issues(
                        over_limit=True,
                        embedded_media=embedded_media,
                        worksheet_hidden=worksheet_hidden,
                    ),
                )
                consumed = remaining_cells
            remaining_cells -= consumed
            units.append(unit)
        return InspectionAdapterResult(
            "inspected",
            worksheet_count,
            (),
            tuple(units),
        )
    except (WorkbookParserBoundaryExceededError, WorkbookWorksheetCountExceededError):
        raise
    except Exception:
        return _source_problem("unreadable", "document-unreadable")
    finally:
        if workbook is not None:
            try:
                workbook.close()
            except Exception:
                pass
