"""Bounded validation and loading for roster XLSX workbooks."""
from __future__ import annotations

import os
import re
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
import zipfile

import openpyxl


MAX_WORKBOOK_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 2_000
MAX_ARCHIVE_MEMBER_BYTES = 25 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 100 * 1024 * 1024
MAX_XML_BYTES = 16 * 1024 * 1024
MAX_WORKSHEET_ROWS = 10_000
MAX_WORKSHEET_COLUMNS = 128
MAX_WORKSHEET_CELLS = 500_000
MAX_STRING_CHARACTERS = 32_767

_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_CELL_REF_RE = re.compile(r"^\$?([A-Za-z]{1,3})\$?([1-9][0-9]*)$")


class RosterWorkbookError(ValueError):
    """Raised when a roster workbook is malformed or exceeds a safety limit."""


class _ByteBudget:
    def __init__(self, limit: int):
        self._remaining = limit

    @property
    def remaining(self) -> int:
        return self._remaining

    def consume(self, size: int) -> None:
        if size > self._remaining:
            raise RosterWorkbookError("archive-uncompressed-too-large")
        self._remaining -= size


class _BoundedReader:
    def __init__(
        self,
        stream,
        member_limit: int,
        byte_budget: _ByteBudget,
    ):
        self._stream = stream
        self._member_limit = member_limit
        self._byte_budget = byte_budget
        self._read = 0

    def read(self, size: int = -1) -> bytes:
        member_remaining = self._member_limit - self._read
        requested = (
            member_remaining + 1
            if size is None or size < 0
            else min(size, member_remaining + 1)
        )
        requested = min(requested, self._byte_budget.remaining + 1)
        content = self._stream.read(requested)
        if len(content) > member_remaining:
            raise RosterWorkbookError("xml-too-large")
        self._byte_budget.consume(len(content))
        self._read += len(content)
        return content

    def close(self) -> None:
        self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def load_roster_rows(xlsx_source) -> list[list]:
    """Preflight an XLSX, then load its active worksheet within those bounds."""
    preflight_roster_workbook(xlsx_source)
    _seek_start(xlsx_source)
    workbook = openpyxl.load_workbook(
        xlsx_source,
        read_only=True,
        data_only=True,
    )
    try:
        worksheet = workbook.active
        return [list(row) for row in worksheet.iter_rows(values_only=True)]
    finally:
        workbook.close()
        _seek_start(xlsx_source)


def preflight_roster_workbook(xlsx_source) -> None:
    """Stream-validate the workbook container and XML before OpenPyXL runs."""
    original_position = _position(xlsx_source)
    try:
        if _source_size(xlsx_source) > MAX_WORKBOOK_BYTES:
            raise RosterWorkbookError("workbook-too-large")
        _seek_start(xlsx_source)
        with zipfile.ZipFile(xlsx_source) as archive:
            members = _validate_archive(archive)
            required = {"[Content_Types].xml", "xl/workbook.xml"}
            if not required.issubset(members):
                raise RosterWorkbookError("missing-required-part")
            worksheets = [
                name
                for name in members
                if name.startswith("xl/worksheets/")
                and name.endswith(".xml")
                and "/" not in name.removeprefix("xl/worksheets/")
            ]
            if not worksheets:
                raise RosterWorkbookError("missing-worksheet")
            budget = _ByteBudget(MAX_ARCHIVE_UNCOMPRESSED_BYTES)
            for name in sorted(members):
                if name.endswith((".xml", ".rels")):
                    _stream_xml(
                        archive,
                        name,
                        budget,
                        worksheet=name in worksheets,
                    )
    except RosterWorkbookError:
        raise
    except (
        ET.ParseError,
        KeyError,
        OSError,
        ValueError,
        zipfile.BadZipFile,
        zipfile.LargeZipFile,
    ) as error:
        raise RosterWorkbookError("invalid-workbook") from error
    finally:
        _restore_position(xlsx_source, original_position)


