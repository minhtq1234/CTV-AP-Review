import pytest

from ctv_inventory_detection import (
    detect_type,
    extension_expected_type,
    safe_extension,
    type_issue_codes,
)


@pytest.mark.parametrize(
    ("sample", "expected"),
    [
        (b"%PDF-1.7\n", "pdf"),
        (b"prefix" + b"%PDF-2.0" + b"x" * 16, "pdf"),
        (b"PK\x03\x04rest", "zip"),
        (b"PK\x05\x06rest", "zip"),
        (b"PK\x07\x08rest", "zip"),
        (b"PK\x03\x04[Content_Types].xml xx xl/workbook.xml", "xlsx"),
        (b"Rar!\x1a\x07\x00rest", "rar"),
        (b"Rar!\x1a\x07\x01\x00rest", "rar"),
        (b"\x89PNG\r\n\x1a\nrest", "image"),
        (b"\xff\xd8\xffrest", "image"),
        (b"GIF87arest", "image"),
        (b"GIF89arest", "image"),
        (b"II*\x00rest", "image"),
        (b"MM\x00*rest", "image"),
        (b"RIFF\x04\x00\x00\x00WEBPrest", "image"),
        (b"not a known format", "unknown"),
    ],
)
def test_detect_type_uses_only_conservative_bounded_signatures(sample, expected):
    assert detect_type(sample) == expected


@pytest.mark.parametrize(
    ("private_name", "expected"),
    [
        ("PERSON.PDF", ".pdf"),
        ("archive.tar.gz", ".gz"),
        ("no-extension", "unknown"),
        ("bad.verylongextension", "unknown"),
        ("bad.địnhdạng", "unknown"),
        ("bad.<script>", "unknown"),
    ],
)
def test_safe_extension_never_returns_private_or_unsafe_text(private_name, expected):
    assert safe_extension(private_name) == expected


def test_mislabeled_supported_extension_reports_mismatch():
    assert extension_expected_type(".pdf") == "pdf"
    assert type_issue_codes(".pdf", "unknown") == ("type-extension-mismatch",)
    assert type_issue_codes(".pdf", "pdf") == ()


def test_pdf_signature_is_accepted_only_within_the_first_1024_bytes():
    assert detect_type(b"x" * 1_016 + b"%PDF-1.7") == "pdf"
    assert detect_type(b"x" * 1_017 + b"%PDF-1.7") == "unknown"


@pytest.mark.parametrize(
    "sample",
    [
        b"%PDF-1",
        b"%PDF-1x7",
        b"PK",
        b"Rar!\x1a\x07\x01",
        b"\x89PNG\r\n\x1a",
        b"\xff\xd8",
        b"GIF87",
        b"II*",
        b"RIFF\x04\x00\x00\x00WEB",
    ],
)
def test_malformed_or_truncated_signatures_remain_unknown(sample):
    assert detect_type(sample) == "unknown"


@pytest.mark.parametrize(
    "sample",
    [
        b"PK\x03\x04[Content_Types].xml",
        b"PK\x03\x04xl/workbook.xml",
        b"PK\x03\x04[content_types].xml xl/workbook.xml",
        b"PK\x03\x04[Content_Types].xml xl/workbook.XML",
    ],
)
def test_xlsx_hint_requires_both_exact_literal_markers(sample):
    assert detect_type(sample) == "zip"


@pytest.mark.parametrize(
    ("extension", "expected"),
    [
        (".pdf", "pdf"),
        (".xlsx", "xlsx"),
        (".xlsm", "xlsx"),
        (".xltx", "xlsx"),
        (".xltm", "xlsx"),
        (".zip", "zip"),
        (".rar", "rar"),
        (".png", "image"),
        (".jpg", "image"),
        (".jpeg", "image"),
        (".gif", "image"),
        (".tif", "image"),
        (".tiff", "image"),
        (".webp", "image"),
    ],
)
def test_supported_extensions_map_to_their_detected_type(extension, expected):
    assert extension_expected_type(extension) == expected


def test_unknown_extensions_do_not_create_mismatch_issues():
    assert extension_expected_type(".txt") is None
    assert type_issue_codes(".txt", "pdf") == ()


def test_sample_failure_has_one_issue_without_a_mismatch():
    assert type_issue_codes(".pdf", "unknown", sample_failed=True) == (
        "type-detection-failed",
    )


def test_returned_values_never_include_the_private_filename():
    private_name = "private-client-12345.PDF"
    returned_values = (
        safe_extension(private_name),
        *type_issue_codes(safe_extension(private_name), "unknown"),
        *type_issue_codes(safe_extension(private_name), "unknown", sample_failed=True),
    )
    assert all(private_name not in value for value in returned_values)
