"""Bounded, byte-only PDF page and standalone-image inspection adapters."""
from __future__ import annotations

from io import BytesIO
import math
import re
import warnings
import zlib

import fitz
from PIL import Image

from ctv_inspection_classifier import TextSignalContext, signals_from_private_text
from ctv_inspection_model import (
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
_SAFE_RESOURCE_KEYS = frozenset({"Font", "ProcSet", "XObject"})
_SAFE_IMAGE_FILTERS = frozenset({"/FlateDecode"})
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
    if value_type != "int" or not value.isascii() or not value.isdigit():
        _pdf_boundary()
    parsed = int(value)
    if parsed <= 0:
        _pdf_boundary()
    return parsed


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


def _bounded_stream_size(
    document: object,
    xref: int,
    *,
    decoded_limit: int,
    raw_limit: int,
    allowed_filters: frozenset[str],
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
        selected_filter = None
    elif filter_type == "name" and filter_value in allowed_filters:
        selected_filter = filter_value
    else:
        _pdf_boundary()
    decode_type, decode_value = _xref_key(document, xref, "DecodeParms")
    if selected_filter == "/FlateDecode":
        if (decode_type, decode_value) not in {
            ("null", "null"),
            ("dict", "<<>>"),
        }:
            _pdf_boundary()
    elif (decode_type, decode_value) not in {
        ("null", "null"),
        ("dict", "<<>>"),
    }:
        _pdf_boundary()
    try:
        raw = document.xref_stream_raw(xref)  # type: ignore[attr-defined]
    except Exception:
        _pdf_boundary()
    if type(raw) is not bytes or len(raw) != declared_length or len(raw) > raw_limit:
        raw = b""
        _pdf_boundary()
    if selected_filter is None:
        decoded_size = len(raw)
        if decoded_size > decoded_limit:
            raw = b""
            _pdf_boundary()
    elif selected_filter == "/FlateDecode":
        decoded_size = _bounded_flate_size(raw, decoded_limit)
    else:
        decoded_size = 0
    raw_size = len(raw)
    raw = b""
    return raw_size, decoded_size


def _resource_xref(document: object, page: object) -> int | None:
    try:
        page_xref = page.xref  # type: ignore[attr-defined]
    except Exception:
        _pdf_boundary()
    if type(page_xref) is not int or page_xref <= 0:
        _pdf_boundary()
    current_xref = page_xref
    visited = set()
    parent_depth = 0
    while True:
        if current_xref in visited:
            _pdf_boundary()
        visited.add(current_xref)
        if parent_depth and _xref_key(document, current_xref, "Type") != (
            "name",
            "/Pages",
        ):
            _pdf_boundary()
        value_type, value = _xref_key(document, current_xref, "Resources")
        if (value_type, value) != ("null", "null"):
            if value_type != "xref":
                _pdf_boundary()
            pieces = value.split()
            if (
                len(pieces) != 3
                or pieces[1:] != ["0", "R"]
                or not pieces[0].isdigit()
            ):
                _pdf_boundary()
            resource_xref = int(pieces[0])
            if resource_xref <= 0:
                _pdf_boundary()
            try:
                keys = document.xref_get_keys(  # type: ignore[attr-defined]
                    resource_xref
                )
            except Exception:
                _pdf_boundary()
            if (
                type(keys) not in {list, tuple}
                or len(keys) > len(_SAFE_RESOURCE_KEYS)
                or any(
                    type(key) is not str or key not in _SAFE_RESOURCE_KEYS
                    for key in keys
                )
            ):
                _pdf_boundary()
            return resource_xref

        parent_type, parent_value = _xref_key(document, current_xref, "Parent")
        if (parent_type, parent_value) == ("null", "null"):
            return None
        if parent_type != "xref":
            _pdf_boundary()
        pieces = parent_value.split()
        if (
            len(pieces) != 3
            or pieces[1:] != ["0", "R"]
            or not pieces[0].isdigit()
        ):
            _pdf_boundary()
        current_xref = int(pieces[0])
        parent_depth += 1
        if current_xref <= 0 or parent_depth > _MAX_PAGE_TREE_PARENT_DEPTH:
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
    total_raw = 0
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
        )
        total_raw += raw_size
        remaining_raw = _MAX_RAW_RESOURCE_BYTES_PER_PAGE - total_raw
        total_raw += _prove_image_color_space(
            document,
            xref,
            raw_limit=remaining_raw,
        )
        if smask:
            remaining_raw = _MAX_RAW_RESOURCE_BYTES_PER_PAGE - total_raw
            mask_raw, _ = _bounded_stream_size(
                document,
                smask,
                decoded_limit=max(1, pixels * 2),
                raw_limit=remaining_raw,
                allowed_filters=_SAFE_IMAGE_FILTERS,
            )
            total_raw += mask_raw
    return bool(images)


def _prove_pdf_page_bounds(
    document: object,
    page: object,
    limits: InspectionLimits,
) -> tuple[bool, bool]:
    _resource_xref(document, page)
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
                    )
                )
            return InspectionAdapterResult("inspected", page_count, (), tuple(units))
    except PdfPageCountExceededError:
        raise
    except PdfParserBoundaryExceededError:
        raise
    except InspectionUnitCountExceededError:
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
    )
    normalized = b""
    return InspectionAdapterResult("inspected", 1, (), (unit,))