def _validate_archive(archive: zipfile.ZipFile) -> set[str]:
    infos = archive.infolist()
    if len(infos) > MAX_ARCHIVE_MEMBERS:
        raise RosterWorkbookError("archive-member-limit")
    names: set[str] = set()
    total_uncompressed = 0
    for info in infos:
        if info.filename in names:
            raise RosterWorkbookError("duplicate-archive-member")
        names.add(info.filename)
        path = PurePosixPath(info.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in info.filename:
            raise RosterWorkbookError("invalid-archive-member")
        if info.flag_bits & 0x1:
            raise RosterWorkbookError("encrypted-entry")
        if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise RosterWorkbookError("archive-member-too-large")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise RosterWorkbookError("archive-uncompressed-too-large")
    return names


def _stream_xml(
    archive: zipfile.ZipFile,
    member: str,
    byte_budget: _ByteBudget,
    *,
    worksheet: bool,
) -> None:
    info = archive.getinfo(member)
    if info.file_size > MAX_XML_BYTES:
        raise RosterWorkbookError("xml-too-large")
    row_count = 0
    cell_count = 0
    string_characters = 0
    string_depth = 0
    with _BoundedReader(
        archive.open(info),
        MAX_XML_BYTES,
        byte_budget,
    ) as stream:
        for event, element in ET.iterparse(stream, events=("start", "end")):
            if event == "start":
                if element.tag in {f"{_SHEET_NS}si", f"{_SHEET_NS}is"}:
                    string_depth += 1
                    string_characters = 0
                continue
            text = element.text or ""
            if len(text) > MAX_STRING_CHARACTERS:
                raise RosterWorkbookError("string-too-large")
            if string_depth and element.tag == f"{_SHEET_NS}t":
                string_characters += len(text)
                if string_characters > MAX_STRING_CHARACTERS:
                    raise RosterWorkbookError("string-too-large")
            if element.tag in {f"{_SHEET_NS}si", f"{_SHEET_NS}is"}:
                string_depth -= 1
                string_characters = 0
            if worksheet:
                if element.tag == f"{_SHEET_NS}dimension":
                    _validate_dimension(element.attrib.get("ref", ""))
                elif element.tag == f"{_SHEET_NS}row":
                    row_count += 1
                    if row_count > MAX_WORKSHEET_ROWS:
                        raise RosterWorkbookError("worksheet-row-limit")
                    row_reference = element.attrib.get("r")
                    if row_reference:
                        _validate_row_number(row_reference)
                elif element.tag == f"{_SHEET_NS}c":
                    cell_count += 1
                    if cell_count > MAX_WORKSHEET_CELLS:
                        raise RosterWorkbookError("worksheet-cell-limit")
                    cell_reference = element.attrib.get("r")
                    if cell_reference:
                        _validate_cell_reference(cell_reference)
            element.clear()


def _validate_dimension(reference: str) -> None:
    if not reference:
        raise RosterWorkbookError("invalid-worksheet-dimension")
    endpoints = reference.split(":")
    if len(endpoints) not in {1, 2}:
        raise RosterWorkbookError("invalid-worksheet-dimension")
    start_column, start_row = _parse_cell_reference(endpoints[0])
    end_column, end_row = _parse_cell_reference(endpoints[-1])
    if end_column < start_column or end_row < start_row:
        raise RosterWorkbookError("invalid-worksheet-dimension")
    _validate_grid_bounds(end_row, end_column)
    if (end_row - start_row + 1) * (end_column - start_column + 1) > MAX_WORKSHEET_CELLS:
        raise RosterWorkbookError("worksheet-cell-limit")


def _validate_row_number(reference: str) -> None:
    try:
        row = int(reference)
    except ValueError as error:
        raise RosterWorkbookError("invalid-row-reference") from error
    if row < 1 or row > MAX_WORKSHEET_ROWS:
        raise RosterWorkbookError("worksheet-row-limit")


def _validate_cell_reference(reference: str) -> None:
    column, row = _parse_cell_reference(reference)
    _validate_grid_bounds(row, column)


def _parse_cell_reference(reference: str) -> tuple[int, int]:
    match = _CELL_REF_RE.fullmatch(reference)
    if match is None:
        raise RosterWorkbookError("invalid-cell-reference")
    column = 0
    for character in match.group(1).upper():
        column = column * 26 + ord(character) - ord("A") + 1
    return column, int(match.group(2))


def _validate_grid_bounds(row: int, column: int) -> None:
    if row > MAX_WORKSHEET_ROWS:
        raise RosterWorkbookError("worksheet-row-limit")
    if column > MAX_WORKSHEET_COLUMNS:
        raise RosterWorkbookError("worksheet-column-limit")


def _position(source) -> int | None:
    if isinstance(source, (str, bytes, os.PathLike)):
        return None
    return source.tell()


def _source_size(source) -> int:
    if isinstance(source, (str, bytes, os.PathLike)):
        return os.path.getsize(source)
    position = source.tell()
    source.seek(0, os.SEEK_END)
    size = source.tell()
    source.seek(position)
    return size


def _seek_start(source) -> None:
    if not isinstance(source, (str, bytes, os.PathLike)):
        source.seek(0)


def _restore_position(source, position: int | None) -> None:
    if position is not None:
        source.seek(position)
