import ast
import builtins
import dataclasses
from io import BytesIO
import socket
import tempfile
import warnings

import fitz
from PIL import Image
import pytest

from ctv_inspection_model import InspectionLimits
from ctv_local_ocr import OcrBudget, OcrOutcome


PRIVATE_TEXT = (
    "CAN CUOC CONG DAN MAT TRUOC 079123456789 "
    "so tien 5.000.000 ngay 13/08/2026"
)


def _pdf(*page_texts):
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_textbox(
                fitz.Rect(36, 36, 560, 780),
                text,
                fontsize=11,
            )
    snapshot = document.tobytes()
    document.close()
    return snapshot


def _scanned_pdf():
    image_bytes = _image_bytes("PNG", size=(120, 80), color=(250, 250, 250))
    document = fitz.open()
    page = document.new_page(width=120, height=80)
    page.insert_image(page.rect, stream=image_bytes)
    snapshot = document.tobytes()
    document.close()
    return snapshot


def _encrypted_pdf():
    document = fitz.open()
    document.new_page()
    stream = BytesIO()
    document.save(
        stream,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw="private-user-password",
        owner_pw="private-owner-password",
    )
    document.close()
    return stream.getvalue()


def _image_bytes(image_format="PNG", *, size=(12, 8), color=(255, 255, 255)):
    stream = BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(stream, format=image_format)
    return stream.getvalue()


def _animated_gif():
    stream = BytesIO()
    with Image.new("RGB", (3, 2), (255, 0, 0)) as first:
        with Image.new("RGB", (3, 2), (0, 0, 255)) as second:
            first.save(
                stream,
                format="GIF",
                save_all=True,
                append_images=[second],
                duration=50,
                loop=0,
            )
    return stream.getvalue()


class RecordingOcr:
    def __init__(self, outcome=None):
        self.outcome = outcome or OcrOutcome("succeeded", PRIVATE_TEXT)
        self.calls = []

    def __call__(self, image_bytes, *, budget, timeout_seconds):
        self.calls.append((image_bytes, budget, timeout_seconds))
        budget.used_units += 1
        return self.outcome


def _inspect_pdf(snapshot, *, runner=None, limits=None):
    from ctv_inspection_media import inspect_pdf

    return inspect_pdf(
        snapshot,
        limits=limits or InspectionLimits(),
        ocr_budget=OcrBudget(),
        ocr_runner=runner or RecordingOcr(),
    )


def _inspect_image(snapshot, *, runner=None, limits=None):
    from ctv_inspection_media import inspect_image

    return inspect_image(
        snapshot,
        limits=limits or InspectionLimits(),
        ocr_budget=OcrBudget(),
        ocr_runner=runner or RecordingOcr(),
    )


def test_pdf_embedded_text_reduces_service_contract_and_acceptance_pages_in_order():
    result = _inspect_pdf(_pdf(
        "HOP DONG DICH VU BEN A va BEN B NOI DUNG DICH VU CHU KY "
        "day la noi dung bo sung de vuot nguong bon muoi ky tu.",
        "BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU BEN A va BEN B CHU KY "
        "day la noi dung bo sung de vuot nguong bon muoi ky tu.",
    ))

    assert result.inspection_status == "inspected"
    assert result.unit_count == 2
    assert [unit.unit_index for unit in result.units] == [1, 2]
    assert [unit.inspection_method for unit in result.units] == [
        "embedded-text", "embedded-text",
    ]
    assert result.units[0].signal_codes == (
        "service-contract-heading", "party-section-present",
        "service-scope-section-present", "signature-section-present",
        "mostly-text-page",
    )
    assert result.units[1].signal_codes == (
        "party-section-present", "signature-section-present",
        "acceptance-heading", "acceptance-period-present", "mostly-text-page",
    )


