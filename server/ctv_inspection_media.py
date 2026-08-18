"""Bounded, byte-only PDF page and standalone-image inspection adapters."""
from __future__ import annotations

from io import BytesIO
import math
import re
import warnings
import zlib

import fitz
from PIL import Image, ImageOps

from ctv_inspection_classifier import TextSignalContext, signals_from_private_text
from ctv_inspection_model import (
    DEFAULT_INSPECTION_LIMITS,
    InspectionAdapterResult,
    InspectionLimits,
    InspectionUnitCountExceededError,
    InspectionUnitEvidence,
)
from ctv_local_ocr import OcrBudget, OcrOutcome


_PDF_DPI = 150
_OCR_IMAGE_BYTES = 25 * 1024 * 1024
_ALPHABETIC_TOKEN = re.compile(r"[^\W\d_]+", re.UNICODE)
_OCR_ISSUES = {
    "unavailable": "ocr-unavailable",
    "timeout": "ocr-timeout",
    "failed": "ocr-failed",
    "low-confidence": "ocr-low-confidence",
    "over-limit": "unit-over-limit",
}
_OCR_STATUSES = (
    "succeeded",
    "unavailable",
    "timeout",
    "failed",
    "low-confidence",
    "over-limit",
)
_MAX_CONTENT_STREAMS_PER_PAGE = 256
_MAX_RESOURCE_RECORDS_PER_PAGE = 256
_MAX_RAW_RESOURCE_BYTES_PER_PAGE = 25 * 1024 * 1024
_MAX_PAGE_TREE_PARENT_DEPTH = 32


class _OutputLimitExceeded(RuntimeError):
    pass


class PrivateTextSinkFailure(RuntimeError):
    def __init__(self) -> None:
        super().__init__("inspection-private-text-sink-failed")


def _capture_private_text(sink, unit_kind: str, unit_index: int, text: str) -> None:
    if sink is None:
        return
    try:
        sink(unit_kind, unit_index, text)
    except Exception:
        raise PrivateTextSinkFailure() from None


class _CappedBytesIO(BytesIO):
    def __init__(self, limit: int) -> None:
        super().__init__()
        self.limit = limit
        self.crossed = False

    def write(self, value: bytes) -> int:
        if self.crossed:
            return len(value)
        end = self.tell() + len(value)
        if end > self.limit:
            self.crossed = True
            raise _OutputLimitExceeded()
        return super().write(value)
_MAX_XREF_DIGITS = 10
_MAX_XREF_REFERENCE_CHARS = 32
_MAX_PDF_METADATA_CHARS = 64 * 1024
_MAX_PDF_METADATA_TOKENS = 4_096
_MAX_PDF_METADATA_DEPTH = 8
_MAX_PDF_NAME_CHARS = 128
_MAX_PDF_OBJECT_CHARS = 2_048
_STANDARD_TYPE1_FONTS = frozenset(
    {
        "Courier",
        "Courier-Bold",
        "Courier-BoldOblique",
        "Courier-Oblique",
        "Helvetica",
        "Helvetica-Bold",
        "Helvetica-BoldOblique",
        "Helvetica-Oblique",
        "Symbol",
        "Times-Bold",
        "Times-BoldItalic",
        "Times-Italic",
        "Times-Roman",
        "ZapfDingbats",
    }
)
_SAFE_RESOURCE_KEYS = frozenset(
    {"ColorSpace", "ExtGState", "Font", "ProcSet", "XObject"}
)
_SAFE_PROCSET_NAMES = frozenset(
    {"/PDF", "/Text", "/ImageB", "/ImageC", "/ImageI"}
)
_SAFE_IMAGE_FILTERS = frozenset({"/DCTDecode", "/FlateDecode"})
_DEVICE_COLOR_SPACES = frozenset({"/DeviceGray", "/DeviceRGB", "/DeviceCMYK"})
_ICC_COLOR_SPACE = re.compile(r"\[\s*/ICCBased\s+(\d+)\s+0\s+R\s*\]")
_INLINE_IMAGE_OPERATOR = re.compile(
    rb"(?:^|[\x00\t\n\f\r ()<>\[\]{}/%])BI"
    rb"(?=$|[\x00\t\n\f\r ()<>\[\]{}/%])"
)
_MAX_ICC_PROFILE_BYTES = 64 * 1024
_MAX_ZLIB_OUTPUT_CHUNK = 64 * 1024


class PdfPageCountExceededError(RuntimeError):
    """Stable adapter boundary raised before prohibited page iteration."""

    def __init__(self) -> None:
        super().__init__("inspection-pdf-page-count-exceeded")


class PdfParserBoundaryExceededError(RuntimeError):
    """Stable boundary raised before an unproved PDF parser expansion."""

    def __init__(self) -> None:
        super().__init__("inspection-parser-boundary-exceeded")


class MediaPreviewError(RuntimeError):
    """Fixed local-preview failure without parser or document details."""

    def __init__(self, code: str) -> None:
        if code not in {
            "preview-unavailable",
            "preview-over-limit",
            "preview-parser-boundary-exceeded",
        }:
            raise ValueError("media preview error code must be fixed")
        super().__init__(code)


class PackageImageError(RuntimeError):
    """Fixed bounded failure for package-specific image normalization."""

    def __init__(self, code: str) -> None:
        if code not in {"package-image-unavailable", "package-image-over-limit"}:
            raise ValueError("package image error code must be fixed")
        super().__init__(code)


def _pdf_boundary() -> None:
    raise PdfParserBoundaryExceededError()


def _xref_key(document: object, xref: int, key: str) -> tuple[str, str]:
    try:
        result = document.xref_get_key(xref, key)  # type: ignore[attr-defined]
    except Exception:
        result = None
    if (
        type(result) is not tuple
        or len(result) != 2
        or type(result[0]) is not str
        or type(result[1]) is not str
    ):
        _pdf_boundary()
    return result


def _positive_int_key(document: object, xref: int, key: str) -> int:
    value_type, value = _xref_key(document, xref, key)
    if value_type == "xref":
        value_xref = _xref_reference(value)
        try:
            is_stream = document.xref_is_stream(value_xref)  # type: ignore[attr-defined]
            value = document.xref_object(  # type: ignore[attr-defined]
                value_xref,
                compressed=False,
            )
        except Exception:
            is_stream = None
            value = None
        if is_stream is not False or type(value) is not str:
            _pdf_boundary()
        value = value.strip()
    elif value_type != "int":
        _pdf_boundary()
    if (
        type(value) is not str
        or len(value) > _MAX_XREF_DIGITS
        or not value.isascii()
        or not value.isdigit()
    ):
        _pdf_boundary()
    parsed = int(value)
    if parsed <= 0:
        _pdf_boundary()
    return parsed


