"""Export the versioned CTV intake contract artifacts."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from intake_contract import (
    EXCEPTION_CODES,
    CanonicalRosterRow,
    ExceptionsDocument,
    PackageManifest,
    ValidationReport,
)
from intake_contract_v2 import (
    AssignmentsDocumentV2,
    CanonicalRosterDocumentV2,
    ExceptionsDocumentV2,
    PackageManifestV2,
    ValidationReportV2,
)


_JSON_ARTIFACTS = {
    "package.schema.json": PackageManifest,
    "exceptions.schema.json": ExceptionsDocument,
    "validation-report.schema.json": ValidationReport,
    "canonical-roster.schema.json": CanonicalRosterRow,
}

_COMPATIBILITY = """# CTV Intake Contract v1 compatibility

Producers and consumers must match major version `1`.

Consumers may accept added optional fields only after the contract tests pass.
Removing or renaming fields, changing enum meaning, or weakening coverage is a
major change.

Exception codes are append-only within v1.

WP records the exact CTV commit and tree digest in `SOURCE.json`.
"""

_V2_JSON_ARTIFACTS = {
    "package.schema.json": PackageManifestV2,
    "assignments.schema.json": AssignmentsDocumentV2,
    "canonical-roster.schema.json": CanonicalRosterDocumentV2,
    "exceptions.schema.json": ExceptionsDocumentV2,
    "validation-report.schema.json": ValidationReportV2,
}

_V2_EXCEPTION_CODES = {
    **EXCEPTION_CODES,
    "assignment-decision-missing": "An assignment references no matching manifest decision.",
    "assignment-locator-unresolved": "An assignment locator does not resolve to a declared artifact.",
    "participant-roster-mismatch": "Assignment participants do not match canonical roster rows.",
    "unacquired-source-provenance": "An unacquired source appears in materialized artifact provenance.",
}

_V2_COMPATIBILITY = """# CTV Intake Contract v2 compatibility

Producers and consumers must match major version `2`. A v1 consumer is not
compatible with a v2 package and must not reinterpret it as v1.

V2 requires `assignments.json`; it permits repeatable `evidence` artifacts and
uses closed document shapes. `validation-report.json` is a generated receipt,
not a declared manifest artifact.

