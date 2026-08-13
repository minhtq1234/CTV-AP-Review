"""Pure, conservative file-type hints from a caller-bounded byte sample."""

import re

from ctv_inventory_model import DetectedType


_SAFE_EXTENSION = re.compile(r"\.[a-z0-9]{1,10}\Z")
_PDF_HEADER = re.compile(rb"%PDF-[0-9]\.[0-9]")
_RAR5_SIGNATURE = b"Rar!\x1a\x07\x01\x00"
_RAR4_SIGNATURE = b"Rar!\x1a\x07\x00"
_ZIP_SIGNATURES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_IMAGE_SIGNATURES = (
    b"\x89PNG\r\n\x1a\n",
    b"\xff\xd8\xff",
    b"GIF87a",
    b"GIF89a",
    b"II*\x00",
    b"MM\x00*",
)
_EXTENSION_TYPES: dict[str, DetectedType] = {
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xlsm": "xlsx",
    ".xltx": "xlsx",
    ".xltm": "xlsx",
    ".zip": "zip",
    ".rar": "rar",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".tif": "image",
    ".tiff": "image",
    ".webp": "image",
}


def safe_extension(private_name: str) -> str:
    """Return the final safe lowercase extension, or the opaque unknown value."""
    _, separator, suffix = private_name.rpartition(".")
    extension = f".{suffix.lower()}" if separator else "unknown"
    return extension if _SAFE_EXTENSION.fullmatch(extension) else "unknown"


def detect_type(sample: bytes) -> DetectedType:
    """Return a broad type hint from signatures within the supplied sample."""
    if _PDF_HEADER.search(sample[:1024]):
        return "pdf"
    if sample.startswith(_RAR5_SIGNATURE) or sample.startswith(_RAR4_SIGNATURE):
        return "rar"
    if sample.startswith(_IMAGE_SIGNATURES) or (
        sample.startswith(b"RIFF") and sample[8:12] == b"WEBP"
    ):
        return "image"
    if sample.startswith(_ZIP_SIGNATURES):
        if b"[Content_Types].xml" in sample and b"xl/workbook.xml" in sample:
            return "xlsx"
        return "zip"
    return "unknown"


def extension_expected_type(extension: str) -> DetectedType | None:
    """Map a safe supported extension to its broad expected type."""
    return _EXTENSION_TYPES.get(extension)


def type_issue_codes(
    extension: str, detected_type: DetectedType, *, sample_failed: bool = False
) -> tuple[str, ...]:
    """Return stable public issue codes without exposing the private filename."""
    if sample_failed:
        return ("type-detection-failed",)
    expected_type = extension_expected_type(extension)
    if expected_type is not None and expected_type != detected_type:
        return ("type-extension-mismatch",)
    return ()
