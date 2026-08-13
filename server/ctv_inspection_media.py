"""Bounded, byte-only PDF page and standalone-image inspection adapters."""
from __future__ import annotations

from io import BytesIO
import math
import re
import warnings

import fitz
from PIL import Image

from ctv_inspection_classifier import TextSignalContext, signals_from_private_text
from ctv_inspection_model import (
    InspectionAdapterResult,
    InspectionLimits,
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


class PdfPageCountExceededError(RuntimeError):
    """Stable adapter boundary raised before prohibited page iteration."""

    def __init__(self) -> None:
        super().__init__("inspection-pdf-page-count-exceeded")


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


def _safe_page_has_images(page: object) -> bool:
    try:
        return bool(page.get_images(full=False))  # type: ignore[attr-defined]
    except Exception:
        return False


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
    page: object,
    unit_index: int,
    *,
    limits: InspectionLimits,
    ocr_budget: OcrBudget,
    ocr_runner,
) -> InspectionUnitEvidence:
    embedded_media = _safe_page_has_images(page)
    try:
        private_text = _bounded_text(
            page.get_text("text"),  # type: ignore[attr-defined]
            limits.max_embedded_text_bytes_per_page,
        )
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
        pixmap = page.get_pixmap(dpi=_PDF_DPI, alpha=False)  # type: ignore[attr-defined]
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
) -> InspectionAdapterResult:
    """Inspect each actual PDF page from one immutable in-memory snapshot."""
    if type(snapshot) is not bytes:
        raise TypeError("inspection snapshot must be bytes")
    if len(snapshot) > limits.max_pdf_source_bytes:
        return _source_problem("over-limit", "document-over-limit")

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
