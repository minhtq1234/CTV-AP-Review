"""Safe, relationship-driven extraction of embedded workbook drawings."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import PurePosixPath
import zipfile
from xml.etree import ElementTree as ET
import zlib

from ooxml import OoxmlRelationshipError, resolve_internal_relationship_target


MAX_WORKBOOK_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_MEMBERS = 10_000
MAX_ARCHIVE_MEMBER_BYTES = 100 * 1024 * 1024
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 600 * 1024 * 1024
MAX_XML_BYTES = 10 * 1024 * 1024
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
    from_row_offset: int = 0
    from_col_offset: int = 0
    to_row_offset: int = 0
    to_col_offset: int = 0


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
# Excel anchors a picture either across a cell range (twoCellAnchor) or at a
# single origin with a pixel extent (oneCellAnchor). Real CCCD workbooks use
# both -- exports converted by some tools emit only the latter.
_ANCHOR_TAGS = (
    f"{_DRAWING_NS}twoCellAnchor",
    f"{_DRAWING_NS}oneCellAnchor",
)
_DOC_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_DRAWING_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing"
)
_IMAGE_REL_TYPE = (
    "http://schemas.openxmlformats.org/officeDocument/2006/relationships/image"
)


def extract_drawings(xlsx_path: str, output_dir: str) -> ExtractionResult:
    """Extract PNG/JPEG drawings in workbook and worksheet relationship order."""
    if os.path.getsize(xlsx_path) > MAX_WORKBOOK_BYTES:
        raise CccdWorkbookError("workbook-too-large")
    with zipfile.ZipFile(xlsx_path) as archive:
        _validate_archive(archive)
        byte_budget = _ExtractionByteBudget(MAX_ARCHIVE_UNCOMPRESSED_BYTES)
        sheet_parts = _worksheet_parts_in_workbook_order(archive, byte_budget)
        records = []
        issues = []
        drawing_instances = 0
        for sheet_name, sheet_part in sheet_parts:
            for drawing_part in _drawing_parts_for_sheet(
                archive, sheet_part, byte_budget
            ):
                try:
                    drawing_records, drawing_issues, instance_count = _drawing_records(
                        archive,
                        sheet_name,
                        drawing_part,
                        drawing_instances + 1,
                        MAX_DRAWINGS - drawing_instances,
                        byte_budget,
                    )
                except ET.ParseError:
                    issues.append(ExtractionIssue("malformed-drawing", None))
                    continue
                drawing_instances += instance_count
                records.extend(drawing_records)
                issues.extend(drawing_issues)
        return _decode_and_store(
            archive, records, issues, drawing_instances, output_dir, byte_budget
        )


def _worksheet_parts_in_workbook_order(archive, byte_budget):
    workbook = _parse_xml(archive, "xl/workbook.xml", byte_budget)
    rels = _relationships(archive, "xl/workbook.xml", byte_budget)
    parts = []
    for sheet in workbook.findall(f".//{_SHEET_NS}sheet"):
        target = _resolve_relationship_target(
            "xl/workbook.xml", rels[sheet.attrib[f"{_DOC_REL_NS}id"]]
        )
        parts.append((sheet.attrib["name"], target))
    return parts


def _drawing_parts_for_sheet(archive, sheet_part, byte_budget):
    sheet = _parse_xml(archive, sheet_part, byte_budget)
    rels = _relationships(archive, sheet_part, byte_budget)
    parts = []
    for drawing in sheet.findall(f".//{_SHEET_NS}drawing"):
        rel = rels[drawing.attrib[f"{_DOC_REL_NS}id"]]
        if rel["type"] == _DRAWING_REL_TYPE:
            parts.append(_resolve_relationship_target(sheet_part, rel))
    return parts


def _drawing_records(
    archive,
    sheet_name,
    drawing_part,
    next_id,
    remaining_capacity,
    byte_budget,
):
    rels = _relationships(archive, drawing_part, byte_budget)
    records = []
    issues = []
    instance_count = 0
    with _bounded_member_reader(
        archive,
        drawing_part,
        MAX_XML_BYTES,
        "xml-too-large",
        byte_budget,
    ) as drawing_stream:
        for _, element in ET.iterparse(drawing_stream, events=("end",)):
            if element.tag not in _ANCHOR_TAGS:
                continue
            one_cell = element.tag == f"{_DRAWING_NS}oneCellAnchor"
            instance_count += 1
            if instance_count > remaining_capacity:
                raise CccdWorkbookError("drawing-limit")
            drawing_id = f"drawing-{next_id + instance_count - 1:04d}"
            try:
                from_row = _anchor_value(element, "from", "row")
                from_col = _anchor_value(element, "from", "col")
                anchor = Anchor(
                    sheet_name,
                    from_row,
                    from_col,
                    # A oneCellAnchor pins an origin plus a pixel extent and has
                    # no "to" cell at all. Treat it as spanning its own cell so
                    # the spatial front/back pairing still gets a comparable
                    # box; the offsets that would describe the extent in EMU are
                    # not convertible to rows/cols without column widths.
                    from_row + 1 if one_cell else _anchor_value(
                        element, "to", "row"
                    ),
                    from_col + 1 if one_cell else _anchor_value(
                        element, "to", "col"
                    ),
                    from_row_offset=_anchor_value(
                        element, "from", "rowOff", default=0
                    ),
                    from_col_offset=_anchor_value(
                        element, "from", "colOff", default=0
                    ),
                    to_row_offset=0 if one_cell else _anchor_value(
                        element, "to", "rowOff", default=0
                    ),
                    to_col_offset=0 if one_cell else _anchor_value(
                        element, "to", "colOff", default=0
                    ),
                )
            except (AttributeError, TypeError, ValueError):
                issues.append(ExtractionIssue("malformed-drawing", drawing_id))
                element.clear()
                continue
            blip = element.find(
                ".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip"
            )
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


def _anchor_value(element, side, value, *, default=None):
    node = element.find(f"{_DRAWING_NS}{side}/{_DRAWING_NS}{value}")
    if node is None or node.text is None:
        if default is not None:
            return default
        raise ValueError(f"missing anchor {side}.{value}")
    return int(node.text)


def _decode_and_store(
    archive,
    records,
    issues,
    drawing_instances,
    output_dir,
    byte_budget,
):
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
        content = _read_member_bytes(
            archive,
            media_part,
            MAX_IMAGE_BYTES,
            "image-too-large",
            byte_budget,
        )
        total_image_bytes += len(content)
        try:
            width, height = _image_size(content, extension)
        except CccdWorkbookError:
            raise
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


def _relationships(archive, source_part, byte_budget):
    path = PurePosixPath(source_part)
    rels_part = str(path.parent / "_rels" / f"{path.name}.rels")
    root = _parse_xml(archive, rels_part, byte_budget)
    result = {}
    for rel in root.findall(f"{_REL_NS}Relationship"):
        result[rel.attrib["Id"]] = {
            "type": rel.attrib["Type"],
            "target": rel.attrib["Target"],
            "external": rel.attrib.get("TargetMode") == "External",
        }
    return result


def _resolve_relationship_target(source_part, relationship):
    try:
        return resolve_internal_relationship_target(
            source_part,
            relationship["target"],
            external=relationship["external"],
        )
    except OoxmlRelationshipError as error:
        raise CccdWorkbookError(str(error)) from error


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
    expected_scanline_bytes = None
    decoded_scanline_bytes = 0
    decompressor = None
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
            if width * height > MAX_PIXELS:
                raise CccdWorkbookError("pixel-limit")
            expected_scanline_bytes = _png_scanline_payload_size(
                width, height, data[8], data[9], data[10], data[11], data[12]
            )
            decompressor = zlib.decompressobj()
        elif chunk_type == b"IDAT":
            decoded_scanline_bytes = _decompress_png_idat(
                decompressor, data, decoded_scanline_bytes, expected_scanline_bytes
            )
        elif chunk_type == b"IEND":
            if (
                length != 0
                or decompressor is None
                or not decompressor.eof
                or decoded_scanline_bytes != expected_scanline_bytes
                or crc_end != len(content)
            ):
                raise ValueError("invalid png termination")
            return width, height
        offset = crc_end
    raise ValueError("missing png termination")


def _png_scanline_payload_size(
    width,
    height,
    bit_depth,
    color_type,
    compression,
    image_filter,
    interlace,
):
    channels_by_color_type = {
        0: 1,
        2: 3,
        3: 1,
        4: 2,
        6: 4,
    }
    allowed_bit_depths = {
        0: {1, 2, 4, 8, 16},
        2: {8, 16},
        3: {1, 2, 4, 8},
        4: {8, 16},
        6: {8, 16},
    }
    if (
        color_type not in channels_by_color_type
        or bit_depth not in allowed_bit_depths[color_type]
        or compression != 0
        or image_filter != 0
        or interlace not in {0, 1}
    ):
        raise ValueError("invalid png header")
    bits_per_pixel = channels_by_color_type[color_type] * bit_depth

    def pass_size(pass_width, pass_height):
        if pass_width <= 0 or pass_height <= 0:
            return 0
        row_bytes = (pass_width * bits_per_pixel + 7) // 8
        return pass_height * (row_bytes + 1)

    if interlace == 0:
        return pass_size(width, height)

    adam7 = (
        (0, 0, 8, 8),
        (4, 0, 8, 8),
        (0, 4, 4, 8),
        (2, 0, 4, 4),
        (0, 2, 2, 4),
        (1, 0, 2, 2),
        (0, 1, 1, 2),
    )
    return sum(
        pass_size(
            (width - start_x + step_x - 1) // step_x if width > start_x else 0,
            (height - start_y + step_y - 1) // step_y if height > start_y else 0,
        )
        for start_x, start_y, step_x, step_y in adam7
    )


def _decompress_png_idat(decompressor, data, decoded_size, expected_size):
    pending = data
    while pending:
        previous_pending_size = len(pending)
        try:
            output = decompressor.decompress(
                pending,
                min(64 * 1024, expected_size - decoded_size + 1),
            )
        except zlib.error as error:
            raise ValueError("invalid png compressed data") from error
        decoded_size += len(output)
        if decoded_size > expected_size or decompressor.unused_data:
            raise ValueError("invalid png scanline payload")
        pending = decompressor.unconsumed_tail
        if pending and len(pending) == previous_pending_size and not output:
            raise ValueError("invalid png compressed data")
    return decoded_size


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
        if (
            0xC0 <= marker <= 0xC3
            or 0xC5 <= marker <= 0xC7
            or 0xC9 <= marker <= 0xCB
            or 0xCD <= marker <= 0xCF
        ):
            return (
                int.from_bytes(content[offset + 3:offset + 5], "big"),
                int.from_bytes(content[offset + 5:offset + 7], "big"),
            )
        offset += length
    raise ValueError("missing jpeg dimensions")


def _reject_encrypted_entries(archive):
    if any(info.flag_bits & 0x1 for info in archive.infolist()):
        raise CccdWorkbookError("encrypted-entry")


def _validate_archive(archive):
    entries = archive.infolist()
    if len(entries) > MAX_ARCHIVE_MEMBERS:
        raise CccdWorkbookError("archive-member-limit")
    total_uncompressed = 0
    for info in entries:
        if info.file_size > MAX_ARCHIVE_MEMBER_BYTES:
            raise CccdWorkbookError("archive-member-too-large")
        total_uncompressed += info.file_size
        if total_uncompressed > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
            raise CccdWorkbookError("archive-uncompressed-too-large")
    _reject_encrypted_entries(archive)


class _ExtractionByteBudget:
    """Bound the total bytes streamed across all ZIP member reads."""

    def __init__(self, limit):
        self._limit = limit
        self._read = 0

    @property
    def remaining(self):
        return self._limit - self._read

    def consume(self, size):
        if size > self.remaining:
            raise CccdWorkbookError("archive-uncompressed-too-large")
        self._read += size


class _BoundedMemberReader:
    """Read one ZIP member without trusting its declared uncompressed size."""

    def __init__(self, stream, limit, error_code, byte_budget):
        self._stream = stream
        self._limit = limit
        self._error_code = error_code
        self._byte_budget = byte_budget
        self._read = 0

    def read(self, size=-1):
        remaining = self._limit - self._read
        requested = (
            remaining + 1
            if size is None or size < 0
            else min(size, remaining + 1)
        )
        request_size = min(requested, self._byte_budget.remaining + 1)
        content = self._stream.read(request_size)
        if len(content) > remaining:
            raise CccdWorkbookError(self._error_code)
        self._byte_budget.consume(len(content))
        self._read += len(content)
        return content

    def close(self):
        self._stream.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def _bounded_member_reader(archive, member, limit, error_code, byte_budget):
    info = archive.getinfo(member)
    if info.file_size > limit:
        raise CccdWorkbookError(error_code)
    return _BoundedMemberReader(
        archive.open(info),
        limit,
        error_code,
        byte_budget,
    )


def _parse_xml(archive, member, byte_budget):
    with _bounded_member_reader(
        archive,
        member,
        MAX_XML_BYTES,
        "xml-too-large",
        byte_budget,
    ) as stream:
        return ET.parse(stream).getroot()


def _read_member_bytes(archive, member, limit, error_code, byte_budget):
    chunks = []
    with _bounded_member_reader(
        archive,
        member,
        limit,
        error_code,
        byte_budget,
    ) as stream:
        while True:
            chunk = stream.read(64 * 1024)
            if not chunk:
                return b"".join(chunks)
            chunks.append(chunk)
