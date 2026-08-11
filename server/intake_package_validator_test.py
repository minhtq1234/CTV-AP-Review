import hashlib
import json
from pathlib import Path

import fitz
import openpyxl
import pytest


SYNTHETIC_TIMESTAMP = "2026-08-11T00:00:00Z"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_pdf(path: Path, page_count: int = 2) -> None:
    document = fitz.open()
    try:
        for page_number in range(1, page_count + 1):
            page = document.new_page()
            page.insert_text((72, 72), f"Synthetic page {page_number}")
        document.save(path)
    finally:
        document.close()


def _write_roster(
    path: Path,
    *,
    title: str = "Roster",
    headers: tuple[str, ...] = ("Display label", "Synthetic identity"),
    rows: tuple[tuple[str, ...], ...] = (
        ("SUBJECT-ALPHA", "SYNTHETIC-IDENTITY-A"),
        ("SUBJECT-BETA", "SYNTHETIC-IDENTITY-B"),
    ),
) -> None:
    workbook = openpyxl.Workbook()
    try:
        worksheet = workbook.active
        worksheet.title = title
        worksheet.append(headers)
        for row in rows:
            worksheet.append(row)
        workbook.save(path)
    finally:
        workbook.close()


def _artifact(artifact_id: str, kind: str, path: Path, source_ids: list[str]) -> dict:
    return {
        "artifactId": artifact_id,
        "kind": kind,
        "path": path.name,
        "size": path.stat().st_size,
        "sha256": _sha256(path),
        "sourceIds": source_ids,
    }


def _write_package(
    package_dir: Path,
    *,
    status: str = "prepared",
    exception_items: list[dict] | None = None,
) -> dict:
    package_dir.mkdir()
    pdf_path = package_dir / "input.pdf"
    roster_path = package_dir / "roster.xlsx"
    exceptions_path = package_dir / "exceptions.json"
    _write_pdf(pdf_path)
    _write_roster(roster_path)
    exceptions_path.write_text(
        json.dumps({"schemaVersion": "1.0", "items": exception_items or []}),
        encoding="utf-8",
    )
    manifest = {
        "schemaVersion": "1.0",
        "batchId": "batch-synthetic",
        "caseId": "case-synthetic",
        "faCode": None,
        "packageVersion": "1.0",
        "status": status,
        "compatibilityTarget": "ctv-intake-v1",
        "sources": [
            {
                "sourceId": "source-pdf",
                "path": "workspace/source.pdf",
                "mediaType": "application/pdf",
                "pageCount": 2,
                "size": pdf_path.stat().st_size,
                "sha256": _sha256(pdf_path),
                "coverageState": "assigned",
            },
            {
                "sourceId": "source-roster",
                "path": "workspace/source.xlsx",
                "mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size": roster_path.stat().st_size,
                "sha256": _sha256(roster_path),
                "coverageState": "assigned",
            },
        ],
        "pdfPages": [
            {
                "sourceId": "source-pdf",
                "sourcePage": 1,
                "coverageState": "assigned",
                "targetPage": 1,
            },
            {
                "sourceId": "source-pdf",
                "sourcePage": 2,
                "coverageState": "assigned",
                "targetPage": 2,
            },
        ],
        "artifacts": [
            _artifact("artifact-pdf", "input-pdf", pdf_path, ["source-pdf"]),
            _artifact("artifact-roster", "roster", roster_path, ["source-roster"]),
            _artifact("artifact-exceptions", "exceptions", exceptions_path, []),
        ],
        "rosterMapping": {
            "sourceId": "source-roster",
            "sheetName": "Roster",
            "canonicalToSourceColumns": {
                "name": "Display label",
                "identity": "Synthetic identity",
            },
        },
        "decisions": [],
        "exceptionIds": [item["exceptionId"] for item in exception_items or []],
        "validatedAt": SYNTHETIC_TIMESTAMP,
        "validatorVersion": "1.0.0",
    }
    _save_manifest(package_dir, manifest)
    return manifest


