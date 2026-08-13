import ast
import builtins
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import date
from io import BytesIO
import json
import os
from pathlib import Path
import re
import shutil
import socket
import stat
import subprocess
import tarfile
import tempfile
import zipfile

import fitz
from openpyxl import Workbook
from PIL import Image
import pytest

import ctv_inventory
from ctv_inspection import (
    INSPECTION_ERROR_CODES,
    InspectionError,
    inspect_source,
)
from ctv_inspection_media import PdfPageCountExceededError
from ctv_inspection_model import (
    InspectionAdapterResult,
    InspectionLimits,
    InspectionUnitEvidence,
)
from ctv_inspection_workbook import (
    WorkbookParserBoundaryExceededError,
    WorkbookWorksheetCountExceededError,
)
from ctv_inventory import InventoryError
from ctv_local_ocr import OcrOutcome


PRIVATE_IDENTITY = "079123456789"
PRIVATE_DATE = "13/08/2026"
PRIVATE_AMOUNT = "987654321"
PRIVATE_MEMBER = "private-member-079123456789.txt"
PRIVATE_SHEETS = (
    "Bảng kê riêng 079123456789",
    "Hỗ trợ ngày 13-08-2026",
)
PRIVATE_UNSUPPORTED = b"PRIVATE-UNSUPPORTED-079123456789"


def _pdf(*page_texts: str) -> bytes:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page(width=600, height=800)
        if text:
            page.insert_textbox(fitz.Rect(36, 36, 560, 760), text, fontsize=11)
    snapshot = document.tobytes()
    document.close()
    return snapshot


def _scanned_pdf() -> bytes:
    image_snapshot = _image()
    document = fitz.open()
    page = document.new_page(width=120, height=80)
    page.insert_image(page.rect, stream=image_snapshot)
    snapshot = document.tobytes()
    document.close()
    return snapshot


def _encrypted_pdf() -> bytes:
    document = fitz.open()
    document.new_page()
    output = BytesIO()
    document.save(
        output,
        encryption=fitz.PDF_ENCRYPT_AES_256,
        user_pw="synthetic-user-password",
        owner_pw="synthetic-owner-password",
    )
    document.close()
    return output.getvalue()


def _image(*, size=(120, 80), color=(245, 245, 245)) -> bytes:
    output = BytesIO()
    with Image.new("RGB", size, color) as image:
        image.save(output, format="PNG")
    return output.getvalue()


def _workbook() -> bytes:
    workbook = Workbook()
    roster = workbook.active
    roster.title = PRIVATE_SHEETS[0]
    roster.append(("DANH SACH CHI TRA", None, None))
    roster.append(("Ho ten", "Ma so nhan vien", "So tien"))
    roster.append((f"NGUYEN VAN KIEM THU {PRIVATE_IDENTITY}", "CTV-001", 1_250_000))
    roster.append(("NGUOI THU HAI", "CTV-002", date(2026, 8, 13)))
    supporting = workbook.create_sheet(PRIVATE_SHEETS[1])
    supporting.sheet_state = "hidden"
    supporting.append(("TAI LIEU KEM THEO", PRIVATE_DATE, PRIVATE_AMOUNT))
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _canonical_result(result) -> bytes:
    return (
        json.dumps(
            result.to_dict(),
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
        ).encode("utf-8")
        + b"\n"
    )


def _unavailable_ocr(monkeypatch) -> None:
    import ctv_inspection as inspection
    from ctv_local_ocr import open_local_ocr

    monkeypatch.setattr(
        inspection,
        "open_local_ocr",
        lambda: open_local_ocr(executable_lookup=lambda _name: None),
    )