def test_scanned_pdf_renders_one_150_dpi_png_and_invokes_ocr_once():
    runner = RecordingOcr()
    result = _inspect_pdf(_scanned_pdf(), runner=runner)

    assert len(runner.calls) == 1
    image_bytes, budget, timeout_seconds = runner.calls[0]
    assert image_bytes.startswith(b"\x89PNG\r\n\x1a\n")
    assert len(image_bytes) <= 25 * 1024 * 1024
    with Image.open(BytesIO(image_bytes)) as rendered:
        assert rendered.size == (250, 167)
    assert budget.used_units == 1
    assert timeout_seconds == 30
    assert result.units[0].inspection_method == "local-ocr"
    assert "identity-front-heading" in result.units[0].signal_codes
    assert "embedded-media-present" in result.units[0].signal_codes


@pytest.mark.parametrize("marker_ends_at_limit", [True, False])
def test_pdf_embedded_text_uses_the_exact_64_kib_boundary(
    monkeypatch, marker_ends_at_limit
):
    import ctv_inspection_media as media

    base = b"alpha beta gamma delta "
    marker = b" HOP DONG DICH VU"
    if marker_ends_at_limit:
        prefix = base + b"x" * (64 * 1024 - len(base) - len(marker))
        embedded_text = prefix + marker
    else:
        prefix = base + b"x" * 70_000
        embedded_text = prefix + marker

    class Page:
        def get_text(self, _kind):
            return embedded_text.decode()

        def get_images(self, **_kwargs):
            return []

    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def load_page(self, _index):
            return Page()

    monkeypatch.setattr(media.fitz, "open", lambda **_kwargs: Document())
    result = _inspect_pdf(b"synthetic-pdf")

    assert result.units[0].inspection_method == "embedded-text"
    assert (
        "service-contract-heading" in result.units[0].signal_codes
    ) is marker_ends_at_limit


def test_pdf_text_below_sufficiency_threshold_falls_back_to_ocr():
    runner = RecordingOcr()
    result = _inspect_pdf(_pdf("mot hai ba"), runner=runner)

    assert len(runner.calls) == 1
    assert result.units[0].inspection_method == "local-ocr"


def test_pdf_page_count_boundary_raises_stable_opaque_error_before_iteration(monkeypatch):
    import ctv_inspection_media as media

    opened = []

    class Document:
        needs_pass = False
        page_count = 10_001

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def load_page(self, _index):
            raise AssertionError("page iteration must not start")

    def fake_open(**kwargs):
        opened.append(kwargs)
        return Document()

    monkeypatch.setattr(media.fitz, "open", fake_open)
    with pytest.raises(media.PdfPageCountExceededError) as raised:
        _inspect_pdf(b"private-pdf-snapshot")

    assert str(raised.value) == "inspection-pdf-page-count-exceeded"
    assert repr(raised.value).find("private-pdf-snapshot") == -1
    assert opened == [{"stream": b"private-pdf-snapshot", "filetype": "pdf"}]


@pytest.mark.parametrize(
    ("snapshot", "expected_status", "expected_count", "expected_issue"),
    [
        (_encrypted_pdf(), "encrypted", None, "document-encrypted"),
        (b"not a pdf: private parser token", "unreadable", None, "document-unreadable"),
    ],
)
def test_pdf_source_failures_are_safe_source_only_results(
    snapshot, expected_status, expected_count, expected_issue
):
    result = _inspect_pdf(snapshot)

    assert result.inspection_status == expected_status
    assert result.unit_count is expected_count
    assert result.source_issue_codes == (expected_issue,)
    assert result.units == ()


def test_empty_pdf_is_an_inspected_zero_unit_source(monkeypatch):
    import ctv_inspection_media as media

    class EmptyDocument:
        needs_pass = False
        page_count = 0

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(media.fitz, "open", lambda **_kwargs: EmptyDocument())
    result = _inspect_pdf(b"synthetic-empty-pdf")

    assert result.inspection_status == "inspected"
    assert result.unit_count == 0
    assert result.units == ()