def _save_manifest(package_dir: Path, manifest: dict) -> None:
    (package_dir / "case-manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )


def _refresh_artifact(package_dir: Path, manifest: dict, kind: str) -> None:
    artifact = next(item for item in manifest["artifacts"] if item["kind"] == kind)
    path = package_dir / artifact["path"]
    artifact["size"] = path.stat().st_size
    artifact["sha256"] = _sha256(path)
    _save_manifest(package_dir, manifest)


def _add_artifact(
    package_dir: Path,
    manifest: dict,
    *,
    artifact_id: str,
    kind: str,
    filename: str,
    content: bytes,
) -> None:
    path = package_dir / filename
    path.write_bytes(content)
    manifest["artifacts"].append(_artifact(artifact_id, kind, path, []))
    _save_manifest(package_dir, manifest)


def _historical_validation_report() -> dict:
    return {
        "schemaVersion": "1.0",
        "outcome": "invalid",
        "packageStatus": "partially_prepared",
        "checks": [
            {
                "code": "historical-check",
                "passed": False,
                "evidenceRefs": ["historical-synthetic-evidence"],
            }
        ],
        "errors": ["historical-check"],
        "warnings": [],
        "validatedAt": SYNTHETIC_TIMESTAMP,
        "validatorVersion": "0.9.0",
    }


def _validate(package_dir: Path):
    from intake_package_validator import validate_package

    return validate_package(package_dir)


def _check(report, code: str):
    return next(check for check in report.checks if check.code == code)


def test_valid_prepared_package_passes_semantic_validation(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(package_dir)

    report = _validate(package_dir)

    assert report.outcome == "valid"
    assert report.package_status == "prepared"
    assert report.errors == []
    assert report.warnings == []
    assert report.validator_version == "1.0.0"


def test_missing_required_artifact_is_rejected(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["artifacts"] = [
        artifact for artifact in manifest["artifacts"] if artifact["kind"] != "roster"
    ]
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "missing-required-artifact" in report.errors
    assert _check(report, "missing-required-artifact").evidence_refs == ["roster"]


def test_duplicate_kind_is_not_snapshotted_while_unaffected_sibling_is_validated(
    tmp_path, monkeypatch
):
    import intake_package_validator as validator

    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    input_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["kind"] == "input-pdf"
    )
    duplicate_ids = [
        "artifact-pdf",
        "artifact-pdf-01",
        "artifact-pdf-02",
        "artifact-pdf-03",
        "artifact-pdf-04",
        "artifact-pdf-05",
        "artifact-pdf-06",
        "artifact-pdf-07",
        "artifact-pdf-08",
    ]
    manifest["artifacts"].extend(
        {**input_artifact, "artifactId": artifact_id}
        for artifact_id in duplicate_ids[1:]
    )
    (package_dir / "roster.xlsx").write_bytes(b"not a workbook")
    _refresh_artifact(package_dir, manifest, "roster")
    real_os_open = validator.os.open

    def reject_duplicate_snapshot(path, flags, mode=0o777, *, dir_fd=None):
        if path == "input.pdf":
            pytest.fail("a declaration from a duplicate artifact kind was opened")
        return real_os_open(path, flags, mode, dir_fd=dir_fd)

    def reject_duplicate_parser(*_args, **_kwargs):
        pytest.fail("a declaration from a duplicate artifact kind was parsed")

    monkeypatch.setattr(validator.os, "open", reject_duplicate_snapshot)
    monkeypatch.setattr(validator.fitz, "open", reject_duplicate_parser)

    first = validator.validate_package(package_dir)
    second = validator.validate_package(package_dir)

    assert first.errors == ["duplicate-artifact-kind", "roster-unreadable"]
    assert _check(first, "duplicate-artifact-kind").evidence_refs == duplicate_ids
    assert first.model_dump(exclude={"validated_at"}) == second.model_dump(
        exclude={"validated_at"}
    )


def test_byte_size_mismatch_is_rejected_before_digesting_or_reading(
    tmp_path, monkeypatch
):
    import intake_package_validator as validator

    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    pdf_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["kind"] == "input-pdf"
    )
    pdf_path = package_dir / pdf_artifact["path"]
    pdf_inode = pdf_path.stat().st_ino
    with pdf_path.open("r+b") as stream:
        stream.truncate(2 * 1024 * 1024)
    real_fdopen = validator.os.fdopen

    def reject_artifact_stream_read(file_descriptor, *args, **kwargs):
        if validator.os.fstat(file_descriptor).st_ino == pdf_inode:
            pytest.fail("size-mismatched artifact content was opened for reading")
        return real_fdopen(file_descriptor, *args, **kwargs)

    monkeypatch.setattr(validator.os, "fdopen", reject_artifact_stream_read)
    _save_manifest(package_dir, manifest)

    report = validator.validate_package(package_dir)

    assert "artifact-size-mismatch" in report.errors
    assert "artifact-digest-mismatch" not in report.errors
    assert _check(report, "artifact-size-mismatch").evidence_refs == ["artifact-pdf"]


def test_digest_mismatch_is_rejected_when_declared_size_matches(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    pdf_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["kind"] == "input-pdf"
    )
    pdf_artifact["sha256"] = "f" * 64
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "artifact-size-mismatch" not in report.errors
    assert "artifact-digest-mismatch" in report.errors


def test_artifact_over_the_absolute_kind_limit_is_rejected_before_reading(tmp_path):
    import intake_package_validator as validator

    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    pdf_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["kind"] == "input-pdf"
    )
    pdf_path = package_dir / pdf_artifact["path"]
    hard_limit = validator.MAX_ARTIFACT_BYTES_BY_KIND["input-pdf"]
    with pdf_path.open("r+b") as stream:
        stream.truncate(hard_limit + 1)
    pdf_artifact["size"] = hard_limit + 1
    pdf_artifact["sha256"] = "f" * 64
    _save_manifest(package_dir, manifest)

    report = validator.validate_package(package_dir)

    assert "artifact-too-large" in report.errors
    assert "artifact-size-mismatch" not in report.errors
    assert "artifact-digest-mismatch" not in report.errors
    assert "pdf-unreadable" not in report.errors