def _xref_reference(value: object) -> int:
    if type(value) is not str or len(value) > _MAX_XREF_REFERENCE_CHARS:
        _pdf_boundary()
    pieces = value.split()
    if (
        len(pieces) != 3
        or pieces[1:] != ["0", "R"]
        or not pieces[0].isascii()
        or not pieces[0].isdigit()
        or len(pieces[0]) > _MAX_XREF_DIGITS
    ):
        _pdf_boundary()
    parsed = int(pieces[0])
    if parsed <= 0:
        _pdf_boundary()
    return parsed


def _pdf_metadata_tokens(value: object) -> tuple[str, ...]:
    if (
        type(value) is not str
        or len(value) > _MAX_PDF_METADATA_CHARS
        or not value.isascii()
    ):
        _pdf_boundary()
    whitespace = "\x00\t\n\f\r "
    delimiters = whitespace + "()<>[]{}/%"
    tokens = []
    position = 0
    while position < len(value):
        while position < len(value) and value[position] in whitespace:
            position += 1
        if position == len(value):
            break
        if value.startswith("<<", position) or value.startswith(">>", position):
            token = value[position : position + 2]
            position += 2
        elif value[position] in "[]":
            token = value[position]
            position += 1
        elif value[position] == "/":
            end = position + 1
            while end < len(value) and value[end] not in delimiters:
                end += 1
            token = value[position:end]
            if (
                len(token) <= 1
                or len(token) > _MAX_PDF_NAME_CHARS
                or "#" in token
            ):
                _pdf_boundary()
            position = end
        else:
            end = position
            while end < len(value) and value[end] not in delimiters:
                end += 1
            token = value[position:end]
            if not token:
                _pdf_boundary()
            position = end
        tokens.append(token)
        if len(tokens) > _MAX_PDF_METADATA_TOKENS:
            _pdf_boundary()
    return tuple(tokens)


def _parse_pdf_metadata_object(value: object):
    tokens = _pdf_metadata_tokens(value)
    position = 0

    def parse(depth: int):
        nonlocal position
        if depth > _MAX_PDF_METADATA_DEPTH or position >= len(tokens):
            _pdf_boundary()
        token = tokens[position]
        position += 1
        if token == "<<":
            pairs = []
            keys = set()
            while True:
                if position >= len(tokens):
                    _pdf_boundary()
                if tokens[position] == ">>":
                    position += 1
                    return "dict", tuple(pairs)
                key = tokens[position]
                position += 1
                if not key.startswith("/") or key in keys:
                    _pdf_boundary()
                keys.add(key)
                pairs.append((key, parse(depth + 1)))
        if token == "[":
            items = []
            while True:
                if position >= len(tokens):
                    _pdf_boundary()
                if tokens[position] == "]":
                    position += 1
                    return "array", tuple(items)
                items.append(parse(depth + 1))
        if token in {">>", "]"}:
            _pdf_boundary()
        if token.startswith("/"):
            return "name", token
        if token in {"true", "false"}:
            return "bool", token == "true"
        if token == "null":
            return "null", None
        if len(token) > 32 or re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", token) is None:
            _pdf_boundary()
        if (
            token.isdigit()
            and len(token) <= _MAX_XREF_DIGITS
            and position + 1 < len(tokens)
            and tokens[position] == "0"
            and tokens[position + 1] == "R"
        ):
            position += 2
            parsed_xref = int(token)
            if parsed_xref <= 0:
                _pdf_boundary()
            return "ref", parsed_xref
        return "number", token

    parsed = parse(0)
    if position != len(tokens):
        _pdf_boundary()
    return parsed


def _pdf_metadata_node(value_type: object, value: object):
    if type(value_type) is not str or type(value) is not str:
        _pdf_boundary()
    expected_kind = {
        "array": "array",
        "bool": "bool",
        "dict": "dict",
        "float": "number",
        "int": "number",
        "name": "name",
        "null": "null",
        "xref": "ref",
    }.get(value_type)
    if expected_kind is None:
        _pdf_boundary()
    parsed = _parse_pdf_metadata_object(value)
    if parsed[0] != expected_kind:
        _pdf_boundary()
    return parsed


def _dictionary_items(node: object) -> dict[str, object]:
    if type(node) is not tuple or len(node) != 2 or node[0] != "dict":
        _pdf_boundary()
    pairs = node[1]
    if type(pairs) is not tuple:
        _pdf_boundary()
    return {key[1:]: value for key, value in pairs}


def _reference_map(node: object) -> tuple[int, ...]:
    items = _dictionary_items(node)
    if len(items) > _MAX_RESOURCE_RECORDS_PER_PAGE:
        _pdf_boundary()
    references = []
    for value in items.values():
        if type(value) is not tuple or len(value) != 2 or value[0] != "ref":
            _pdf_boundary()
        references.append(value[1])
    return tuple(references)


def _bounded_object_node(document: object, xref: int):
    try:
        is_stream = document.xref_is_stream(xref)  # type: ignore[attr-defined]
        value = document.xref_object(  # type: ignore[attr-defined]
            xref,
            compressed=False,
        )
    except Exception:
        is_stream = None
        value = None
    if (
        is_stream is not False
        or type(value) is not str
        or len(value) > _MAX_PDF_OBJECT_CHARS
    ):
        _pdf_boundary()
    return _parse_pdf_metadata_object(value)


def _number(node: object) -> float:
    if type(node) is not tuple or len(node) != 2 or node[0] != "number":
        _pdf_boundary()
    try:
        value = float(node[1])
    except Exception:
        value = math.nan
    if not math.isfinite(value):
        _pdf_boundary()
    return value