def test_pdf_render_failure_keeps_known_page_and_hides_exception(monkeypatch):
    import ctv_inspection_media as media

    class Page:
        rect = fitz.Rect(0, 0, 100, 100)

        def get_text(self, _kind):
            return ""

        def get_images(self, **_kwargs):
            return []

        def get_pixmap(self, **_kwargs):
            raise RuntimeError("parser page 079123456789 at 612x792")

    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def load_page(self, _index):
            return Page()

    monkeypatch.setattr(media.fitz, "open", lambda **_kwargs: Document())
    result = _inspect_pdf(b"synthetic-pdf")

    assert result.unit_count == 1
    assert result.units[0].inspection_method == "local-ocr"
    assert result.units[0].issue_codes == ("ocr-failed",)
    assert "079123456789" not in repr(result)
    assert "612x792" not in repr(result)


@pytest.mark.parametrize(
    ("outcome", "expected_issue", "has_identity_signal"),
    [
        (OcrOutcome("unavailable", ""), "ocr-unavailable", False),
        (OcrOutcome("timeout", ""), "ocr-timeout", False),
        (OcrOutcome("failed", ""), "ocr-failed", False),
        (OcrOutcome("over-limit", ""), "unit-over-limit", False),
        (OcrOutcome("low-confidence", PRIVATE_TEXT), "ocr-low-confidence", True),
    ],
)
def test_pdf_maps_every_safe_ocr_outcome(outcome, expected_issue, has_identity_signal):
    result = _inspect_pdf(_scanned_pdf(), runner=RecordingOcr(outcome))
    unit = result.units[0]

    assert unit.issue_codes == (expected_issue,)
    assert ("identity-number-pattern-present" in unit.signal_codes) is has_identity_signal


@pytest.mark.parametrize("encoded_size", [25 * 1024 * 1024, 25 * 1024 * 1024 + 1])
def test_pdf_rendered_png_enforces_exact_ocr_byte_boundary(monkeypatch, encoded_size):
    import ctv_inspection_media as media

    class Pixmap:
        width = 1
        height = 1

        def tobytes(self, _format):
            return b"\x89PNG\r\n\x1a\n" + b"x" * (encoded_size - 8)

    class Page:
        rect = fitz.Rect(0, 0, 1, 1)

        def get_text(self, _kind):
            return ""

        def get_images(self, **_kwargs):
            return []

        def get_pixmap(self, **_kwargs):
            return Pixmap()

    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def load_page(self, _index):
            return Page()

    monkeypatch.setattr(media.fitz, "open", lambda **_kwargs: Document())
    runner = RecordingOcr()
    result = _inspect_pdf(b"synthetic-pdf", runner=runner)

    assert len(runner.calls) == (1 if encoded_size == 25 * 1024 * 1024 else 0)
    assert result.units[0].issue_codes == (
        () if encoded_size == 25 * 1024 * 1024 else ("unit-over-limit",)
    )


def test_pdf_rendered_area_is_checked_before_encoding(monkeypatch):
    import ctv_inspection_media as media

    class Pixmap:
        width = 10_000
        height = 5_001

        def tobytes(self, _format):
            raise AssertionError("oversized pixels must not be encoded")

    class Page:
        rect = fitz.Rect(0, 0, 1, 1)

        def get_text(self, _kind):
            return ""

        def get_images(self, **_kwargs):
            return []

        def get_pixmap(self, **_kwargs):
            return Pixmap()

    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def load_page(self, _index):
            return Page()

    monkeypatch.setattr(media.fitz, "open", lambda **_kwargs: Document())
    result = _inspect_pdf(b"synthetic-pdf")

    assert result.units[0].issue_codes == ("unit-over-limit",)


def test_pdf_invalid_page_geometry_fails_closed_before_render(monkeypatch):
    import ctv_inspection_media as media

    class Rect:
        width = float("nan")
        height = 100

    class Page:
        rect = Rect()

        def get_text(self, _kind):
            return ""

        def get_images(self, **_kwargs):
            return []

        def get_pixmap(self, **_kwargs):
            raise AssertionError("invalid geometry must not be rendered")

    class Document:
        needs_pass = False
        page_count = 1

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def load_page(self, _index):
            return Page()

    monkeypatch.setattr(media.fitz, "open", lambda **_kwargs: Document())
    result = _inspect_pdf(b"synthetic-pdf")

    assert result.units[0].inspection_method == "none"
    assert result.units[0].issue_codes == ("unit-over-limit",)


