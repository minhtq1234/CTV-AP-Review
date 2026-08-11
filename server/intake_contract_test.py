from typing import get_args

import pytest
from pydantic import TypeAdapter, ValidationError

from intake_contract import (
    ArtifactKind,
    CanonicalRosterRow,
    CoverageState,
    DecisionType,
    EXCEPTION_CODES,
    ExceptionItem,
    ExceptionResolution,
    ExceptionSeverity,
    ExceptionsDocument,
    PackageManifest,
    PackageStatus,
    ValidationOutcome,
    ValidationReport,
)


def _manifest(**overrides):
    document = {
        "schemaVersion": "1.0",
        "batchId": "batch-demo",
        "caseId": "case-demo",
        "faCode": None,
        "packageVersion": "1.0",
        "status": "partially_prepared",
        "compatibilityTarget": "ctv-intake-v1",
        "sources": [{
            "sourceId": "source-pdf",
            "path": "workspace/incoming/source.pdf",
            "mediaType": "application/pdf",
            "size": 120,
            "sha256": "a" * 64,
            "coverageState": "assigned",
        }],
        "pdfPages": [{
            "sourceId": "source-pdf",
            "sourcePage": 1,
            "coverageState": "assigned",
            "targetPage": 1,
        }],
        "artifacts": [{
            "artifactId": "artifact-input-pdf",
            "kind": "input-pdf",
            "path": "artifacts/input.pdf",
            "size": 120,
            "sha256": "b" * 64,
            "sourceIds": ["source-pdf"],
        }],
        "rosterMapping": None,
        "decisions": [{
            "decisionId": "decision-preview",
            "proposalVersion": "1.0",
            "type": "approve-preview",
            "actor": "user",
            "timestamp": "2026-08-11T00:00:00Z",
            "evidenceRefs": ["source-pdf"],
        }],
        "exceptionIds": [],
        "validatedAt": "2026-08-11T00:00:00Z",
        "validatorVersion": "1.0",
    }
    document.update(overrides)
    return document


def test_public_literal_types_accept_the_contract_values_and_reject_other_values():
    literal_values = {
        CoverageState: [
            "assigned", "shared", "duplicate", "unsupported", "unreadable",
            "excluded-by-user", "unresolved",
        ],
        PackageStatus: ["prepared", "partially_prepared"],
        ValidationOutcome: ["valid", "invalid"],
        ExceptionSeverity: ["warning", "blocking"],
        ArtifactKind: ["input-pdf", "roster", "cccd", "exceptions", "validation-report"],
        ExceptionResolution: ["open", "accepted-partial", "resolved"],
        DecisionType: [
            "assign-source", "share-source", "mark-duplicate", "exclude-source",
            "assign-page", "select-roster-sheet", "map-roster-column",
            "approve-preview", "accept-partial",
        ],
    }

    for contract_type, expected in literal_values.items():
        assert list(get_args(contract_type)) == expected
        adapter = TypeAdapter(contract_type)
        assert [adapter.validate_python(value) for value in expected] == expected
        with pytest.raises(ValidationError):
            adapter.validate_python("not-a-contract-value")


def test_manifest_round_trips_the_document_shape_with_no_extra_fields():
    manifest = PackageManifest.model_validate(_manifest())

    assert manifest.model_dump(by_alias=True)["artifacts"][0]["path"] == "artifacts/input.pdf"
    with pytest.raises(ValidationError):
        PackageManifest.model_validate(_manifest(unexpected="not-allowed"))


def test_source_page_count_is_optional_but_one_based_when_present():
    document = _manifest()
    document["sources"][0]["pageCount"] = 2

    manifest = PackageManifest.model_validate(document)

    assert manifest.sources[0].page_count == 2
    document["sources"][0].pop("pageCount")
    assert PackageManifest.model_validate(document).sources[0].page_count is None
    document["sources"][0]["pageCount"] = 0
    with pytest.raises(ValidationError):
        PackageManifest.model_validate(document)


@pytest.mark.parametrize("path", ["/outside/source.pdf", "../source.pdf", "folder/../source.pdf"])
def test_manifest_rejects_absolute_and_traversing_workspace_paths(path):
    document = _manifest()
    document["sources"][0]["path"] = path

    with pytest.raises(ValidationError):
        PackageManifest.model_validate(document)


def test_manifest_rejects_malformed_sha256_values():
    document = _manifest()
    document["sources"][0]["sha256"] = "not-a-sha256"

    with pytest.raises(ValidationError):
        PackageManifest.model_validate(document)


def test_manifest_rejects_zero_based_source_pages():
    document = _manifest()
    document["pdfPages"][0]["sourcePage"] = 0

    with pytest.raises(ValidationError):
        PackageManifest.model_validate(document)