def _bounded_flate_size(raw: bytes, limit: int) -> int:
    if type(raw) is not bytes or type(limit) is not int or limit < 0:
        _pdf_boundary()
    decompressor = zlib.decompressobj()
    produced = 0
    try:
        for offset in range(0, len(raw), 64 * 1024):
            pending = raw[offset : offset + 64 * 1024]
            while pending:
                maximum_output = min(
                    _MAX_ZLIB_OUTPUT_CHUNK,
                    limit - produced + 1,
                )
                chunk = decompressor.decompress(pending, maximum_output)
                produced += len(chunk)
                if produced > limit:
                    chunk = b""
                    pending = b""
                    _pdf_boundary()
                unconsumed = decompressor.unconsumed_tail
                if unconsumed and len(unconsumed) == len(pending) and not chunk:
                    pending = b""
                    _pdf_boundary()
                pending = unconsumed
                chunk = b""
    except PdfParserBoundaryExceededError:
        raise
    except Exception:
        _pdf_boundary()
    if (
        produced > limit
        or not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        _pdf_boundary()
    return produced


def _bounded_flate_output(raw: bytes, limit: int) -> bytes:
    if type(raw) is not bytes or type(limit) is not int or limit < 0:
        _pdf_boundary()
    decompressor = zlib.decompressobj()
    output = bytearray()
    try:
        for offset in range(0, len(raw), 64 * 1024):
            pending = raw[offset : offset + 64 * 1024]
            while pending:
                chunk = decompressor.decompress(
                    pending,
                    min(_MAX_ZLIB_OUTPUT_CHUNK, limit - len(output) + 1),
                )
                output.extend(chunk)
                if len(output) > limit:
                    output.clear()
                    _pdf_boundary()
                unconsumed = decompressor.unconsumed_tail
                if unconsumed and len(unconsumed) == len(pending) and not chunk:
                    output.clear()
                    _pdf_boundary()
                pending = unconsumed
    except PdfParserBoundaryExceededError:
        raise
    except Exception:
        output.clear()
        _pdf_boundary()
    if (
        not decompressor.eof
        or decompressor.unused_data
        or decompressor.unconsumed_tail
    ):
        output.clear()
        _pdf_boundary()
    return bytes(output)


def _prove_jpeg_header(
    snapshot: bytes,
    *,
    width: int,
    height: int,
    bits: int,
) -> None:
    if (
        type(snapshot) is not bytes
        or type(width) is not int
        or type(height) is not int
        or type(bits) is not int
        or len(snapshot) < 4
        or snapshot[:2] != b"\xff\xd8"
    ):
        _pdf_boundary()
    position = 2
    while position < len(snapshot):
        if snapshot[position] != 0xFF:
            _pdf_boundary()
        while position < len(snapshot) and snapshot[position] == 0xFF:
            position += 1
        if position >= len(snapshot):
            _pdf_boundary()
        marker = snapshot[position]
        position += 1
        if marker in {0x01, 0xD8} or 0xD0 <= marker <= 0xD7:
            continue
        if marker in {0xD9, 0xDA} or position + 2 > len(snapshot):
            _pdf_boundary()
        segment_length = int.from_bytes(snapshot[position : position + 2], "big")
        if segment_length < 2 or position + segment_length > len(snapshot):
            _pdf_boundary()
        if marker in {0xC0, 0xC1, 0xC2}:
            if segment_length < 8:
                _pdf_boundary()
            precision = snapshot[position + 2]
            jpeg_height = int.from_bytes(
                snapshot[position + 3 : position + 5],
                "big",
            )
            jpeg_width = int.from_bytes(
                snapshot[position + 5 : position + 7],
                "big",
            )
            components = snapshot[position + 7]
            if (
                precision != bits
                or jpeg_width != width
                or jpeg_height != height
                or components not in {1, 3, 4}
            ):
                _pdf_boundary()
            return
        position += segment_length
    _pdf_boundary()


def _decoded_stream_after_proof(
    document: object,
    xref: int,
    expected_size: int,
) -> bytes:
    try:
        decoded = document.xref_stream(xref)  # type: ignore[attr-defined]
    except Exception:
        _pdf_boundary()
    if type(decoded) is not bytes or len(decoded) != expected_size:
        decoded = b""
        _pdf_boundary()
    return decoded


def _empty_decode_parameters(node: object) -> bool:
    return node == ("null", None) or node == ("dict", ())


def _prove_dct_decode_parameters(node: object) -> None:
    if _empty_decode_parameters(node):
        return
    items = _dictionary_items(node)
    if set(items) - {"Quality"}:
        _pdf_boundary()
    quality = items.get("Quality")
    if quality is not None:
        value = _number(quality)
        if not value.is_integer() or not 0 <= value <= 100:
            _pdf_boundary()


def _bounded_stream_size(
    document: object,
    xref: int,
    *,
    decoded_limit: int,
    raw_limit: int,
    allowed_filters: frozenset[str],
    dct_dimensions: tuple[int, int, int] | None = None,
) -> tuple[int, int]:
    if (
        type(xref) is not int
        or xref <= 0
        or type(decoded_limit) is not int
        or decoded_limit < 0
        or type(raw_limit) is not int
        or raw_limit < 0
        or type(allowed_filters) is not frozenset
        or any(type(value) is not str for value in allowed_filters)
        or (
            dct_dimensions is not None
            and (
                type(dct_dimensions) is not tuple
                or len(dct_dimensions) != 3
                or any(type(value) is not int or value <= 0 for value in dct_dimensions)
            )
        )
    ):
        _pdf_boundary()
    try:
        if document.xref_is_stream(xref) is not True:  # type: ignore[attr-defined]
            _pdf_boundary()
    except PdfParserBoundaryExceededError:
        raise
    except Exception:
        _pdf_boundary()
    declared_length = _positive_int_key(document, xref, "Length")
    if declared_length > raw_limit:
        _pdf_boundary()
    filter_type, filter_value = _xref_key(document, xref, "Filter")
    if filter_type == "null" and filter_value == "null":
        selected_filters = ()
    elif filter_type == "name" and filter_value in allowed_filters:
        selected_filters = (filter_value,)
    elif filter_type == "array":
        filter_node = _pdf_metadata_node(filter_type, filter_value)
        selected_filters = tuple(
            value[1]
            for value in filter_node[1]
            if type(value) is tuple
            and len(value) == 2
            and value[0] == "name"
        )
        if (
            len(selected_filters) != len(filter_node[1])
            or selected_filters != ("/FlateDecode", "/DCTDecode")
            or any(value not in allowed_filters for value in selected_filters)
        ):
            _pdf_boundary()
    else:
        _pdf_boundary()
    decode_type, decode_value = _xref_key(document, xref, "DecodeParms")
    decode_parameters = _pdf_metadata_node(decode_type, decode_value)
    if selected_filters in {(), ("/FlateDecode",)}:
        if not _empty_decode_parameters(decode_parameters):
            _pdf_boundary()
    elif selected_filters == ("/DCTDecode",):
        _prove_dct_decode_parameters(decode_parameters)
    elif selected_filters == ("/FlateDecode", "/DCTDecode"):
        if (
            type(decode_parameters) is not tuple
            or len(decode_parameters) != 2
            or decode_parameters[0] != "array"
            or len(decode_parameters[1]) != 2
            or not _empty_decode_parameters(decode_parameters[1][0])
        ):
            _pdf_boundary()
        _prove_dct_decode_parameters(decode_parameters[1][1])
    else:
        _pdf_boundary()
    if "/DCTDecode" in selected_filters and dct_dimensions is None:
        _pdf_boundary()
    try:
        raw = document.xref_stream_raw(xref)  # type: ignore[attr-defined]
    except Exception:
        _pdf_boundary()
    if type(raw) is not bytes or len(raw) != declared_length or len(raw) > raw_limit:
        raw = b""
        _pdf_boundary()
    charged_size = len(raw)
    if not selected_filters:
        decoded_size = len(raw)
        if decoded_size > decoded_limit:
            raw = b""
            _pdf_boundary()
    elif selected_filters == ("/FlateDecode",):
        decoded_size = _bounded_flate_size(raw, decoded_limit)
    elif selected_filters == ("/DCTDecode",):
        _prove_jpeg_header(
            raw,
            width=dct_dimensions[0],
            height=dct_dimensions[1],
            bits=dct_dimensions[2],
        )
        decoded_size = 0
    else:
        jpeg = _bounded_flate_output(raw, raw_limit - len(raw))
        _prove_jpeg_header(
            jpeg,
            width=dct_dimensions[0],
            height=dct_dimensions[1],
            bits=dct_dimensions[2],
        )
        charged_size += len(jpeg)
        jpeg = b""
        decoded_size = 0
    raw_size = charged_size
    raw = b""
    return raw_size, decoded_size


def _prove_calgray(node: object) -> None:
    items = _dictionary_items(node)
    if set(items) - {"BlackPoint", "Gamma", "WhitePoint"}:
        _pdf_boundary()
    white_point = items.get("WhitePoint")
    if (
        type(white_point) is not tuple
        or len(white_point) != 2
        or white_point[0] != "array"
        or len(white_point[1]) != 3
    ):
        _pdf_boundary()
    if any(not 0 < _number(value) <= 10 for value in white_point[1]):
        _pdf_boundary()
    gamma = items.get("Gamma")
    if gamma is not None and not 0 < _number(gamma) <= 10:
        _pdf_boundary()
    black_point = items.get("BlackPoint")
    if black_point is not None:
        if (
            type(black_point) is not tuple
            or len(black_point) != 2
            or black_point[0] != "array"
            or len(black_point[1]) != 3
            or any(not 0 <= _number(value) <= 10 for value in black_point[1])
        ):
            _pdf_boundary()


def _prove_color_space(
    document: object,
    node: object,
    *,
    raw_limit: int,
) -> int:
    if type(node) is not tuple or len(node) != 2:
        _pdf_boundary()
    if node[0] == "ref":
        node = _bounded_object_node(document, node[1])
    if node[0] == "name":
        if node[1] not in _DEVICE_COLOR_SPACES:
            _pdf_boundary()
        return 0
    if node[0] != "array" or len(node[1]) != 2:
        _pdf_boundary()
    family, detail = node[1]
    if family == ("name", "/ICCBased"):
        if type(detail) is not tuple or len(detail) != 2 or detail[0] != "ref":
            _pdf_boundary()
        profile_xref = detail[1]
        if _positive_int_key(document, profile_xref, "N") not in {1, 3, 4}:
            _pdf_boundary()
        raw_size, _ = _bounded_stream_size(
            document,
            profile_xref,
            decoded_limit=_MAX_ICC_PROFILE_BYTES,
            raw_limit=raw_limit,
            allowed_filters=frozenset({"/FlateDecode"}),
        )
        return raw_size
    if family == ("name", "/CalGray"):
        _prove_calgray(detail)
        return 0
    _pdf_boundary()


def _prove_resource_metadata(
    document: object,
    resource_xref: int | None,
    direct_resources: object | None,
    resource_keys: tuple[str, ...] | None,
) -> int:
    if resource_xref is None and direct_resources is None:
        return 0
    if resource_xref is not None:
        try:
            is_stream = document.xref_is_stream(resource_xref)  # type: ignore[attr-defined]
        except Exception:
            is_stream = None
        if (
            is_stream is not False
            or type(resource_keys) is not tuple
        ):
            _pdf_boundary()
        items = {}
        for key in resource_keys:
            value_type, value = _xref_key(document, resource_xref, key)
            items[key] = _pdf_metadata_node(value_type, value)
    else:
        items = _dictionary_items(direct_resources)
        if len(items) > len(_SAFE_RESOURCE_KEYS) or set(items) - _SAFE_RESOURCE_KEYS:
            _pdf_boundary()

    for key in ("Font", "XObject"):
        if key in items:
            _reference_map(items[key])

    if "ProcSet" in items:
        procset = items["ProcSet"]
        if (
            type(procset) is not tuple
            or len(procset) != 2
            or procset[0] != "array"
            or len(procset[1]) > len(_SAFE_PROCSET_NAMES)
            or any(
                type(value) is not tuple
                or len(value) != 2
                or value[0] != "name"
                or value[1] not in _SAFE_PROCSET_NAMES
                for value in procset[1]
            )
        ):
            _pdf_boundary()

    if "ExtGState" in items:
        for graphics_state_xref in _reference_map(items["ExtGState"]):
            graphics_state = _dictionary_items(
                _bounded_object_node(document, graphics_state_xref)
            )
            if set(graphics_state) - {"AIS", "BM", "CA", "SMask", "Type", "ca"}:
                _pdf_boundary()
            if graphics_state.get("Type") not in {None, ("name", "/ExtGState")}:
                _pdf_boundary()
            if graphics_state.get("BM") not in {None, ("name", "/Normal")}:
                _pdf_boundary()
            if graphics_state.get("AIS") not in {None, ("bool", False)}:
                _pdf_boundary()
            if graphics_state.get("SMask") not in {None, ("name", "/None")}:
                _pdf_boundary()
            for alpha_key in ("CA", "ca"):
                if alpha_key in graphics_state:
                    alpha = _number(graphics_state[alpha_key])
                    if not 0 <= alpha <= 1:
                        _pdf_boundary()

    total_raw = 0
    if "ColorSpace" in items:
        color_spaces = _dictionary_items(items["ColorSpace"])
        if len(color_spaces) > _MAX_RESOURCE_RECORDS_PER_PAGE:
            _pdf_boundary()
        for color_space in color_spaces.values():
            total_raw += _prove_color_space(
                document,
                color_space,
                raw_limit=_MAX_RAW_RESOURCE_BYTES_PER_PAGE - total_raw,
            )
    return total_raw


def _resource_xref(
    document: object,
    page: object,
) -> tuple[int | None, object | None, tuple[str, ...] | None]:
    try:
        page_xref = page.xref  # type: ignore[attr-defined]
    except Exception:
        page_xref = None
    if type(page_xref) is not int or page_xref <= 0:
        _pdf_boundary()
    current_xref = page_xref
    visited = set()
    parent_depth = 0
    resource_xref = None
    direct_resources = None
    resource_keys = None
    while True:
        if current_xref in visited:
            _pdf_boundary()
        visited.add(current_xref)
        if parent_depth and _xref_key(document, current_xref, "Type") != (
            "name",
            "/Pages",
        ):
            _pdf_boundary()
        if resource_xref is None and direct_resources is None:
            value_type, value = _xref_key(document, current_xref, "Resources")
            if (value_type, value) != ("null", "null"):
                if value_type == "xref":
                    resource_xref = _xref_reference(value)
                    keys = None
                    try:
                        keys = document.xref_get_keys(  # type: ignore[attr-defined]
                            resource_xref
                        )
                    except Exception:
                        pass
                    if (
                        type(keys) not in {list, tuple}
                        or len(keys) > len(_SAFE_RESOURCE_KEYS)
                        or any(
                            type(key) is not str or key not in _SAFE_RESOURCE_KEYS
                            for key in keys
                        )
                    ):
                        _pdf_boundary()
                    resource_keys = tuple(keys)
                elif value_type == "dict":
                    direct_resources = _pdf_metadata_node(value_type, value)
                else:
                    _pdf_boundary()

        parent_type, parent_value = _xref_key(document, current_xref, "Parent")
        if (parent_type, parent_value) == ("null", "null"):
            if parent_depth == 0:
                _pdf_boundary()
            return resource_xref, direct_resources, resource_keys
        if parent_type != "xref":
            _pdf_boundary()
        current_xref = _xref_reference(parent_value)
        parent_depth += 1
        if parent_depth > _MAX_PAGE_TREE_PARENT_DEPTH:
            _pdf_boundary()


def _prove_standard_fonts(page: object, document: object) -> bool:
    try:
        fonts = page.get_fonts(full=True)  # type: ignore[attr-defined]
    except Exception:
        _pdf_boundary()
    if type(fonts) not in {list, tuple} or len(fonts) > _MAX_RESOURCE_RECORDS_PER_PAGE:
        _pdf_boundary()
    for font in fonts:
        if type(font) not in {list, tuple} or len(font) < 7:
            _pdf_boundary()
        xref, subtype, base_font, encoding = font[0], font[2], font[3], font[5]
        if (
            type(xref) is not int
            or xref <= 0
            or subtype != "Type1"
            or type(base_font) is not str
            or base_font not in _STANDARD_TYPE1_FONTS
            or encoding not in {"WinAnsiEncoding", "MacRomanEncoding", ""}
            or _xref_key(document, xref, "ToUnicode") != ("null", "null")
            or _xref_key(document, xref, "FontDescriptor") != ("null", "null")
        ):
            _pdf_boundary()
    return bool(fonts)


def _prove_image_color_space(
    document: object,
    image_xref: int,
    *,
    raw_limit: int,
) -> int:
    color_type, color_value = _xref_key(document, image_xref, "ColorSpace")
    if color_type == "name" and color_value in _DEVICE_COLOR_SPACES:
        return 0
    if color_type != "xref":
        _pdf_boundary()
    pieces = color_value.split()
    if len(pieces) != 3 or pieces[1:] != ["0", "R"] or not pieces[0].isdigit():
        _pdf_boundary()
    color_xref = int(pieces[0])
    if color_xref <= 0:
        _pdf_boundary()
    try:
        color_object = document.xref_object(  # type: ignore[attr-defined]
            color_xref,
            compressed=False,
        )
    except Exception:
        _pdf_boundary()
    if type(color_object) is not str or len(color_object) > 256:
        _pdf_boundary()
    profile_match = _ICC_COLOR_SPACE.fullmatch(color_object)
    color_object = ""
    if profile_match is None:
        _pdf_boundary()
    profile_xref = int(profile_match.group(1))
    if _positive_int_key(document, profile_xref, "N") not in {1, 3, 4}:
        _pdf_boundary()
    raw_size, _ = _bounded_stream_size(
        document,
        profile_xref,
        decoded_limit=_MAX_ICC_PROFILE_BYTES,
        raw_limit=raw_limit,
        allowed_filters=frozenset({"/FlateDecode"}),
    )
    return raw_size


def _prove_image_resources(
    page: object,
    document: object,
    *,
    pixel_limit: int,
    initial_raw: int = 0,
) -> bool:
    try:
        images = page.get_images(full=True)  # type: ignore[attr-defined]
        forms = page.get_xobjects()  # type: ignore[attr-defined]
    except Exception:
        _pdf_boundary()
    if type(forms) not in {list, tuple} or forms:
        _pdf_boundary()
    if type(images) not in {list, tuple} or len(images) > _MAX_RESOURCE_RECORDS_PER_PAGE:
        _pdf_boundary()
    total_pixels = 0
    if (
        type(initial_raw) is not int
        or initial_raw < 0
        or initial_raw > _MAX_RAW_RESOURCE_BYTES_PER_PAGE
    ):
        _pdf_boundary()
    total_raw = initial_raw
    for image in images:
        if type(image) not in {list, tuple} or len(image) < 10:
            _pdf_boundary()
        xref, smask, width, height, bits = image[:5]
        if (
            type(xref) is not int
            or xref <= 0
            or type(smask) is not int
            or smask < 0
            or type(width) is not int
            or type(height) is not int
            or type(bits) is not int
            or width <= 0
            or height <= 0
            or bits not in {1, 2, 4, 8, 16}
        ):
            _pdf_boundary()
        pixels = width * height
        total_pixels += pixels
        if pixels > pixel_limit or total_pixels > pixel_limit:
            _pdf_boundary()
        remaining_raw = _MAX_RAW_RESOURCE_BYTES_PER_PAGE - total_raw
        raw_size, _ = _bounded_stream_size(
            document,
            xref,
            decoded_limit=max(1, pixels * 8),
            raw_limit=remaining_raw,
            allowed_filters=_SAFE_IMAGE_FILTERS,
            dct_dimensions=(width, height, bits),
        )
        total_raw += raw_size
        remaining_raw = _MAX_RAW_RESOURCE_BYTES_PER_PAGE - total_raw
        total_raw += _prove_image_color_space(
            document,
            xref,
            raw_limit=remaining_raw,
        )
        if smask:
            mask_width = _positive_int_key(document, smask, "Width")
            mask_height = _positive_int_key(document, smask, "Height")
            mask_bits = _positive_int_key(document, smask, "BitsPerComponent")
            mask_pixels = mask_width * mask_height
            if (
                mask_width != width
                or mask_height != height
                or mask_pixels > pixel_limit
                or total_pixels + mask_pixels > pixel_limit
            ):
                _pdf_boundary()
            total_pixels += mask_pixels
            remaining_raw = _MAX_RAW_RESOURCE_BYTES_PER_PAGE - total_raw
            mask_raw, _ = _bounded_stream_size(
                document,
                smask,
                decoded_limit=max(1, mask_pixels * 2),
                raw_limit=remaining_raw,
                allowed_filters=_SAFE_IMAGE_FILTERS,
                dct_dimensions=(mask_width, mask_height, mask_bits),
            )
            total_raw += mask_raw
    return bool(images)


def _prove_pdf_page_bounds(
    document: object,
    page: object,
    limits: InspectionLimits,
) -> tuple[bool, bool]:
    resource_xref, direct_resources, resource_keys = _resource_xref(document, page)
    resource_raw = _prove_resource_metadata(
        document,
        resource_xref,
        direct_resources,
        resource_keys,
    )
    try:
        content_xrefs = page.get_contents()  # type: ignore[attr-defined]
    except Exception:
        _pdf_boundary()
    if (
        type(content_xrefs) not in {list, tuple}
        or len(content_xrefs) > _MAX_CONTENT_STREAMS_PER_PAGE
        or any(type(xref) is not int or xref <= 0 for xref in content_xrefs)
        or len(set(content_xrefs)) != len(content_xrefs)
    ):
        _pdf_boundary()
    remaining_decoded = max(1, limits.max_embedded_text_bytes_per_page // 4)
    remaining_raw = _MAX_RAW_RESOURCE_BYTES_PER_PAGE
    for content_xref in content_xrefs:
        raw_size, decoded_size = _bounded_stream_size(
            document,
            content_xref,
            decoded_limit=remaining_decoded,
            raw_limit=remaining_raw,
            allowed_filters=frozenset({"/FlateDecode"}),
        )
        decoded_content = _decoded_stream_after_proof(
            document,
            content_xref,
            decoded_size,
        )
        if _INLINE_IMAGE_OPERATOR.search(decoded_content):
            decoded_content = b""
            _pdf_boundary()
        decoded_content = b""
        remaining_raw -= raw_size
        remaining_decoded -= decoded_size
    has_fonts = _prove_standard_fonts(page, document)
    has_images = _prove_image_resources(
        page,
        document,
        pixel_limit=limits.max_decoded_image_pixels,
        initial_raw=resource_raw,
    )
    return has_fonts, has_images


def _source_problem(status: str, issue: str) -> InspectionAdapterResult:
    return InspectionAdapterResult(status, None, (issue,), ())


def _known_over_limit_image() -> InspectionAdapterResult:
    unit = InspectionUnitEvidence("image", 1, "none", (), ("unit-over-limit",))
    return InspectionAdapterResult("inspected", 1, (), (unit,))


def _bounded_text(text: object, byte_limit: int) -> str:
    if not isinstance(text, str) or byte_limit <= 0:
        return ""
    pieces = []
    used_bytes = 0
    character_index = 0
    text_length = min(len(text), byte_limit)
    while character_index < text_length and used_bytes < byte_limit:
        remaining_bytes = byte_limit - used_bytes
        chunk_end = min(
            text_length,
            character_index + min(1024, remaining_bytes),
        )
        chunk = text[character_index:chunk_end]
        if not chunk:
            break
        encoded_chunk = chunk.encode("utf-8", errors="ignore")
        if len(encoded_chunk) <= remaining_bytes:
            pieces.append(encoded_chunk.decode("utf-8"))
            used_bytes += len(encoded_chunk)
            character_index = chunk_end
            continue
        for character in chunk:
            encoded_character = character.encode("utf-8", errors="ignore")
            if len(encoded_character) > byte_limit - used_bytes:
                return "".join(pieces)
            if encoded_character:
                pieces.append(encoded_character.decode("utf-8"))
                used_bytes += len(encoded_character)
            character_index += 1
    return "".join(pieces)


def _text_is_sufficient(text: str) -> bool:
    return (
        sum(not character.isspace() for character in text) >= 40
        and len(_ALPHABETIC_TOKEN.findall(text)) >= 4
    )


def _signals(text: str, *, unit_kind: str, mostly_image: bool, embedded_media: bool):
    signal_codes = signals_from_private_text(
        text,
        TextSignalContext(
            unit_kind,
            mostly_image=mostly_image,
            embedded_media=embedded_media,
            worksheet_hidden=False,
            row_pattern=False,
        ),
    )
    text = ""
    return signal_codes


def _ocr_evidence(
    image_bytes: bytes,
    *,
    unit_kind: str,
    unit_index: int,
    embedded_media: bool,
    extra_issue_codes: tuple[str, ...],
    limits: InspectionLimits,
    ocr_budget: OcrBudget,
    ocr_runner,
    _private_text_sink=None,
) -> InspectionUnitEvidence:
    try:
        outcome = ocr_runner(
            image_bytes,
            budget=ocr_budget,
            timeout_seconds=limits.max_ocr_seconds_per_unit,
        )
    except Exception:
        outcome = None
    image_bytes = b""

    if type(outcome) is OcrOutcome:
        try:
            status = object.__getattribute__(outcome, "status")
            private_text = object.__getattribute__(outcome, "private_text")
        except Exception:
            status = None
            private_text = None
    else:
        status = None
        private_text = None
    valid_status = type(status) is str and status in _OCR_STATUSES
    valid_text = type(private_text) is str
    valid_pair = valid_status and valid_text and (
        (status in {"succeeded", "low-confidence"}) == bool(private_text)
    )
    if not valid_pair:
        status = "failed"
        private_text = ""
    if status in {"succeeded", "low-confidence"}:
        _capture_private_text(
            _private_text_sink, unit_kind, unit_index, private_text
        )
    signal_codes = _signals(
        private_text if status in {"succeeded", "low-confidence"} else "",
        unit_kind=unit_kind,
        mostly_image=True,
        embedded_media=embedded_media,
    )
    private_text = ""
    outcome = None
    issue = _OCR_ISSUES.get(status)
    issues = set(extra_issue_codes)
    if issue is not None:
        issues.add(issue)
    ordered_issues = tuple(
        code
        for code in (
            "unit-over-limit",
            "multi-frame-image",
            "ocr-unavailable",
            "ocr-timeout",
            "ocr-failed",
            "ocr-low-confidence",
        )
        if code in issues
    )
    return InspectionUnitEvidence(
        unit_kind,
        unit_index,
        "local-ocr",
        signal_codes,
        ordered_issues,
    )


def _failed_ocr_unit(
    unit_index: int, *, embedded_media: bool
) -> InspectionUnitEvidence:
    return InspectionUnitEvidence(
        "pdf-page",
        unit_index,
        "local-ocr",
        _signals(
            "",
            unit_kind="pdf-page",
            mostly_image=True,
            embedded_media=embedded_media,
        ),
        ("ocr-failed",),
    )


def _page_predicted_over_limit(page: object, pixel_limit: int) -> bool:
    try:
        rect = page.rect  # type: ignore[attr-defined]
        scale = _PDF_DPI / 72
        width = math.ceil(abs(float(rect.width)) * scale)
        height = math.ceil(abs(float(rect.height)) * scale)
        return width <= 0 or height <= 0 or width * height > pixel_limit
    except Exception:
        return True


def _inspect_pdf_page(
    document: object,
    page: object,
    unit_index: int,
    *,
    limits: InspectionLimits,
    ocr_budget: OcrBudget,
    ocr_runner,
    _private_text_sink=None,
) -> InspectionUnitEvidence:
    has_fonts, embedded_media = _prove_pdf_page_bounds(document, page, limits)
    private_text = ""
    if has_fonts:
        try:
            extracted = page.get_text("text")  # type: ignore[attr-defined]
            private_text = _bounded_text(
                extracted,
                limits.max_embedded_text_bytes_per_page,
            )
            if type(extracted) is not str or len(private_text) != len(extracted):
                extracted = ""
                private_text = ""
                _pdf_boundary()
            extracted = ""
        except PdfParserBoundaryExceededError:
            raise
        except Exception:
            private_text = ""

    if _text_is_sufficient(private_text):
        _capture_private_text(
            _private_text_sink, "pdf-page", unit_index, private_text
        )
        signal_codes = _signals(
            private_text,
            unit_kind="pdf-page",
            mostly_image=False,
            embedded_media=embedded_media,
        )
        private_text = ""
        return InspectionUnitEvidence(
            "pdf-page", unit_index, "embedded-text", signal_codes, ()
        )
    private_text = ""

    if _page_predicted_over_limit(page, limits.max_decoded_image_pixels):
        return InspectionUnitEvidence(
            "pdf-page", unit_index, "none", (), ("unit-over-limit",)
        )
    try:
        pixmap = page.get_pixmap(  # type: ignore[attr-defined]
            dpi=_PDF_DPI,
            alpha=False,
            annots=False,
        )
        width = pixmap.width
        height = pixmap.height
        if (
            not isinstance(width, int)
            or isinstance(width, bool)
            or not isinstance(height, int)
            or isinstance(height, bool)
            or width <= 0
            or height <= 0
            or width * height > limits.max_decoded_image_pixels
        ):
            return InspectionUnitEvidence(
                "pdf-page", unit_index, "none", (), ("unit-over-limit",)
            )
        rendered = pixmap.tobytes("png")
        pixmap = None
        if not isinstance(rendered, bytes) or len(rendered) > _OCR_IMAGE_BYTES:
            rendered = b""
            return InspectionUnitEvidence(
                "pdf-page", unit_index, "none", (), ("unit-over-limit",)
            )
    except Exception:
        return _failed_ocr_unit(unit_index, embedded_media=embedded_media)

    evidence = _ocr_evidence(
        rendered,
        unit_kind="pdf-page",
        unit_index=unit_index,
        embedded_media=embedded_media,
        extra_issue_codes=(),
        limits=limits,
        ocr_budget=ocr_budget,
        ocr_runner=ocr_runner,
        _private_text_sink=_private_text_sink,
    )
    rendered = b""
    return evidence


def inspect_pdf(
    snapshot: bytes,
    *,
    limits: InspectionLimits,
    ocr_budget: OcrBudget,
    ocr_runner,
    remaining_units: int | None = None,
    _private_text_sink=None,
) -> InspectionAdapterResult:
    """Inspect each actual PDF page from one immutable in-memory snapshot."""
    if type(snapshot) is not bytes:
        raise TypeError("inspection snapshot must be bytes")
    if len(snapshot) > limits.max_pdf_source_bytes:
        return _source_problem("over-limit", "document-over-limit")
    if remaining_units is None:
        remaining_units = limits.max_units
    if (
        type(remaining_units) is not int
        or remaining_units < 0
        or remaining_units > limits.max_units
    ):
        raise ValueError("remaining_units must be within the inspection unit budget")

    try:
        document = fitz.open(stream=snapshot, filetype="pdf")
    except Exception:
        return _source_problem("unreadable", "document-unreadable")

    try:
        with document:
            if document.needs_pass:
                return _source_problem("encrypted", "document-encrypted")
            page_count = document.page_count
            if (
                not isinstance(page_count, int)
                or isinstance(page_count, bool)
                or page_count < 0
            ):
                return _source_problem("unreadable", "document-unreadable")
            if page_count > limits.max_pdf_pages:
                raise PdfPageCountExceededError()
            if page_count > remaining_units:
                raise InspectionUnitCountExceededError()

            units = []
            for page_number in range(page_count):
                unit_index = page_number + 1
                try:
                    page = document.load_page(page_number)
                except Exception:
                    units.append(_failed_ocr_unit(unit_index, embedded_media=False))
                    continue
                units.append(
                    _inspect_pdf_page(
                        document,
                        page,
                        unit_index,
                        limits=limits,
                        ocr_budget=ocr_budget,
                        ocr_runner=ocr_runner,
                        _private_text_sink=_private_text_sink,
                    )
                )
            return InspectionAdapterResult("inspected", page_count, (), tuple(units))
    except PdfPageCountExceededError:
        raise
    except PdfParserBoundaryExceededError:
        raise
    except InspectionUnitCountExceededError:
        raise
    except PrivateTextSinkFailure:
        raise
    except Exception:
        return _source_problem("unreadable", "document-unreadable")


def _normalize_image(snapshot: bytes, limits: InspectionLimits):
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(BytesIO(snapshot)) as image:
            width, height = image.size
            if (
                not isinstance(width, int)
                or isinstance(width, bool)
                or not isinstance(height, int)
                or isinstance(height, bool)
                or width <= 0
                or height <= 0
            ):
                raise ValueError("invalid image header")
            if width * height > limits.max_decoded_image_pixels:
                return None, False, True
            image.seek(0)
            try:
                image.seek(1)
            except EOFError:
                multi_frame = False
            else:
                multi_frame = True
            finally:
                image.seek(0)
            image.load()
            normalized = image.convert("RGB")
            try:
                stream = BytesIO()
                normalized.save(stream, format="PNG")
                rendered = stream.getvalue()
            finally:
                if normalized is not image:
                    normalized.close()
            if len(rendered) > _OCR_IMAGE_BYTES:
                rendered = b""
                return None, multi_frame, True
            return rendered, multi_frame, False


def inspect_image(
    snapshot: bytes,
    *,
    limits: InspectionLimits,
    ocr_budget: OcrBudget,
    ocr_runner,
    _private_text_sink=None,
) -> InspectionAdapterResult:
    """Inspect the first frame of one standalone image from immutable bytes."""
    if type(snapshot) is not bytes:
        raise TypeError("inspection snapshot must be bytes")
    if len(snapshot) > limits.max_image_source_bytes:
        return _known_over_limit_image()

    try:
        normalized, multi_frame, over_limit = _normalize_image(snapshot, limits)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        return _known_over_limit_image()
    except Exception:
        return _source_problem("unreadable", "document-unreadable")

    if over_limit or normalized is None:
        return _known_over_limit_image()
    extra_issues = ("multi-frame-image",) if multi_frame else ()
    unit = _ocr_evidence(
        normalized,
        unit_kind="image",
        unit_index=1,
        embedded_media=False,
        extra_issue_codes=extra_issues,
        limits=limits,
        ocr_budget=ocr_budget,
        ocr_runner=ocr_runner,
        _private_text_sink=_private_text_sink,
    )
    normalized = b""
    return InspectionAdapterResult("inspected", 1, (), (unit,))


def render_pdf_page_preview(
    snapshot: bytes,
    unit_index: int,
    *,
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> bytes:
    """Render one proved PDF page to a bounded 150-DPI in-memory PNG."""
    if type(snapshot) is not bytes or type(limits) is not InspectionLimits:
        raise TypeError("preview input must use bounded snapshot bytes and limits")
    if type(unit_index) is not int or not 1 <= unit_index <= limits.max_pdf_pages:
        raise MediaPreviewError("preview-unavailable")
    if len(snapshot) > limits.max_pdf_source_bytes:
        raise MediaPreviewError("preview-over-limit")
    try:
        document = fitz.open(stream=snapshot, filetype="pdf")
    except Exception:
        raise MediaPreviewError("preview-unavailable") from None
    try:
        with document:
            if document.needs_pass:
                raise MediaPreviewError("preview-unavailable")
            page_count = document.page_count
            if (
                type(page_count) is not int
                or page_count < 0
                or page_count > limits.max_pdf_pages
                or unit_index > page_count
            ):
                raise MediaPreviewError("preview-unavailable")
            page = document.load_page(unit_index - 1)
            if _page_predicted_over_limit(page, limits.max_decoded_image_pixels):
                raise MediaPreviewError("preview-over-limit")
            _prove_pdf_page_bounds(document, page, limits)
            pixmap = page.get_pixmap(dpi=_PDF_DPI, alpha=False, annots=False)
            width = pixmap.width
            height = pixmap.height
            if (
                type(width) is not int
                or type(height) is not int
                or width <= 0
                or height <= 0
                or width * height > limits.max_decoded_image_pixels
            ):
                raise MediaPreviewError("preview-over-limit")
            rendered = pixmap.tobytes("png")
            if type(rendered) is not bytes or len(rendered) > _OCR_IMAGE_BYTES:
                raise MediaPreviewError("preview-over-limit")
            return rendered
    except MediaPreviewError:
        raise
    except PdfParserBoundaryExceededError:
        raise MediaPreviewError("preview-parser-boundary-exceeded") from None
    except Exception:
        raise MediaPreviewError("preview-unavailable") from None


def render_image_preview(
    snapshot: bytes,
    *,
    limits: InspectionLimits = DEFAULT_INSPECTION_LIMITS,
) -> bytes:
    """Normalize the first image frame to the existing bounded in-memory PNG."""
    if type(snapshot) is not bytes or type(limits) is not InspectionLimits:
        raise TypeError("preview input must use bounded snapshot bytes and limits")
    if len(snapshot) > limits.max_image_source_bytes:
        raise MediaPreviewError("preview-over-limit")
    try:
        normalized, _multi_frame, over_limit = _normalize_image(snapshot, limits)
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise MediaPreviewError("preview-over-limit") from None
    except Exception:
        raise MediaPreviewError("preview-unavailable") from None
    if over_limit or normalized is None or len(normalized) > _OCR_IMAGE_BYTES:
        raise MediaPreviewError("preview-over-limit")
    return normalized


def _normalize_package_image(
    snapshot: bytes,
    *,
    limits: InspectionLimits,
    max_output_bytes: int,
) -> bytes:
    """Return fixed first-frame RGBA PNG bytes or a fixed bounded media error."""
    if type(snapshot) is not bytes or type(limits) is not InspectionLimits:
        raise TypeError("package image input must use bounded snapshot bytes and limits")
    if len(snapshot) > limits.max_image_source_bytes:
        raise PackageImageError("package-image-over-limit")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(BytesIO(snapshot)) as image:
                image.seek(0)
                width, height = image.size
                if (
                    type(width) is not int
                    or type(height) is not int
                    or width <= 0
                    or height <= 0
                    or width * height > limits.max_decoded_image_pixels
                ):
                    raise PackageImageError("package-image-over-limit")
                image.load()
                oriented = ImageOps.exif_transpose(image)
                normalized = oriented.convert("RGBA")
                try:
                    output = _CappedBytesIO(max_output_bytes)
                    normalized.save(
                        output,
                        format="PNG",
                        compress_level=9,
                        optimize=False,
                        bits=8,
                    )
                    rendered = output.getvalue()
                finally:
                    normalized.close()
                    if oriented is not image:
                        oriented.close()
    except PackageImageError:
        raise
    except _OutputLimitExceeded:
        raise PackageImageError("package-image-over-limit") from None
    except (Image.DecompressionBombWarning, Image.DecompressionBombError):
        raise PackageImageError("package-image-over-limit") from None
    except Exception:
        raise PackageImageError("package-image-unavailable") from None
    if len(rendered) > _OCR_IMAGE_BYTES:
        raise PackageImageError("package-image-over-limit")
    return rendered


def normalize_package_image(
    snapshot: bytes,
    *,
    limits: InspectionLimits,
) -> bytes:
    """Return fixed first-frame RGBA PNG bytes or a fixed bounded media error."""
    return _normalize_package_image(
        snapshot,
        limits=limits,
        max_output_bytes=_OCR_IMAGE_BYTES,
    )