@pytest.mark.parametrize(
    ("private_text", "expected_signals"),
    [
        (
            "CAN CUOC CONG DAN MAT TRUOC 079123456789",
            ("identity-front-heading", "identity-front-layout", "identity-number-pattern-present"),
        ),
        (
            "MAT SAU NGAY CAP CO QUAN CAP",
            ("identity-back-layout", "identity-issue-section-present"),
        ),
        ("van ban khong xac dinh", ()),
    ],
)
def test_image_ocr_reduces_identity_front_back_and_ambiguous_text(
    private_text, expected_signals
):
    result = _inspect_image(
        _image_bytes(), runner=RecordingOcr(OcrOutcome("succeeded", private_text))
    )
    unit = result.units[0]

    assert result.inspection_status == "inspected"
    assert result.unit_count == 1
    assert unit.unit_kind == "image"
    assert unit.unit_index == 1
    for signal in expected_signals:
        assert signal in unit.signal_codes
    if not expected_signals:
        assert unit.signal_codes == ("mostly-image-page",)


def test_corrupt_image_is_unreadable_without_a_fabricated_unit():
    result = _inspect_image(b"not an image: 079123456789 parser detail")

    assert result.inspection_status == "unreadable"
    assert result.unit_count is None
    assert result.source_issue_codes == ("document-unreadable",)
    assert result.units == ()
    assert "079123456789" not in repr(result)


def test_multiframe_image_uses_only_first_frame_and_adds_safe_issue():
    runner = RecordingOcr(OcrOutcome("succeeded", "MAT SAU NGAY CAP"))
    result = _inspect_image(_animated_gif(), runner=runner)

    assert result.unit_count == 1
    assert result.units[0].issue_codes == ("multi-frame-image",)
    assert len(runner.calls) == 1
    with Image.open(BytesIO(runner.calls[0][0])) as normalized:
        assert normalized.format == "PNG"
        assert normalized.mode == "RGB"
        assert normalized.getpixel((0, 0)) == (255, 0, 0)


def test_image_source_byte_boundary_is_exact_and_oversize_remains_one_known_unit():
    raw = _image_bytes()
    at_limit = raw + b"x" * (25 * 1024 * 1024 - len(raw))
    over_limit = at_limit + b"x"
    at_runner = RecordingOcr()
    over_runner = RecordingOcr()

    accepted = _inspect_image(at_limit, runner=at_runner)
    rejected = _inspect_image(over_limit, runner=over_runner)

    assert len(at_runner.calls) == 1
    assert accepted.units[0].issue_codes == ()
    assert len(over_runner.calls) == 0
    assert rejected.inspection_status == "inspected"
    assert rejected.unit_count == 1
    assert rejected.units[0].inspection_method == "none"
    assert rejected.units[0].issue_codes == ("unit-over-limit",)


@pytest.mark.parametrize(
    ("size", "loads"),
    [((10_000, 5_000), True), ((10_000, 5_001), False)],
)
def test_image_dimension_boundary_is_checked_from_header_before_pixel_load(
    monkeypatch, size, loads
):
    import ctv_inspection_media as media

    events = []

    class FakeImage:
        n_frames = 1
        mode = "RGB"

        def __init__(self):
            self.size = size

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def seek(self, frame):
            events.append(("seek", frame))

        def load(self):
            events.append(("load", None))

        def convert(self, mode):
            events.append(("convert", mode))
            return self

        def save(self, stream, *, format):
            events.append(("save", format))
            stream.write(_image_bytes())

        def close(self):
            events.append(("close", None))

    monkeypatch.setattr(media.Image, "open", lambda stream: FakeImage())
    result = _inspect_image(b"synthetic-image")

    assert (("load", None) in events) is loads
    assert result.units[0].issue_codes == (() if loads else ("unit-over-limit",))