def _write_end_to_end_tree(tmp_path: Path) -> tuple[Path, tuple[str, ...]]:
    source = tmp_path / f"Khách hàng riêng {PRIVATE_IDENTITY}"
    source.mkdir()
    (source / "a-mixed-private.pdf").write_bytes(
        _pdf(
            "HOP DONG DICH VU BEN A va BEN B NOI DUNG DICH VU CHU KY "
            "noi dung bo sung du dai de phan loai tai lieu mot cach on dinh.",
            "BIEN BAN NGHIEM THU THOI GIAN NGHIEM THU BEN A va BEN B CHU KY "
            "noi dung bo sung du dai de phan loai tai lieu mot cach on dinh.",
        )
    )
    (source / "b-roster-private.xlsx").write_bytes(_workbook())
    (source / f"c-identity-{PRIVATE_IDENTITY}.png").write_bytes(_image())
    (source / "d-opaque-private.zip").write_bytes(
        b"PK\x03\x04" + PRIVATE_MEMBER.encode("ascii") + b" PRIVATE ARCHIVE PAYLOAD"
    )
    (source / "e-disguised-private.pdf").write_bytes(
        b"Rar!\x1a\x07\x01\x00" + PRIVATE_MEMBER.encode("ascii")
    )
    (source / "f-unsupported-private.bin").write_bytes(PRIVATE_UNSUPPORTED)
    (source / "g-duplicate-private.dat").write_bytes(PRIVATE_UNSUPPORTED)
    outside = tmp_path / f"outside-private-{PRIVATE_IDENTITY}.pdf"
    outside.write_bytes(b"%PDF-1.7\noutside private target")
    (source / "h-private-link.pdf").symlink_to(outside)
    os.mkfifo(source / "i-private-special.xlsx")
    forbidden = (
        str(tmp_path),
        source.name,
        *(entry.name for entry in source.iterdir()),
        *PRIVATE_SHEETS,
        PRIVATE_IDENTITY,
        PRIVATE_DATE,
        PRIVATE_AMOUNT,
        PRIVATE_MEMBER,
        PRIVATE_UNSUPPORTED.decode("ascii"),
    )
    return source, forbidden


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are unavailable")
def test_mixed_folder_is_fully_accounted_in_evidence_and_unit_order(
    tmp_path, monkeypatch
):
    import ctv_inspection as inspection

    source, forbidden = _write_end_to_end_tree(tmp_path)
    sessions = []
    observations = []
    real_observation = inspection.open_inventory_observation

    def open_ocr():
        session = object()
        sessions.append(session)
        return session

    def synthetic_ocr(_image_bytes, *, session, budget, timeout_seconds):
        assert session is sessions[-1]
        assert timeout_seconds == 30
        budget.used_units += 1
        return OcrOutcome(
            "succeeded",
            f"CAN CUOC CONG DAN MAT TRUOC {PRIVATE_IDENTITY}",
        )

    @contextmanager
    def recording_observation(*args, **kwargs):
        with real_observation(*args, **kwargs) as observation:
            observations.append(observation)
            yield observation

    monkeypatch.setattr(inspection, "open_local_ocr", open_ocr)
    monkeypatch.setattr(inspection, "run_local_ocr", synthetic_ocr)
    monkeypatch.setattr(inspection, "open_inventory_observation", recording_observation)

    first = inspect_source(source)
    second = inspect_source(source)

    assert first.to_dict() == second.to_dict()
    assert _canonical_result(first) == _canonical_result(second)
    assert len(sessions) == 2
    assert len(observations) == 2
    assert observations[0] is not observations[1]
    assert [item.evidence_id for item in first.sources] == [
        f"evidence-{index:04d}" for index in range(1, 10)
    ]
    assert [unit.unit_id for unit in first.units] == [
        f"unit-{index:04d}" for index in range(1, 6)
    ]
    assert [
        (unit.evidence_id, unit.unit_kind, unit.unit_index)
        for unit in first.units
    ] == [
        ("evidence-0001", "pdf-page", 1),
        ("evidence-0001", "pdf-page", 2),
        ("evidence-0002", "worksheet", 1),
        ("evidence-0002", "worksheet", 2),
        ("evidence-0003", "image", 1),
    ]
    assert [unit.suggested_role for unit in first.units] == [
        "service-contract",
        "acceptance-record",
        "payment-roster",
        "other-supporting-evidence",
        "identity-front",
    ]
    assert first.inspection_status == "complete-with-issues"
    assert first.totals.to_dict() == {
        "sources": 9,
        "units": 5,
        "classified": 5,
        "unknown": 0,
        "needsUserReview": 1,
        "issues": 8,
    }
    assert [source_record.inspection_status for source_record in first.sources] == [
        "inspected",
        "inspected",
        "inspected",
        "opaque",
        "opaque",
        "unsupported",
        "unsupported",
        "not-applicable",
        "not-applicable",
    ]
    assert first.sources[3].issue_codes == ("opaque-archive",)
    assert first.sources[4].issue_codes == (
        "type-extension-mismatch",
        "opaque-archive",
    )
    assert all(source_record.unit_count == 0 for source_record in first.sources[3:])
    public = "\n".join(
        (
            json.dumps(first.to_dict(), ensure_ascii=False),
            repr(first),
            repr(first.sources),
            repr(first.units),
        )
    )
    for private in forbidden:
        assert private not in public