def test_artifact_appended_after_fstat_is_bounded_and_rejected(tmp_path, monkeypatch):
    import intake_package_validator as validator

    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    pdf_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["kind"] == "input-pdf"
    )
    pdf_path = package_dir / pdf_artifact["path"]
    pdf_inode = pdf_path.stat().st_ino
    accepted_limit = pdf_path.stat().st_size + 16
    monkeypatch.setitem(
        validator.MAX_ARTIFACT_BYTES_BY_KIND, "input-pdf", accepted_limit
    )
    real_fdopen = validator.os.fdopen
    appended = False

    def append_before_read(file_descriptor, *args, **kwargs):
        nonlocal appended
        if not appended and validator.os.fstat(file_descriptor).st_ino == pdf_inode:
            with pdf_path.open("ab") as stream:
                stream.write(b"X" * 32)
            appended = True
        return real_fdopen(file_descriptor, *args, **kwargs)

    monkeypatch.setattr(validator.os, "fdopen", append_before_read)

    report = validator.validate_package(package_dir)

    assert appended
    assert "artifact-too-large" in report.errors
    assert "artifact-size-mismatch" not in report.errors
    assert "artifact-digest-mismatch" not in report.errors
    assert "pdf-unreadable" not in report.errors


def test_missing_and_extra_pdf_page_coverage_are_reported(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["pdfPages"] = [
        manifest["pdfPages"][0],
        {
            "sourceId": "source-pdf",
            "sourcePage": 3,
            "coverageState": "assigned",
            "targetPage": 2,
        },
    ]
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "page-coverage-missing" in report.errors
    assert "page-coverage-extra" in report.errors
    assert _check(report, "page-coverage-missing").evidence_refs == [
        "source-pdf#page=2"
    ]
    assert _check(report, "page-coverage-extra").evidence_refs == [
        "source-pdf#page=3"
    ]


def test_pdf_source_requires_a_declared_page_count(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["sources"][0].pop("pageCount")
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "page-coverage-missing" in report.errors
    assert _check(report, "page-coverage-missing").evidence_refs == [
        "source-pdf#page-count"
    ]


def test_each_pdf_source_uses_its_own_page_count_in_a_merged_input_pdf(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    _write_pdf(package_dir / "input.pdf", page_count=3)
    _refresh_artifact(package_dir, manifest, "input-pdf")
    manifest["sources"].append(
        {
            "sourceId": "source-pdf-secondary",
            "path": "workspace/source-secondary.pdf",
            "mediaType": "application/pdf",
            "pageCount": 1,
            "size": 1,
            "sha256": "e" * 64,
            "coverageState": "assigned",
        }
    )
    input_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["kind"] == "input-pdf"
    )
    input_artifact["sourceIds"].append("source-pdf-secondary")
    manifest["pdfPages"].append(
        {
            "sourceId": "source-pdf-secondary",
            "sourcePage": 1,
            "coverageState": "assigned",
            "targetPage": 3,
        }
    )
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert report.outcome == "valid"
    assert report.errors == []


@pytest.mark.parametrize(
    ("target_pages", "missing_evidence", "extra_evidence"),
    [
        ((1, 1), "artifact-pdf#target-page=2", "artifact-pdf#target-page=1"),
        ((1, 3), "artifact-pdf#target-page=2", "artifact-pdf#target-page=3"),
    ],
)
def test_derived_pdf_target_pages_must_be_covered_exactly_once(
    tmp_path, target_pages, missing_evidence, extra_evidence
):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    for page, target_page in zip(manifest["pdfPages"], target_pages, strict=True):
        page["targetPage"] = target_page
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert missing_evidence in _check(report, "page-coverage-missing").evidence_refs
    assert extra_evidence in _check(report, "page-coverage-extra").evidence_refs


@pytest.mark.parametrize(
    ("relationship", "expected_evidence"),
    [
        ("omitted", "artifact-pdf#omitted-source=1"),
        ("extra-pdf", "artifact-pdf#extra-source=1"),
        ("non-pdf", "artifact-pdf#non-pdf-source=1"),
    ],
)
def test_input_pdf_provenance_matches_sources_represented_by_target_pages(
    tmp_path, relationship, expected_evidence
):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    input_artifact = next(
        artifact for artifact in manifest["artifacts"] if artifact["kind"] == "input-pdf"
    )
    if relationship == "omitted":
        input_artifact["sourceIds"] = []
    elif relationship == "extra-pdf":
        manifest["sources"].append(
            {
                "sourceId": "source-pdf-unmapped",
                "path": "workspace/source-unmapped.pdf",
                "mediaType": "application/pdf",
                "pageCount": 1,
                "size": 1,
                "sha256": "e" * 64,
                "coverageState": "assigned",
            }
        )
        manifest["pdfPages"].append(
            {
                "sourceId": "source-pdf-unmapped",
                "sourcePage": 1,
                "coverageState": "assigned",
                "targetPage": None,
            }
        )
        input_artifact["sourceIds"].append("source-pdf-unmapped")
    else:
        input_artifact["sourceIds"].append("source-roster")
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "input-pdf-provenance-mismatch" in report.errors
    assert expected_evidence in _check(
        report, "input-pdf-provenance-mismatch"
    ).evidence_refs


def test_unknown_source_decision_exception_and_evidence_references_are_rejected(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["sources"][0]["duplicateSourceId"] = "source-unknown"
    manifest["sources"][0]["decisionId"] = "decision-unknown"
    manifest["artifacts"][0]["sourceIds"].append("source-artifact-unknown")
    manifest["decisions"] = [
        {
            "decisionId": "decision-present",
            "proposalVersion": "1.0",
            "type": "approve-preview",
            "actor": "user",
            "timestamp": SYNTHETIC_TIMESTAMP,
            "evidenceRefs": ["artifact-unknown", "source-pdf#page=99"],
        }
    ]
    manifest["exceptionIds"] = ["exception-unknown"]
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "source-reference-unknown" in report.errors
    assert "decision-reference-unknown" in report.errors
    assert "exception-reference-unknown" in report.errors
    assert _check(report, "source-reference-unknown").evidence_refs == [
        "source-artifact-unknown",
        "source-unknown",
    ]
    assert "evidence-reference-unknown" in report.errors
    assert _check(report, "evidence-reference-unknown").evidence_refs == [
        "decision-present#evidence-ref=0",
        "decision-present#evidence-ref=1",
    ]


def test_unknown_evidence_reports_owner_and_index_without_echoing_raw_values(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(
        package_dir,
        exception_items=[
            {
                "exceptionId": "exception-evidence-owner",
                "code": "artifact-outside-package",
                "severity": "warning",
                "evidenceRefs": ["../../private/location/synthetic-subject"],
                "explanation": "Synthetic unknown exception evidence.",
                "requiredAction": "Review the synthetic evidence reference.",
                "resolution": "open",
            }
        ],
    )
    manifest["decisions"] = [
        {
            "decisionId": "decision-evidence-owner",
            "proposalVersion": "1.0",
            "type": "approve-preview",
            "actor": "user",
            "timestamp": SYNTHETIC_TIMESTAMP,
            "evidenceRefs": ["synthetic.person@example.invalid"],
        }
    ]
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)
    serialized_report = report.model_dump_json(by_alias=True)

    assert _check(report, "evidence-reference-unknown").evidence_refs == [
        "decision-evidence-owner#evidence-ref=0",
        "exception-evidence-owner#evidence-ref=0",
    ]
    assert "../../private/location/synthetic-subject" not in serialized_report
    assert "synthetic.person@example.invalid" not in serialized_report


def test_evidence_can_reference_an_authoritative_source_page_missing_coverage(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["pdfPages"] = [manifest["pdfPages"][0]]
    manifest["decisions"] = [
        {
            "decisionId": "decision-missing-coverage",
            "proposalVersion": "1.0",
            "type": "assign-page",
            "actor": "user",
            "timestamp": SYNTHETIC_TIMESTAMP,
            "evidenceRefs": ["source-pdf#page=2"],
        }
    ]
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "page-coverage-missing" in report.errors
    assert "evidence-reference-unknown" not in report.errors


def test_unreadable_pdf_and_roster_are_reported_as_independent_sibling_failures(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    (package_dir / "input.pdf").write_bytes(b"not a pdf")
    (package_dir / "roster.xlsx").write_bytes(b"not a workbook")
    _refresh_artifact(package_dir, manifest, "input-pdf")
    _refresh_artifact(package_dir, manifest, "roster")

    report = _validate(package_dir)

    assert "pdf-unreadable" in report.errors
    assert "roster-unreadable" in report.errors


@pytest.mark.parametrize(
    "mapping",
    [
        None,
        {
            "sourceId": "source-roster",
            "sheetName": "Roster",
            "canonicalToSourceColumns": {"identity": "Synthetic identity"},
        },
        {
            "sourceId": "source-roster",
            "sheetName": "Roster",
            "canonicalToSourceColumns": {
                "name": "Display label",
                "identity": "Display label",
            },
        },
    ],
)
def test_missing_or_ambiguous_canonical_name_and_identity_mapping_is_rejected(
    tmp_path, mapping
):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["rosterMapping"] = mapping
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "roster-mapping-missing" in report.errors


def test_selected_roster_sheet_and_mapped_columns_must_exist(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["rosterMapping"]["sheetName"] = "Missing sheet"
    manifest["rosterMapping"]["canonicalToSourceColumns"]["identity"] = (
        "Missing identity column"
    )
    _save_manifest(package_dir, manifest)

    missing_sheet = _validate(package_dir)
    assert "roster-sheet-missing" in missing_sheet.errors

    manifest["rosterMapping"]["sheetName"] = "Roster"
    _save_manifest(package_dir, manifest)
    missing_column = _validate(package_dir)
    assert "roster-column-missing" in missing_column.errors


def test_nonempty_canonical_identity_values_must_be_unique(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    _write_roster(
        package_dir / "roster.xlsx",
        rows=(
            ("SUBJECT-ALPHA", "SYNTHETIC-IDENTITY-DUPLICATE"),
            ("SUBJECT-BETA", "SYNTHETIC-IDENTITY-DUPLICATE"),
            ("SUBJECT-GAMMA", ""),
            ("SUBJECT-DELTA", ""),
        ),
    )
    _refresh_artifact(package_dir, manifest, "roster")

    report = _validate(package_dir)

    assert "roster-identity-duplicate" in report.errors
    assert _check(report, "roster-identity-duplicate").evidence_refs == [
        "artifact-roster#row=2",
        "artifact-roster#row=3",
    ]


def test_prepared_package_allows_an_open_warning_only_exception(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(
        package_dir,
        exception_items=[
            {
                "exceptionId": "exception-synthetic-warning",
                "code": "artifact-outside-package",
                "severity": "warning",
                "evidenceRefs": ["artifact-pdf"],
                "explanation": "Synthetic warning for contract coverage.",
                "requiredAction": "Review the synthetic warning.",
                "resolution": "open",
            }
        ],
    )

    report = _validate(package_dir)

    assert report.outcome == "valid"
    assert report.package_status == "prepared"
    assert report.errors == []
    assert report.warnings == ["artifact-outside-package"]


@pytest.mark.parametrize(
    ("failure", "artifact_error"),
    [
        ("missing", "artifact-missing"),
        ("malformed", "exceptions-invalid"),
        ("metadata-mismatch", "artifact-size-mismatch"),
    ],
)
def test_manifest_exception_ids_remain_unknown_when_exceptions_are_unusable(
    tmp_path, failure, artifact_error
):
    package_dir = tmp_path / "package"
    manifest = _write_package(
        package_dir,
        exception_items=[
            {
                "exceptionId": "exception-synthetic-unresolved",
                "code": "unassigned-page",
                "severity": "blocking",
                "evidenceRefs": ["source-pdf#page=2"],
                "explanation": "Synthetic exception document failure.",
                "requiredAction": "Restore the synthetic exception document.",
                "resolution": "open",
            }
        ],
    )
    exceptions_path = package_dir / "exceptions.json"
    if failure == "missing":
        exceptions_path.unlink()
    elif failure == "malformed":
        exceptions_path.write_bytes(b"{")
        _refresh_artifact(package_dir, manifest, "exceptions")
    else:
        exceptions_path.write_bytes(b"{}")

    report = _validate(package_dir)

    assert artifact_error in report.errors
    assert "exception-reference-unknown" in report.errors
    assert _check(report, "exception-reference-unknown").evidence_refs == [
        "exception-synthetic-unresolved"
    ]


@pytest.mark.parametrize("valid_document", [True, False])
def test_declared_validation_report_is_parsed_but_never_used_as_current_output(
    tmp_path, valid_document
):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    document = _historical_validation_report()
    if not valid_document:
        document["schemaVersion"] = "invalid"
    _add_artifact(
        package_dir,
        manifest,
        artifact_id="artifact-validation-report",
        kind="validation-report",
        filename="historical-validation-report.json",
        content=json.dumps(document).encode("utf-8"),
    )

    report = _validate(package_dir)

    assert ("validation-report-invalid" in report.errors) is not valid_document
    if valid_document:
        assert report.outcome == "valid"
        assert report.errors == []


def test_blocking_exception_and_unresolved_coverage_are_rejected(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(
        package_dir,
        status="partially_prepared",
        exception_items=[
            {
                "exceptionId": "exception-synthetic-blocking",
                "code": "unresolved-coverage",
                "severity": "blocking",
                "evidenceRefs": ["source-pdf#page=2"],
                "explanation": "Synthetic page remains unresolved.",
                "requiredAction": "Resolve the synthetic page.",
                "resolution": "open",
            }
        ],
    )
    manifest["pdfPages"][1]["coverageState"] = "unresolved"
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert report.outcome == "invalid"
    assert report.package_status == "partially_prepared"
    assert "blocking-exception" in report.errors
    assert "unresolved-coverage" in report.errors


def test_prepared_manifest_with_unresolved_coverage_keeps_the_semantic_code(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["pdfPages"][1]["coverageState"] = "unresolved"
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert report.outcome == "invalid"
    assert report.package_status == "partially_prepared"
    assert "manifest-invalid" in report.errors
    assert "unresolved-coverage" in report.errors
    assert _check(report, "unresolved-coverage").evidence_refs == [
        "source-pdf#page=2"
    ]


def test_symlinked_artifact_is_rejected_before_file_parsing(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes(b"not a pdf")
    (package_dir / "input.pdf").unlink()
    (package_dir / "input.pdf").symlink_to(outside)
    _refresh_artifact(package_dir, manifest, "input-pdf")

    report = _validate(package_dir)

    assert "symlink-not-allowed" in report.errors
    assert "pdf-unreadable" not in report.errors


def test_symlinked_package_root_uses_private_synthetic_evidence(tmp_path):
    package_dir = tmp_path / "package"
    _write_package(package_dir)
    package_alias = tmp_path / "package-alias"
    package_alias.symlink_to(package_dir, target_is_directory=True)

    report = _validate(package_alias)

    assert "symlink-not-allowed" in report.errors
    assert _check(report, "symlink-not-allowed").evidence_refs == ["package-root"]


def test_validation_fails_closed_when_secure_relative_open_is_unavailable(
    tmp_path, monkeypatch
):
    import intake_package_validator as validator

    package_dir = tmp_path / "package"
    _write_package(package_dir)

    def reject_pathname_fallback(*_args, **_kwargs):
        pytest.fail("an insecure package pathname reader was invoked")

    def reject_parser(*_args, **_kwargs):
        pytest.fail("an artifact parser was invoked")

    monkeypatch.setattr(validator, "_SUPPORTS_SECURE_RELATIVE_OPEN", False)
    monkeypatch.setattr(Path, "open", reject_pathname_fallback)
    monkeypatch.setattr(validator.fitz, "open", reject_parser)
    monkeypatch.setattr(validator.openpyxl, "load_workbook", reject_parser)

    report = validator.validate_package(package_dir)

    assert report.errors == ["secure-open-unavailable"]
    assert _check(report, "secure-open-unavailable").evidence_refs == ["package-root"]


def test_pdf_parser_uses_the_same_opened_bytes_that_were_digest_checked(
    tmp_path, monkeypatch
):
    import intake_package_validator as validator

    package_dir = tmp_path / "package"
    _write_package(package_dir)
    pdf_path = package_dir / "input.pdf"
    replacement = tmp_path / "replacement.pdf"
    replacement.write_bytes(b"not a pdf")
    real_open = validator.fitz.open
    swapped = False

    def swap_path_before_real_parse(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            replacement.replace(pdf_path)
            swapped = True
        return real_open(*args, **kwargs)

    monkeypatch.setattr(validator.fitz, "open", swap_path_before_real_parse)

    report = validator.validate_package(package_dir)

    assert swapped
    assert report.outcome == "valid"
    assert "pdf-unreadable" not in report.errors


def test_roster_parser_uses_the_same_opened_bytes_that_were_preflighted(
    tmp_path, monkeypatch
):
    import intake_package_validator as validator

    package_dir = tmp_path / "package"
    _write_package(package_dir)
    roster_path = package_dir / "roster.xlsx"
    replacement = tmp_path / "replacement.xlsx"
    replacement.write_bytes(b"not a workbook")
    real_load_workbook = validator.openpyxl.load_workbook
    swapped = False

    def swap_path_before_real_parse(*args, **kwargs):
        nonlocal swapped
        if not swapped:
            replacement.replace(roster_path)
            swapped = True
        return real_load_workbook(*args, **kwargs)

    monkeypatch.setattr(
        validator.openpyxl, "load_workbook", swap_path_before_real_parse
    )

    report = validator.validate_package(package_dir)

    assert swapped
    assert report.outcome == "valid"
    assert "roster-unreadable" not in report.errors


@pytest.mark.parametrize("declared_path", ["../outside.pdf", "bad\x00.pdf"])
def test_package_relative_path_escaping_the_package_is_rejected(
    tmp_path, declared_path
):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["artifacts"][0]["path"] = declared_path
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "unsafe-artifact-path" in report.errors


def test_failed_size_check_precedes_and_suppresses_pdf_parsing(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    (package_dir / "input.pdf").write_bytes(b"not a pdf")
    _save_manifest(package_dir, manifest)

    report = _validate(package_dir)

    assert "artifact-size-mismatch" in report.errors
    assert "pdf-unreadable" not in report.errors


def test_errors_and_evidence_are_deterministic_and_code_sorted(tmp_path):
    package_dir = tmp_path / "package"
    manifest = _write_package(package_dir)
    manifest["artifacts"] = []
    manifest["pdfPages"] = []
    manifest["sources"][0]["decisionId"] = "decision-zeta"
    manifest["sources"][1]["decisionId"] = "decision-alpha"
    _save_manifest(package_dir, manifest)

    first = _validate(package_dir)
    second = _validate(package_dir)

    assert first.errors == sorted(first.errors)
    assert first.errors == second.errors
    assert first.model_dump(exclude={"validated_at"}) == second.model_dump(
        exclude={"validated_at"}
    )
    assert _check(first, "decision-reference-unknown").evidence_refs == [
        "decision-alpha",
        "decision-zeta",
    ]
    assert _check(first, "missing-required-artifact").evidence_refs == [
        "exceptions",
        "input-pdf",
        "roster",
    ]