@pytest.mark.parametrize("bomb_type", ["warning", "error"])
def test_image_catches_decompression_bombs_without_mutating_global_limit(
    monkeypatch, bomb_type
):
    import ctv_inspection_media as media

    original_limit = Image.MAX_IMAGE_PIXELS

    def bomb(_stream):
        exception_type = (
            Image.DecompressionBombWarning
            if bomb_type == "warning"
            else Image.DecompressionBombError
        )
        if bomb_type == "warning":
            warnings.warn("private dimensions 10000x10000", exception_type)
        raise exception_type("private dimensions 10000x10000")

    monkeypatch.setattr(media.Image, "open", bomb)
    result = _inspect_image(b"synthetic-image")

    assert Image.MAX_IMAGE_PIXELS == original_limit
    assert result.inspection_status == "inspected"
    assert result.unit_count == 1
    assert result.units[0].issue_codes == ("unit-over-limit",)
    assert "10000x10000" not in repr(result)


def test_image_maps_ocr_statuses_and_uses_shared_budget_sequentially():
    budget = OcrBudget(max_units=2)
    runner = RecordingOcr(OcrOutcome("timeout", ""))
    from ctv_inspection_media import inspect_image

    first = inspect_image(
        _image_bytes(), limits=InspectionLimits(), ocr_budget=budget, ocr_runner=runner
    )
    runner.outcome = OcrOutcome("failed", "")
    second = inspect_image(
        _image_bytes(), limits=InspectionLimits(), ocr_budget=budget, ocr_runner=runner
    )

    assert first.units[0].issue_codes == ("ocr-timeout",)
    assert second.units[0].issue_codes == ("ocr-failed",)
    assert [call[1] for call in runner.calls] == [budget, budget]
    assert budget.used_units == 2


def test_media_results_never_retain_private_content_or_diagnostics(monkeypatch):
    import ctv_inspection_media as media

    private_values = (
        PRIVATE_TEXT, "5.000.000", "13/08/2026", "612x792",
        "parser detail", repr(_image_bytes()),
    )
    pdf_result = _inspect_pdf(_pdf(
        "HOP DONG DICH VU BEN A BEN B CHU KY " + PRIVATE_TEXT
    ))
    image_result = _inspect_image(
        _image_bytes(), runner=RecordingOcr(OcrOutcome("succeeded", PRIVATE_TEXT))
    )
    public_surface = repr(dataclasses.asdict(pdf_result)) + repr(
        dataclasses.asdict(image_result)
    )

    for private_value in private_values:
        assert private_value not in public_surface


def test_media_adapters_perform_no_filesystem_temp_or_network_calls(monkeypatch):
    pdf = _pdf("HOP DONG DICH VU BEN A BEN B CHU KY noi dung du bo muoi ky tu")
    image = _image_bytes()

    def forbidden(*_args, **_kwargs):
        raise AssertionError("external I/O is forbidden")

    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(tempfile, "NamedTemporaryFile", forbidden)
    monkeypatch.setattr(tempfile, "TemporaryDirectory", forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)

    assert _inspect_pdf(pdf).unit_count == 1
    assert _inspect_image(image).unit_count == 1


def test_media_module_imports_only_approved_parser_and_project_modules():
    source = (__import__("pathlib").Path(__file__).with_name(
        "ctv_inspection_media.py"
    )).read_text(encoding="utf-8")
    imported_roots = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".")[0])

    forbidden = {
        "openpyxl", "zipfile", "tarfile", "rarfile", "pytesseract",
        "tempfile", "socket", "urllib", "requests", "subprocess",
    }
    assert not imported_roots & forbidden
    assert imported_roots <= {
        "__future__", "io", "math", "re", "warnings", "fitz", "PIL",
        "ctv_inspection_classifier", "ctv_inspection_model", "ctv_local_ocr",
    }