def test_safe_folder_mutation_rebinds_observation_and_evidence_ids(tmp_path, monkeypatch):
    _unavailable_ocr(monkeypatch)
    source = tmp_path / "private-source"
    source.mkdir()
    (source / "z-contract.pdf").write_bytes(
        _pdf(
            "HOP DONG DICH VU BEN A va BEN B NOI DUNG DICH VU CHU KY "
            "noi dung bo sung du dai de phan loai tai lieu mot cach on dinh."
        )
    )

    before = inspect_source(source)
    (source / "a-new.bin").write_bytes(b"new unsupported evidence")
    after = inspect_source(source)

    assert before.inspection_status == "complete"
    assert before.totals.to_dict() == {
        "sources": 1,
        "units": 1,
        "classified": 1,
        "unknown": 0,
        "needsUserReview": 0,
        "issues": 0,
    }
    assert after.inspection_status == "complete-with-issues"
    assert after.totals.issues == 1
    assert before.observation_id != after.observation_id
    assert before.units[0].evidence_id == "evidence-0001"
    assert after.units[0].evidence_id == "evidence-0002"
    assert [record.evidence_id for record in after.sources] == [
        "evidence-0001",
        "evidence-0002",
    ]


def test_source_failures_and_exact_source_caps_are_honestly_accounted(
    tmp_path, monkeypatch
):
    _unavailable_ocr(monkeypatch)
    source = tmp_path / "private-source"
    source.mkdir()
    corrupt_pdf = b"%PDF-1.7\ncorrupt bounded private content"
    corrupt_workbook = b"PK\x03\x04[Content_Types].xml xl/workbook.xml private"
    encrypted_pdf = _encrypted_pdf()
    valid_pdf = _pdf("bounded private pdf") + b"\n" + b"x" * len(encrypted_pdf)
    valid_workbook = _workbook()
    valid_image = _image()
    (source / "a-corrupt.pdf").write_bytes(corrupt_pdf)
    (source / "b-encrypted.pdf").write_bytes(encrypted_pdf)
    (source / "c-false-positive.xlsx").write_bytes(corrupt_workbook)
    (source / "d-over.pdf").write_bytes(valid_pdf)
    (source / "e-over.xlsx").write_bytes(valid_workbook)
    (source / "f-over.png").write_bytes(valid_image)
    (source / "g-unsupported.bin").write_bytes(b"unsupported private")
    limits = InspectionLimits(
        max_pdf_source_bytes=len(valid_pdf) - 1,
        max_workbook_source_bytes=len(valid_workbook) - 1,
        max_image_source_bytes=len(valid_image) - 1,
    )

    result = inspect_source(source, limits=limits)

    assert [record.inspection_status for record in result.sources] == [
        "unreadable",
        "encrypted",
        "unreadable",
        "over-limit",
        "over-limit",
        "inspected",
        "unsupported",
    ]
    assert [record.unit_count for record in result.sources] == [
        None,
        None,
        None,
        None,
        None,
        1,
        0,
    ]
    assert result.sources[0].issue_codes == ("document-unreadable",)
    assert result.sources[1].issue_codes == ("document-encrypted",)
    assert result.sources[2].issue_codes == ("document-unreadable",)
    assert result.sources[3].issue_codes == ("document-over-limit",)
    assert result.sources[4].issue_codes == ("document-over-limit",)
    assert result.sources[5].issue_codes == ()
    assert result.sources[6].issue_codes == ("unsupported-document-type",)
    assert len(result.units) == 1
    assert result.units[0].unit_kind == "image"
    assert result.units[0].inspection_method == "none"
    assert result.units[0].suggested_role == "unknown"
    assert result.units[0].confidence_band == "none"
    assert result.units[0].issue_codes == (
        "unit-over-limit",
        "classification-ambiguous",
    )