V2 contract fixtures contain only synthetic values. `schema-example` illustrates
closed document shapes, not a materialized package. Semantic complete packages
come from the production-backed Task 5 fixture factory.
"""


def _v2_manifest_document() -> dict[str, object]:
    sha_a = "a" * 64
    return {
        "schemaVersion": "2.0",
        "compatibilityTarget": "ctv-intake-v2",
        "packageId": "package-" + "b" * 64,
        "sourceObservationId": "observation-" + "c" * 64,
        "proposalDigest": sha_a,
        "batchId": "batch-synthetic-001",
        "caseId": "case-synthetic-001",
        "faCode": "FA-SYNTHETIC-001",
        "packageVersion": "writer-2.0.0",
        "status": "prepared",
        "validatorVersion": "validator-2.0.0",
        "sources": [
            {
                "bindingStatus": "verified-content",
                "sourceId": "source-0001",
                "path": "incoming/synthetic-input.pdf",
                "mediaType": "application/pdf",
                "size": 120,
                "sha256": sha_a,
                "pageCount": 1,
                "coverageState": "assigned",
            },
            {
                "bindingStatus": "verified-content",
                "sourceId": "source-0002",
                "path": "incoming/synthetic-roster.xlsx",
                "mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "size": 80,
                "sha256": "b" * 64,
                "coverageState": "assigned",
            },
            {
                "bindingStatus": "verified-content",
                "sourceId": "source-0003",
                "path": "incoming/synthetic-evidence.png",
                "mediaType": "image/png",
                "size": 10,
                "sha256": "e" * 64,
                "coverageState": "assigned",
            },
        ],
        "pdfPages": [{
            "sourceId": "source-0001", "sourcePage": 1, "targetPage": 1,
            "coverageState": "assigned",
        }],
        "artifacts": [
            {"artifactId": "artifact-input-pdf", "kind": "input-pdf", "formatVersion": "2.0", "path": "input.pdf", "size": 120, "sha256": sha_a, "sourceIds": ["source-0001"]},
            {"artifactId": "artifact-roster", "kind": "roster", "formatVersion": "2.0", "path": "roster.xlsx", "size": 80, "sha256": "b" * 64, "sourceIds": ["source-0002"]},
            {"artifactId": "artifact-assignments", "kind": "assignments", "formatVersion": "2.0", "path": "assignments.json", "size": 40, "sha256": "c" * 64, "sourceIds": []},
            {"artifactId": "artifact-exceptions", "kind": "exceptions", "formatVersion": "2.0", "path": "exceptions.json", "size": 30, "sha256": "d" * 64, "sourceIds": []},
            {"artifactId": "artifact-evidence-0001", "kind": "evidence", "formatVersion": "2.0", "path": "evidence/evidence-0001.png", "size": 10, "sha256": "e" * 64, "sourceIds": ["source-0003"]},
            {"artifactId": "artifact-evidence-0002", "kind": "evidence", "formatVersion": "2.0", "path": "evidence/evidence-0002.xlsx", "size": 10, "sha256": "f" * 64, "sourceIds": ["source-0002"]},
        ],
        "rosterMapping": {
            "sourceId": "source-0002", "sheetName": "Synthetic roster",
            "canonicalToSourceColumns": {"name": "Name", "identity": "Identity", "faCode": "FA code"},
        },
        "decisions": [
            {"decisionId": "decision-0001", "proposalVersion": "proposal-2.0", "proposalDigest": sha_a, "type": "accept-unit", "actor": "user", "subjectRefs": ["unit-0001"], "evidenceRefs": ["source-0001"]},
            {"decisionId": "decision-0002", "proposalVersion": "proposal-2.0", "proposalDigest": sha_a, "type": "select-roster", "actor": "user", "subjectRefs": ["unit-0002"], "evidenceRefs": ["source-0002"]},
            {"decisionId": "decision-0003", "proposalVersion": "proposal-2.0", "proposalDigest": sha_a, "type": "approve-proposal", "actor": "user", "subjectRefs": [], "evidenceRefs": []},
            {"decisionId": "decision-0004", "proposalVersion": "proposal-2.0", "proposalDigest": sha_a, "type": "accept-unit", "actor": "user", "subjectRefs": ["unit-0003"], "evidenceRefs": ["source-0003"]},
            {"decisionId": "decision-0005", "proposalVersion": "proposal-2.0", "proposalDigest": sha_a, "type": "accept-unit", "actor": "user", "subjectRefs": ["unit-0004"], "evidenceRefs": ["source-0002"]},
        ],
        "exceptionIds": [],
    }


def _v2_assignments_document(*, invalid_decision: bool = False) -> dict[str, object]:
    sha_a = "a" * 64
    unit_decision_id = "decision-9999" if invalid_decision else "decision-0001"
    return {
        "schemaVersion": "2.0", "packageId": "package-" + "b" * 64,
        "sourceObservationId": "observation-" + "c" * 64, "proposalDigest": sha_a,
        "rosterArtifactId": "artifact-roster",
        "participants": [{"participantHandle": "participant-0001", "rosterRowId": "roster-row-0001"}],
        "units": [
            {"unitId": "unit-0001", "sourceId": "source-0001", "sourceUnitIndex": 1, "unitKind": "pdf-page", "decisionId": unit_decision_id, "decision": "accepted", "role": "service-contract", "target": {"scope": "individual", "participantHandles": ["participant-0001"]}, "outputLocator": {"kind": "pdf-page", "artifactId": "artifact-input-pdf", "targetPage": 1}},
            {"unitId": "unit-0002", "sourceId": "source-0002", "sourceUnitIndex": 1, "unitKind": "worksheet", "decisionId": "decision-0002", "decision": "accepted", "role": "payment-roster", "target": {"scope": "case", "participantHandles": []}, "outputLocator": {"kind": "roster", "artifactId": "artifact-roster", "worksheetIndex": 1}},
            {"unitId": "unit-0003", "sourceId": "source-0003", "sourceUnitIndex": 1, "unitKind": "image", "decisionId": "decision-0004", "decision": "accepted", "role": "identity-front", "target": {"scope": "individual", "participantHandles": ["participant-0001"]}, "outputLocator": {"kind": "image", "artifactId": "artifact-evidence-0001"}},
            {"unitId": "unit-0004", "sourceId": "source-0002", "sourceUnitIndex": 2, "unitKind": "worksheet", "decisionId": "decision-0005", "decision": "accepted", "role": "other-supporting-evidence", "target": {"scope": "case", "participantHandles": []}, "outputLocator": {"kind": "worksheet", "artifactId": "artifact-evidence-0002", "worksheetIndex": 1}},
        ],
        "exclusions": [],
    }


def _v2_validation_report_document() -> dict[str, object]:
    sha_a = "a" * 64
    return {
        "schemaVersion": "2.0", "outcome": "valid", "packageStatus": "prepared",
        "checks": [{"code": "manifest-valid", "passed": True, "evidenceRefs": ["artifact-assignments"]}],
        "errors": [], "warnings": [], "validatedAt": "2026-08-14T00:00:00Z",
        "validatorVersion": "validator-2.0.0", "packageId": "package-" + "b" * 64,
        "sourceObservationId": "observation-" + "c" * 64, "proposalDigest": sha_a,
        "manifestSha256": sha_a, "declaredArtifactSetSha256": "b" * 64,
    }


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def export_contract_artifacts(output_root: Path, compatibility_target: str = "ctv-intake-v1") -> None:
    """Write the selected versioned CTV intake contract to *output_root*."""
    if compatibility_target == "ctv-intake-v1":
        _export_v1(output_root)
        return
    if compatibility_target == "ctv-intake-v2":
        _export_v2(output_root)
        return
    raise ValueError("unsupported CTV intake compatibility target")


def _export_v1(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for filename, model in _JSON_ARTIFACTS.items():
        (output / filename).write_text(_canonical_json(model.model_json_schema()), encoding="utf-8")
    (output / "exception-codes.json").write_text(
        _canonical_json(EXCEPTION_CODES), encoding="utf-8"
    )
    (output / "compatibility.md").write_text(_COMPATIBILITY, encoding="utf-8")


def _write_json_artifact(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_canonical_json(value), encoding="utf-8")


def _export_v2(output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    for filename, model in _V2_JSON_ARTIFACTS.items():
        _write_json_artifact(output / filename, model.model_json_schema())
    _write_json_artifact(output / "exception-codes.json", _V2_EXCEPTION_CODES)
    (output / "compatibility.md").write_text(_V2_COMPATIBILITY, encoding="utf-8")
    (output / "fixtures" / "README.md").parent.mkdir(parents=True, exist_ok=True)
    (output / "fixtures" / "README.md").write_text(
        "# CTV intake v2 synthetic fixtures\n\n"
        "`schema-example` demonstrates closed document shapes only; it is not a "
        "materialized package. Semantic complete packages come from the "
        "production-backed Task 5 fixture factory.\n\n"
        "`invalid-assignment` contains exactly one intentional cross-reference "
        "failure: `assignment-decision-missing`.\n",
        encoding="utf-8",
    )
    manifest = _v2_manifest_document()
    for fixture_name, assignments in (
        ("schema-example", _v2_assignments_document()),
        ("invalid-assignment", _v2_assignments_document(invalid_decision=True)),
    ):
        fixture_root = output / "fixtures" / fixture_name
        _write_json_artifact(fixture_root / "case-manifest.json", manifest)
        _write_json_artifact(fixture_root / "assignments.json", assignments)
        _write_json_artifact(fixture_root / "exceptions.json", {"schemaVersion": "2.0", "items": []})
    _write_json_artifact(output / "fixtures" / "schema-example" / "validation-report.json", _v2_validation_report_document())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--compatibility-target", default="ctv-intake-v1")
    args = parser.parse_args()
    export_contract_artifacts(args.output, args.compatibility_target)


if __name__ == "__main__":
    main()