@pytest.mark.parametrize(
    ("key", "duplicate"),
    [
        ("sources", {"sourceId": "source-pdf", "path": "workspace/other.pdf", "mediaType": "application/pdf", "size": 1, "sha256": "c" * 64, "coverageState": "assigned"}),
        ("artifacts", {"kind": "exceptions", "path": "artifacts/exceptions.json", "size": 1, "sha256": "c" * 64, "sourceIds": [], "artifactId": "artifact-input-pdf"}),
        ("decisions", {"decisionId": "decision-preview", "proposalVersion": "1.0", "type": "accept-partial", "actor": "user", "timestamp": "2026-08-11T00:00:00Z", "evidenceRefs": []}),
    ],
)
def test_manifest_rejects_duplicate_source_artifact_and_decision_ids(key, duplicate):
    document = _manifest()
    document[key].append(duplicate)

    with pytest.raises(ValidationError):
        PackageManifest.model_validate(document)


def test_exceptions_document_rejects_duplicate_exception_ids():
    item = {
        "exceptionId": "exception-1",
        "code": "unresolved-coverage",
        "severity": "blocking",
        "evidenceRefs": ["source-pdf"],
        "explanation": "A source remains unresolved.",
        "requiredAction": "Resolve the source coverage.",
        "resolution": "open",
    }

    with pytest.raises(ValidationError):
        ExceptionsDocument.model_validate({"schemaVersion": "1.0", "items": [item, item]})


def test_exception_item_accepts_the_append_only_unassigned_page_code():
    item = ExceptionItem.model_validate({
        "exceptionId": "exception-unassigned-page",
        "code": "unassigned-page",
        "severity": "blocking",
        "evidenceRefs": ["source-synthetic-pdf#page=2"],
        "explanation": "A synthetic page is not assigned.",
        "requiredAction": "Assign or explicitly exclude the page.",
        "resolution": "open",
    })

    assert item.code == "unassigned-page"


def test_manifest_rejects_duplicate_exception_references():
    with pytest.raises(ValidationError):
        PackageManifest.model_validate(_manifest(exceptionIds=["exception-1", "exception-1"]))


def test_prepared_manifest_rejects_unresolved_coverage():
    document = _manifest(status="prepared")
    document["sources"][0]["coverageState"] = "unresolved"

    with pytest.raises(ValidationError):
        PackageManifest.model_validate(document)


def test_prepared_validation_report_rejects_blocking_exceptions():
    with pytest.raises(ValidationError):
        ValidationReport.model_validate({
            "schemaVersion": "1.0",
            "outcome": "invalid",
            "packageStatus": "prepared",
            "checks": [{"code": "unresolved-coverage", "passed": False, "evidenceRefs": ["source-pdf"]}],
            "errors": ["exception-1"],
            "warnings": [],
            "validatedAt": "2026-08-11T00:00:00Z",
            "validatorVersion": "1.0",
        })


@pytest.mark.parametrize("path", ["/outside/input.pdf", "../input.pdf", "folder/../input.pdf"])
def test_manifest_rejects_absolute_and_traversing_artifact_paths(path):
    document = _manifest()
    document["artifacts"][0]["path"] = path

    with pytest.raises(ValidationError):
        PackageManifest.model_validate(document)


def test_manifest_accepts_a_top_level_package_relative_artifact_path():
    document = _manifest()
    document["artifacts"][0]["path"] = "input.pdf"

    manifest = PackageManifest.model_validate(document)

    assert manifest.artifacts[0].path == "input.pdf"


def test_exception_codes_and_validation_checks_use_lowercase_kebab_case():
    item = {
        "exceptionId": "exception-1",
        "code": "unresolved-coverage",
        "severity": "blocking",
        "evidenceRefs": ["source-pdf"],
        "explanation": "A source remains unresolved.",
        "requiredAction": "Resolve the source coverage.",
        "resolution": "open",
    }

    document = ExceptionsDocument.model_validate({"schemaVersion": "1.0", "items": [item]})
    assert document.items[0].code == "unresolved-coverage"
    assert set(EXCEPTION_CODES) == {
        "artifact-outside-package", "blocking-exception", "duplicate-id",
        "malformed-sha256", "path-not-workspace-relative",
        "unassigned-page", "unresolved-coverage", "zero-based-page",
    }


@pytest.mark.parametrize("code", ["UPPER_CASE", "bad_code", "with space", "", "two--hyphens", "-leading", "trailing-"])
def test_validation_checks_reject_non_kebab_case_codes(code):
    with pytest.raises(ValidationError):
        ValidationReport.model_validate({
            "schemaVersion": "1.0",
            "outcome": "invalid",
            "packageStatus": "partially_prepared",
            "checks": [{"code": code, "passed": False, "evidenceRefs": ["source-pdf"]}],
            "errors": [],
            "warnings": [],
            "validatedAt": "2026-08-11T00:00:00Z",
            "validatorVersion": "1.0",
        })