def test_one_ocr_session_precedes_observation_and_one_budget_is_sequential(
    tmp_path, monkeypatch
):
    import ctv_inspection as inspection

    source = tmp_path / "source"
    source.mkdir()
    (source / "a-scanned.pdf").write_bytes(_scanned_pdf())
    (source / "b-image.png").write_bytes(_image())
    events = []
    calls = []
    session = object()
    real_observation = inspection.open_inventory_observation

    def open_ocr():
        events.append("ocr-open")
        return session

    @contextmanager
    def recording_observation(*args, **kwargs):
        events.append("observation-open")
        with real_observation(*args, **kwargs) as observation:
            yield observation

    def recording_ocr(_image_bytes, *, session: object, budget, timeout_seconds):
        calls.append((session, id(budget), budget.used_units, timeout_seconds))
        budget.used_units += 1
        return OcrOutcome(
            "succeeded",
            f"CAN CUOC CONG DAN MAT TRUOC {PRIVATE_IDENTITY}",
        )

    monkeypatch.setattr(inspection, "open_local_ocr", open_ocr)
    monkeypatch.setattr(inspection, "open_inventory_observation", recording_observation)
    monkeypatch.setattr(inspection, "run_local_ocr", recording_ocr)

    result = inspect_source(source)

    assert events == ["ocr-open", "observation-open"]
    assert len(calls) == 2
    assert [call[0] for call in calls] == [session, session]
    assert len({call[1] for call in calls}) == 1
    assert [call[2] for call in calls] == [0, 1]
    assert [call[3] for call in calls] == [30, 30]
    assert [unit.evidence_id for unit in result.units] == [
        "evidence-0001",
        "evidence-0002",
    ]


def test_adapter_evidence_is_reclassified_and_preserves_derived_signals(
    tmp_path, monkeypatch
):
    import ctv_inspection as inspection

    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.pdf").write_bytes(_pdf("private"))
    adapter = InspectionAdapterResult(
        "inspected",
        1,
        (),
        (
            InspectionUnitEvidence(
                "pdf-page",
                1,
                "embedded-text",
                (
                    "service-contract-heading",
                    "party-section-present",
                    "signature-section-present",
                    "acceptance-heading",
                ),
                (),
            ),
        ),
    )
    monkeypatch.setattr(inspection, "inspect_pdf", lambda *_args, **_kwargs: adapter)

    result = inspect_source(source)

    assert result.units[0].suggested_role == "unknown"
    assert result.units[0].confidence_band == "none"
    assert result.units[0].needs_user_review is True
    assert result.units[0].signal_codes == (
        "service-contract-heading",
        "party-section-present",
        "signature-section-present",
        "acceptance-heading",
        "multiple-role-signals",
    )
    assert result.units[0].issue_codes == ("classification-conflict",)


@pytest.mark.parametrize(
    ("filename", "content", "adapter_name", "adapter_error", "expected"),
    [
        (
            "private.pdf",
            b"%PDF-1.7\nprivate",
            "inspect_pdf",
            PdfPageCountExceededError,
            "inspection-pdf-page-count-exceeded",
        ),
        (
            "private.xlsx",
            _workbook(),
            "inspect_workbook",
            WorkbookParserBoundaryExceededError,
            "inspection-parser-boundary-exceeded",
        ),
        (
            "private.xlsx",
            _workbook(),
            "inspect_workbook",
            WorkbookWorksheetCountExceededError,
            "inspection-worksheet-count-exceeded",
        ),
    ],
)
def test_adapter_enumeration_boundaries_fail_with_exact_operation_codes(
    tmp_path,
    monkeypatch,
    filename,
    content,
    adapter_name,
    adapter_error,
    expected,
):
    import ctv_inspection as inspection

    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / filename).write_bytes(content)

    def fail(*_args, **_kwargs):
        raise adapter_error()

    monkeypatch.setattr(inspection, adapter_name, fail)

    with pytest.raises(InspectionError) as raised:
        inspect_source(source)

    assert raised.value.code == expected
    assert str(raised.value) == expected


