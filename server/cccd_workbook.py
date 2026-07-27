"""Safe, relationship-driven extraction of embedded workbook drawings."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
import posixpath
from pathlib import PurePosixPath
import zipfile
from xml.etree import ElementTree as ET
import zlib


MAX_WORKBOOK_BYTES = 100 * 1024 * 1024
MAX_DRAWINGS = 500
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_TOTAL_IMAGE_BYTES = 500 * 1024 * 1024
MAX_PIXELS = 40_000_000


class CccdWorkbookError(ValueError):
    """Raised when a workbook exceeds a hard extraction safety limit."""


@dataclass(frozen=True)
class Anchor:
    sheet: str
    from_row: int
    from_col: int
    to_row: int
    to_col: int


@dataclass(frozen=True)
class EmbeddedDrawing:
    id: str
    anchor: Anchor
    media_type: str
    extension: str
    width: int
    height: int
    sha256: str
    stored_path: str


@dataclass(frozen=True)
class ExtractionIssue:
    code: str
    drawing_id: str | None


@dataclass(frozen=True)
class ExtractionResult:
    drawing_instances: int
    drawings: list[EmbeddedDrawing]
    issues: list[ExtractionIssue]


_REL_NS = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_SHEET_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_DRAWING_NS = "{http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing}"
_DOC_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_DRAWING_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
_IMAGE_REL_TYPE = "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"


def extract_drawings(xlsx_path: str, output_dir: str) -> ExtractionResult:
    """Extract PNG/JPEG drawings in workbook and worksheet relationship order."""
    if os.path.getsize(xlsx_path) > MAX_WORKBOOK_BYTES:
        raise CccdWorkbookError("workbook-too-large")
    with zipfile.ZipFile(xlsx_path) as archive:
        _reject_encrypted_entries(archive)
        sheet_parts = _worksheet_parts_in_workbook_order(archive)
        records = []
        issues = []
        drawing_instances = 0
        for sheet_name, sheet_part in sheet_parts:
            for drawing_part in _drawing_parts_for_sheet(archive, sheet_part):
                try:
                    drawing_records, drawing_issues, instance_count = _drawing_records(
                        archive,
                        sheet_name,
                        drawing_part,
                        drawing_instances + 1,
                        MAX_DRAWINGS - drawing_instances,
                    )
                except ET.ParseError:
                    issues.append(ExtractionIssue("malformed-drawing", None))
                    continue
                drawing_instances += instance_count
                records.extend(drawing_records)
                issues.extend(drawing_issues)
        return _decode_and_store(
            archive, records, issues, drawing_instances, output_dir
        )


def _worksheet_parts_in_workbook_order(archive):
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = _relationships(archive, "xl/workbook.xml")
    parts = []
    for sheet in workbook.findall(f".//{_SHEET_NS}sheet"):
        target = _resolve_relationship_target(
            "xl/workbook.xml", rels[sheet.attrib[f"{_DOC_REL_NS}id"]]
        )
        parts.append((sheet.attrib["name"], target))
    return parts


def _drawing_parts_for_sheet(archive, sheet_part):
    sheet = ET.fromstring(archive.read(sheet_part))
    rels = _relationships(archive, sheet_part)
    parts = []
    for drawing in sheet.findall(f".//{_SHEET_NS}drawing"):
        rel = rels[drawing.attrib[f"{_DOC_REL_NS}id"]]
        if rel["type"] == _DRAWING_REL_TYPE:
            parts.append(_resolve_relationship_target(sheet_part, rel))
    return parts


def _drawing_records(archive, sheet_name, drawing_part, next_id, remaining_capacity):
    rels = _relationships(archive, drawing_part)
    records = []
    issues = []
    instance_count = 0
    with archive.open(drawing_part) as drawing_stream:
        for _, element in ET.iterparse(drawing_stream, events=("end",)):
            if element.tag != f"{_DRAWING_NS}twoCellAnchor":
                continue
            instance_count += 1
            if instance_count > remaining_capacity:
                raise CccdWorkbookError("drawing-limit")
            drawing_id = f"drawing-{next_id + instance_count - 1:04d}"
            try:
                anchor = Anchor(
                    sheet_name,
                    _anchor_value(element, "from", "row"),
                    _anchor_value(element, "from", "col"),
                    _anchor_value(element, "to", "row"),
                    _anchor_value(element, "to", "col"),
                )
            except (AttributeError, TypeError, ValueError):
                issues.append(ExtractionIssue("malformed-drawing", drawing_id))
                element.clear()
                continue
            blip = element.find(f".//{{http://schemas.openxmlformats.org/drawingml/2006/main}}blip")
            if blip is None:
                issues.append(ExtractionIssue("malformed-drawing", drawing_id))
                element.clear()
                continue
            embed = blip.attrib.get(f"{_DOC_REL_NS}embed")
            rel = rels.get(embed)
            if not rel or rel["type"] != _IMAGE_REL_TYPE:
                issues.append(ExtractionIssue("malformed-drawing", drawing_id))
                element.clear()
                continue
            try:
                media_part = _resolve_relationship_target(drawing_part, rel)
            except CccdWorkbookError as error:
                issues.append(ExtractionIssue(str(error), drawing_id))
                element.clear()
                continue
            records.append((drawing_id, anchor, media_part))
            element.clear()
    return records, issues, instance_count


def _anchor_value(element, side, value):
    node = element.find(f"{_DRAWING_NS}{side}/{_DRAWING_NS}{value}")
    return int(node.text)


def _decode_and_store(archive, records, issues, drawing_instances, output_dir):
    if drawing_instances > MAX_DRAWINGS:
        raise CccdWorkbookError("drawing-limit")
    os.makedirs(output_dir, exist_ok=True)
    drawings = []
    total_image_bytes = 0
    for drawing_id, anchor, media_part in records:
        extension = _extension_for(media_part)
        if extension not in {"png", "jpg"}:
            issues.append(ExtractionIssue("unsupported-media", drawing_id))
            continue
        info = archive.getinfo(media_part)
        if info.file_size > MAX_IMAGE_BYTES:
            raise CccdWorkbookError("image-too-large")
        if total_image_bytes + info.file_size > MAX_TOTAL_IMAGE_BYTES:
            raise CccdWorkbookError("total-image-too-large")
        content = archive.read(media_part)
        if len(content) > MAX_IMAGE_BYTES:
            raise CccdWorkbookError("image-too-large")
        total_image_bytes += len(content)
        try:
            width, height = _image_size(content, extension)
        except ValueError:
            issues.append(ExtractionIssue("unsupported-media", drawing_id))
            continue
        if width * height > MAX_PIXELS:
            raise CccdWorkbookError("pixel-limit")
        stored_path = os.path.join(output_dir, f"{drawing_id}.{extension}")
        with open(stored_path, "wb") as stored:
            stored.write(content)
        drawings.append(EmbeddedDrawing(
            id=drawing_id,
            anchor=anchor,
            media_type={"png": "image/png", "jpg": "image/jpeg"}[extension],
            extension=extension,
            width=width,
            height=height,
            sha256=hashlib.sha256(content).hexdigest(),
            stored_path=stored_path,
        ))
    return ExtractionResult(drawing_instances, drawings, issues)


def _relationships(archive, source_part):
    path = PurePosixPath(source_part)
    rels_part = str(path.parent / "_rels" / f"{path.name}.rels")
    root = ET.fromstring(archive.read(rels_part))
    result = {}
    for rel in root.findall(f"{_REL_NS}Relationship"):
        result[rel.attrib["Id"]] = {
            "type": rel.attrib["Type"],
            "target": rel.attrib["Target"],
            "external": rel.attrib.get("TargetMode") == "External",
        }
    return result


def _resolve_relationship_target(source_part, relationship):
    if relationship["external"]:
        raise CccdWorkbookError("external-relationship")
    target = relationship["target"]
    if target.startswith("/"):
        raise CccdWorkbookError("invalid-target")
    candidate = str(PurePosixPath(source_part).parent / target)
    normalized = PurePosixPath(posixpath.normpath(candidate))
    if normalized.is_absolute() or ".." in normalized.parts:
        raise CccdWorkbookError("invalid-target")
    return str(normalized)


def _extension_for(media_part):
    extension = PurePosixPath(media_part).suffix.lower().lstrip(".")
    return "jpg" if extension == "jpeg" else extension


def _image_size(content, extension):
    if extension == "png":
        return _png_size(content)
    if extension == "jpg" and content.startswith(b"\xff\xd8"):
        return _jpeg_size(content)
    raise ValueError("unsupported image bytes")


def _png_size(content):
    if not content.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("invalid png signature")
    offset = 8
    width = height = None
    idat_chunks = []
    while offset < len(content):
        if offset + 12 > len(content):
            raise ValueError("truncated png chunk")
        length = int.from_bytes(content[offset:offset + 4], "big")
        chunk_type = content[offset + 4:offset + 8]
        data_start = offset + 8
        data_end = data_start + length
        crc_end = data_end + 4
        if crc_end > len(content):
            raise ValueError("truncated png chunk")
        data = content[data_start:data_end]
        expected_crc = int.from_bytes(content[data_end:crc_end], "big")
        if (zlib.crc32(chunk_type + data) & 0xFFFFFFFF) != expected_crc:
            raise ValueError("invalid png crc")
        if width is None:
            if chunk_type != b"IHDR" or length != 13:
                raise ValueError("missing png header")
            width = int.from_bytes(data[0:4], "big")
            height = int.from_bytes(data[4:8], "big")
            if width == 0 or height == 0:
                raise ValueError("invalid png dimensions")
        elif chunk_type == b"IDAT":
            idat_chunks.append(data)
        elif chunk_type == b"IEND":
            if length != 0 or not idat_chunks or crc_end != len(content):
                raise ValueError("invalid png termination")
            zlib.decompress(b"".join(idat_chunks))
            return width, height
        offset = crc_end
    raise ValueError("missing png termination")


def _jpeg_size(content):
    offset = 2
    while offset + 9 < len(content):
        if content[offset] != 0xFF:
            raise ValueError("invalid jpeg marker")
        while offset < len(content) and content[offset] == 0xFF:
            offset += 1
        marker = content[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(content):
            break
        length = int.from_bytes(content[offset:offset + 2], "big")
        if length < 2 or offset + length > len(content):
            break
        if 0xC0 <= marker <= 0xC3 or 0xC5 <= marker <= 0xC7 or 0xC9 <= marker <= 0xCB or 0xCD <= marker <= 0xCF:
            return (
                int.from_bytes(content[offset + 3:offset + 5], "big"),
                int.from_bytes(content[offset + 5:offset + 7], "big"),
            )
        offset += length
    raise ValueError("missing jpeg dimensions")


def _reject_encrypted_entries(archive):
    if any(info.flag_bits & 0x1 for info in archive.infolist()):
        raise CccdWorkbookError("encrypted-entry")