def test_roster_mapping_is_canonical_to_source_and_exception_codes_are_exported():
    row = CanonicalRosterRow.model_validate({
        "rowId": "row-1",
        "values": {
            "name": "SUBJECT-ALPHA",
            "identity": "SYNTHETIC-IDENTITY-A",
            "faCode": "FA-DEMO",
        },
    })

    manifest = PackageManifest.model_validate(_manifest(rosterMapping={
        "sourceId": "source-pdf",
        "sheetName": "Roster",
        "canonicalToSourceColumns": {"faCode": "FA code"},
    }))
    assert row.values.fa_code == "FA-DEMO"
    assert manifest.roster_mapping.canonical_to_source_columns["faCode"] == "FA code"
    assert EXCEPTION_CODES["unresolved-coverage"]


def test_manifest_accepts_only_the_exact_v1_compatibility_target():
    assert PackageManifest.model_validate(_manifest()).compatibility_target == "ctv-intake-v1"

    with pytest.raises(ValidationError):
        PackageManifest.model_validate(_manifest(compatibilityTarget="ctv-intake-v1-compatible"))


@pytest.mark.parametrize(
    "values",
    [
        {"identity": "SYNTHETIC-IDENTITY-A"},
        {"name": "SUBJECT-ALPHA"},
        {"name": "", "identity": "SYNTHETIC-IDENTITY-A"},
        {"name": "SUBJECT-ALPHA", "identity": ""},
        {
            "name": "SUBJECT-ALPHA",
            "identity": "SYNTHETIC-IDENTITY-A",
            "arbitrary": "not-a-canonical-field",
        },
    ],
)
def test_canonical_roster_values_require_typed_name_and_identity(values):
    with pytest.raises(ValidationError):
        CanonicalRosterRow.model_validate({"rowId": "row-1", "values": values})


def test_canonical_roster_values_accept_the_bounded_v1_field_set():
    row = CanonicalRosterRow.model_validate({
        "rowId": "row-1",
        "values": {
            "name": "SUBJECT-ALPHA",
            "identity": "SYNTHETIC-IDENTITY-A",
            "faCode": "FA-SYNTH-001",
            "taxId": None,
            "birthDate": None,
            "bankAccount": None,
            "serviceFee": None,
            "product": None,
        },
    })

    assert row.values.name == "SUBJECT-ALPHA"
    assert row.values.identity == "SYNTHETIC-IDENTITY-A"


@pytest.mark.parametrize(
    "report",
    [
        {
            "schemaVersion": "1.0",
            "outcome": "valid",
            "packageStatus": "partially_prepared",
            "checks": [{"code": "gate", "passed": False, "evidenceRefs": []}],
            "errors": ["gate"],
            "warnings": [],
            "validatedAt": "2026-08-11T00:00:00Z",
            "validatorVersion": "1.0",
        },
        {
            "schemaVersion": "1.0",
            "outcome": "invalid",
            "packageStatus": "partially_prepared",
            "checks": [],
            "errors": [],
            "warnings": [],
            "validatedAt": "2026-08-11T00:00:00Z",
            "validatorVersion": "1.0",
        },
        {
            "schemaVersion": "1.0",
            "outcome": "invalid",
            "packageStatus": "partially_prepared",
            "checks": [
                {"code": "gate", "passed": False, "evidenceRefs": []},
                {"code": "gate", "passed": False, "evidenceRefs": []},
            ],
            "errors": ["gate"],
            "warnings": [],
            "validatedAt": "2026-08-11T00:00:00Z",
            "validatorVersion": "1.0",
        },
        {
            "schemaVersion": "1.0",
            "outcome": "invalid",
            "packageStatus": "partially_prepared",
            "checks": [{"code": "other-gate", "passed": False, "evidenceRefs": []}],
            "errors": ["gate"],
            "warnings": [],
            "validatedAt": "2026-08-11T00:00:00Z",
            "validatorVersion": "1.0",
        },
    ],
)
def test_validation_report_rejects_contradictory_outcomes_and_checks(report):
    with pytest.raises(ValidationError):
        ValidationReport.model_validate(report)


def test_validation_report_accepts_positive_executed_checks_for_a_valid_result():
    report = ValidationReport.model_validate({
        "schemaVersion": "1.0",
        "outcome": "valid",
        "packageStatus": "prepared",
        "checks": [
            {"code": "manifest-valid", "passed": True, "evidenceRefs": ["case-manifest.json"]},
            {"code": "coverage-valid", "passed": True, "evidenceRefs": ["source-pdf"]},
        ],
        "errors": [],
        "warnings": [],
        "validatedAt": "2026-08-11T00:00:00Z",
        "validatorVersion": "1.0",
    })

    assert report.outcome == "valid"
    assert all(check.passed for check in report.checks)