def test_unit_limit_is_enforced_before_append_even_with_forged_relaxed_limits(
    tmp_path, monkeypatch
):
    import ctv_inspection as inspection

    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "a-private.pdf").write_bytes(b"%PDF-1.7\nprivate")
    (source / "b-private.png").write_bytes(_image())
    ten_thousand = tuple(
        InspectionUnitEvidence("pdf-page", index, "none", (), ())
        for index in range(1, 10_001)
    )
    monkeypatch.setattr(
        inspection,
        "inspect_pdf",
        lambda *_args, **_kwargs: InspectionAdapterResult(
            "inspected", 10_000, (), ten_thousand
        ),
    )
    monkeypatch.setattr(
        inspection,
        "inspect_image",
        lambda *_args, **_kwargs: InspectionAdapterResult(
            "inspected",
            1,
            (),
            (InspectionUnitEvidence("image", 1, "none", (), ()),),
        ),
    )
    forged = InspectionLimits()
    object.__setattr__(forged, "max_units", 20_000)

    with pytest.raises(InspectionError) as raised:
        inspect_source(source, limits=forged)

    assert str(raised.value) == "inspection-unit-count-exceeded"


def test_result_output_limit_fails_closed_without_returning_partial_result(
    tmp_path, monkeypatch
):
    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.bin").write_bytes(b"private")

    with pytest.raises(InspectionError) as raised:
        inspect_source(source, limits=InspectionLimits(max_json_bytes=1))

    assert str(raised.value) == "inspection-output-too-large"


def test_snapshot_failure_maps_to_tree_changed_without_private_diagnostics(
    tmp_path, monkeypatch
):
    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.pdf").write_bytes(b"%PDF-1.7\nprivate")

    def fail_snapshot(self, evidence_id, *, max_bytes):
        raise InventoryError("inventory-tree-changed")

    monkeypatch.setattr(ctv_inventory.InventoryObservation, "snapshot", fail_snapshot)

    with pytest.raises(InspectionError) as raised:
        inspect_source(source)

    assert str(raised.value) == "inspection-tree-changed"
    assert "private" not in repr(raised.value)


def test_hash_read_failure_remains_an_accounted_unreadable_source(
    tmp_path, monkeypatch
):
    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.pdf").write_bytes(b"%PDF-1.7\nprivate bounded content")

    def fail_hash(*_args, **_kwargs):
        raise ctv_inventory._HashReadFailed()

    monkeypatch.setattr(ctv_inventory, "_stream_hash", fail_hash)

    result = inspect_source(source)

    assert len(result.sources) == 1
    assert result.sources[0].detected_type == "unknown"
    assert result.sources[0].inspection_status == "unreadable"
    assert result.sources[0].unit_count is None
    assert result.sources[0].issue_codes == (
        "unreadable",
        "document-unreadable",
    )
    assert result.units == ()


def test_mutation_during_adapter_work_invalidates_the_whole_result(
    tmp_path, monkeypatch
):
    import ctv_inspection as inspection

    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    private_file = source / "private.pdf"
    private_file.write_bytes(
        _pdf(
            "HOP DONG DICH VU BEN A va BEN B NOI DUNG DICH VU CHU KY "
            "noi dung bo sung du dai de phan loai tai lieu mot cach on dinh."
        )
    )
    real_adapter = inspection.inspect_pdf

    def mutating_adapter(snapshot, **kwargs):
        result = real_adapter(snapshot, **kwargs)
        private_file.write_bytes(snapshot + b"\n")
        return result

    monkeypatch.setattr(inspection, "inspect_pdf", mutating_adapter)

    with pytest.raises(InspectionError) as raised:
        inspect_source(source)

    assert str(raised.value) == "inspection-tree-changed"


def test_mutation_at_observation_exit_invalidates_the_whole_result(
    tmp_path, monkeypatch
):
    import ctv_inspection as inspection

    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    private_file = source / "private.bin"
    private_file.write_bytes(b"private")
    real_observation = inspection.open_inventory_observation

    @contextmanager
    def mutate_before_final_revalidation(*args, **kwargs):
        with real_observation(*args, **kwargs) as observation:
            try:
                yield observation
            finally:
                private_file.write_bytes(b"changed")

    monkeypatch.setattr(
        inspection,
        "open_inventory_observation",
        mutate_before_final_revalidation,
    )

    with pytest.raises(InspectionError) as raised:
        inspect_source(source)

    assert str(raised.value) == "inspection-tree-changed"


def _tree_state(source: Path):
    state = {}
    for root, directories, files in os.walk(source, followlinks=False):
        root_path = Path(root)
        for name in sorted((*directories, *files)):
            path = root_path / name
            metadata = path.lstat()
            relative = os.fspath(path.relative_to(source))
            content = path.read_bytes() if stat.S_ISREG(metadata.st_mode) else None
            state[relative] = (
                stat.S_IFMT(metadata.st_mode),
                stat.S_IMODE(metadata.st_mode),
                metadata.st_size,
                metadata.st_mtime_ns,
                content,
            )
    return state


def _poison_mutation_network_shell_and_extraction(monkeypatch):
    original_os_open = os.open
    supported_dir_fd = set(os.supports_dir_fd)
    write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

    def read_only_os_open(path, flags, *args, **kwargs):
        assert flags & write_flags == 0
        return original_os_open(path, flags, *args, **kwargs)

    def forbidden(*_args, **_kwargs):
        raise AssertionError("inspection invoked a forbidden side effect")

    monkeypatch.setattr(os, "open", read_only_os_open)
    supported_dir_fd.discard(original_os_open)
    supported_dir_fd.add(read_only_os_open)
    monkeypatch.setattr(os, "supports_dir_fd", supported_dir_fd)
    monkeypatch.setattr(builtins, "open", forbidden)
    monkeypatch.setattr(os, "write", forbidden)
    for name in ("mkdir", "makedirs", "rename", "replace", "unlink", "remove"):
        monkeypatch.setattr(os, name, forbidden)
    for name in ("write_bytes", "write_text", "mkdir", "rename", "replace", "unlink", "touch"):
        monkeypatch.setattr(Path, name, forbidden)
    for name in (
        "NamedTemporaryFile",
        "TemporaryFile",
        "TemporaryDirectory",
        "mkstemp",
        "mkdtemp",
    ):
        monkeypatch.setattr(tempfile, name, forbidden)
    monkeypatch.setattr(socket, "socket", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    for name in ("Popen", "run", "call", "check_call", "check_output"):
        monkeypatch.setattr(subprocess, name, forbidden)
    monkeypatch.setattr(os, "system", forbidden)
    monkeypatch.setattr(os, "popen", forbidden)
    monkeypatch.setattr(shutil, "unpack_archive", forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extract", forbidden)
    monkeypatch.setattr(zipfile.ZipFile, "extractall", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extract", forbidden)
    monkeypatch.setattr(tarfile.TarFile, "extractall", forbidden)


@pytest.mark.parametrize("fail_output", [False, True])
def test_success_and_controlled_failure_never_write_or_mutate_source(
    tmp_path, monkeypatch, fail_output
):
    import ctv_inspection as inspection
    from ctv_local_ocr import open_local_ocr

    source = tmp_path / "source"
    source.mkdir()
    (source / "a-private.pdf").write_bytes(
        _pdf(
            "HOP DONG DICH VU BEN A va BEN B NOI DUNG DICH VU CHU KY "
            "noi dung bo sung du dai de phan loai tai lieu mot cach on dinh."
        )
    )
    (source / "b-private.xlsx").write_bytes(_workbook())
    (source / "c-private.png").write_bytes(_image())
    (source / "d-private.zip").write_bytes(
        b"PK\x03\x04" + PRIVATE_MEMBER.encode("ascii")
    )
    before = _tree_state(source)
    monkeypatch.setattr(
        inspection,
        "open_local_ocr",
        lambda: open_local_ocr(executable_lookup=lambda _name: None),
    )
    _poison_mutation_network_shell_and_extraction(monkeypatch)

    if fail_output:
        with pytest.raises(InspectionError) as raised:
            inspect_source(source, limits=InspectionLimits(max_json_bytes=1))
        assert str(raised.value) == "inspection-output-too-large"
    else:
        inspect_source(source)

    assert _tree_state(source) == before


def test_unchanged_concurrent_calls_are_isolated_and_byte_identical(
    tmp_path, monkeypatch
):
    _unavailable_ocr(monkeypatch)
    source = tmp_path / "source"
    source.mkdir()
    (source / "private.pdf").write_bytes(
        _pdf(
            "HOP DONG DICH VU BEN A va BEN B NOI DUNG DICH VU CHU KY "
            "noi dung bo sung du dai de phan loai tai lieu mot cach on dinh."
        )
    )

    with ThreadPoolExecutor(max_workers=4) as executor:
        outputs = list(
            executor.map(
                lambda _index: _canonical_result(inspect_source(source)),
                range(8),
            )
        )

    assert len(set(outputs)) == 1


@pytest.mark.parametrize(
    "inventory_code",
    [
        "inventory-depth-exceeded",
        "inventory-directory-count-exceeded",
        "inventory-directory-unreadable",
        "inventory-entry-count-exceeded",
        "inventory-entry-unsafe",
        "inventory-item-count-exceeded",
        "inventory-output-too-large",
        "inventory-regular-file-count-exceeded",
        "inventory-tree-changed",
        "secure-open-unavailable",
        "source-root-missing",
        "source-root-unsafe",
    ],
)
def test_inventory_operation_errors_are_retained_or_mapped_exactly(
    tmp_path, monkeypatch, inventory_code
):
    import ctv_inspection as inspection

    _unavailable_ocr(monkeypatch)

    @contextmanager
    def fail_inventory(*_args, **_kwargs):
        raise InventoryError(inventory_code)
        yield

    monkeypatch.setattr(inspection, "open_inventory_observation", fail_inventory)
    expected = (
        "inspection-tree-changed"
        if inventory_code == "inventory-tree-changed"
        else inventory_code
    )

    with pytest.raises(InspectionError) as raised:
        inspect_source(tmp_path)

    assert raised.value.code == expected
    assert str(raised.value) == expected
    assert raised.value.args == (expected,)


def test_inspection_error_surface_is_exact_allowlisted_and_private_safe():
    assert INSPECTION_ERROR_CODES == (
        "inspection-output-too-large",
        "inspection-parser-boundary-exceeded",
        "inspection-pdf-page-count-exceeded",
        "inspection-tree-changed",
        "inspection-unit-count-exceeded",
        "inspection-worksheet-count-exceeded",
        "inventory-depth-exceeded",
        "inventory-directory-count-exceeded",
        "inventory-directory-unreadable",
        "inventory-entry-count-exceeded",
        "inventory-entry-unsafe",
        "inventory-item-count-exceeded",
        "inventory-output-too-large",
        "inventory-regular-file-count-exceeded",
        "secure-open-unavailable",
        "source-root-missing",
        "source-root-unsafe",
    )
    assert tuple(sorted(INSPECTION_ERROR_CODES)) == INSPECTION_ERROR_CODES
    assert all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", code) for code in INSPECTION_ERROR_CODES)
    for code in INSPECTION_ERROR_CODES:
        error = InspectionError(code)
        assert error.code == code
        assert str(error) == code
        assert error.args == (code,)

    private_code = "private/path/079123456789"
    with pytest.raises(ValueError) as raised:
        InspectionError(private_code)
    assert private_code not in str(raised.value)


def test_orchestrator_imports_no_write_network_shell_or_archive_helpers():
    module_path = Path(__file__).with_name("ctv_inspection.py")
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    imported_roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "tempfile",
            "socket",
            "subprocess",
            "zipfile",
            "tarfile",
            "shutil",
            "requests",
            "httpx",
            "urllib",
            "pytesseract",
        }
    )
