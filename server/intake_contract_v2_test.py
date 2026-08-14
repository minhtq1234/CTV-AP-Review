import copy

import pytest
from pydantic import ValidationError

from intake_contract_v2 import (
    AssignmentsDocumentV2,
    CanonicalRosterDocumentV2,
    ExceptionsDocumentV2,
    PackageManifestV2,
    ValidationReportV2,
)


_SHA = "a" * 64


def complete_manifest_v2(**overrides):
    document = {
        "schemaVersion": "2.0",
        "compatibilityTarget": "ctv-intake-v2",
        "packageId": "package-" + "b" * 64,
        "sourceObservationId": "observation-" + "c" * 64,
        "proposalDigest": _SHA,
        "batchId": "batch-synthetic-001",
        "caseId": "case-synthetic-001",
        "faCode": "FA-SYNTHETIC-001",
        "packageVersion": "writer-2.0.0",
        "status": "prepared",
        "validatorVersion": "validator-2.0.0",
        "sources": [
            {"bindingStatus": "verified-content", "sourceId": "source-0001", "path": "incoming/input.pdf", "mediaType": "application/pdf", "size": 120, "sha256": _SHA, "pageCount": 1, "coverageState": "assigned"},
            {"bindingStatus": "verified-content", "sourceId": "source-0002", "path": "incoming/roster.xlsx", "mediaType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", "size": 80, "sha256": "b" * 64, "coverageState": "assigned"},
            {"bindingStatus": "verified-content", "sourceId": "source-0003", "path": "incoming/evidence.png", "mediaType": "image/png", "size": 10, "sha256": "e" * 64, "coverageState": "assigned"},
        ],
        "pdfPages": [{"sourceId": "source-0001", "sourcePage": 1, "targetPage": 1, "coverageState": "assigned"}],
        "artifacts": [
            {"artifactId": "artifact-input-pdf", "kind": "input-pdf", "formatVersion": "2.0", "path": "input.pdf", "size": 120, "sha256": _SHA, "sourceIds": ["source-0001"]},
            {"artifactId": "artifact-roster", "kind": "roster", "formatVersion": "2.0", "path": "roster.xlsx", "size": 80, "sha256": "b" * 64, "sourceIds": ["source-0002"]},
            {"artifactId": "artifact-assignments", "kind": "assignments", "formatVersion": "2.0", "path": "assignments.json", "size": 40, "sha256": "c" * 64, "sourceIds": []},
            {"artifactId": "artifact-exceptions", "kind": "exceptions", "formatVersion": "2.0", "path": "exceptions.json", "size": 30, "sha256": "d" * 64, "sourceIds": []},
            {"artifactId": "artifact-evidence-0001", "kind": "evidence", "formatVersion": "2.0", "path": "evidence/evidence-0001.png", "size": 10, "sha256": "e" * 64, "sourceIds": ["source-0003"]},
            {"artifactId": "artifact-evidence-0002", "kind": "evidence", "formatVersion": "2.0", "path": "evidence/evidence-0002.xlsx", "size": 10, "sha256": "f" * 64, "sourceIds": ["source-0002"]},
        ],
        "rosterMapping": {"sourceId": "source-0002", "sheetName": "Synthetic roster", "canonicalToSourceColumns": {"name": "Name", "identity": "Identity", "faCode": "FA code"}},
        "decisions": [
            {"decisionId": "decision-0001", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "accept-unit", "actor": "user", "subjectRefs": ["unit-0001"], "evidenceRefs": ["source-0001"]},
            {"decisionId": "decision-0002", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "select-roster", "actor": "user", "subjectRefs": ["unit-0002"], "evidenceRefs": ["source-0002"]},
            {"decisionId": "decision-0003", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "approve-proposal", "actor": "user", "subjectRefs": [], "evidenceRefs": []},
            {"decisionId": "decision-0004", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "accept-unit", "actor": "user", "subjectRefs": ["unit-0003"], "evidenceRefs": ["source-0003"]},
            {"decisionId": "decision-0005", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "accept-unit", "actor": "user", "subjectRefs": ["unit-0004"], "evidenceRefs": ["source-0002"]},
        ],
        "exceptionIds": [],
    }
    document.update(overrides)
    return document


def complete_assignments_v2(**overrides):
    document = {
        "schemaVersion": "2.0", "packageId": "package-" + "b" * 64,
        "sourceObservationId": "observation-" + "c" * 64, "proposalDigest": _SHA,
        "rosterArtifactId": "artifact-roster",
        "participants": [{"participantHandle": "participant-0001", "rosterRowId": "roster-row-0001"}],
        "units": [
            {"unitId": "unit-0001", "sourceId": "source-0001", "sourceUnitIndex": 1, "unitKind": "pdf-page", "decisionId": "decision-0001", "decision": "accepted", "role": "service-contract", "target": {"scope": "individual", "participantHandles": ["participant-0001"]}, "outputLocator": {"kind": "pdf-page", "artifactId": "artifact-input-pdf", "targetPage": 1}},
            {"unitId": "unit-0002", "sourceId": "source-0002", "sourceUnitIndex": 1, "unitKind": "worksheet", "decisionId": "decision-0002", "decision": "accepted", "role": "payment-roster", "target": {"scope": "case", "participantHandles": []}, "outputLocator": {"kind": "roster", "artifactId": "artifact-roster", "worksheetIndex": 1}},
            {"unitId": "unit-0003", "sourceId": "source-0003", "sourceUnitIndex": 1, "unitKind": "image", "decisionId": "decision-0004", "decision": "accepted", "role": "identity-front", "target": {"scope": "individual", "participantHandles": ["participant-0001"]}, "outputLocator": {"kind": "image", "artifactId": "artifact-evidence-0001"}},
            {"unitId": "unit-0004", "sourceId": "source-0002", "sourceUnitIndex": 2, "unitKind": "worksheet", "decisionId": "decision-0005", "decision": "accepted", "role": "other-supporting-evidence", "target": {"scope": "case", "participantHandles": []}, "outputLocator": {"kind": "worksheet", "artifactId": "artifact-evidence-0002", "worksheetIndex": 1}},
        ], "exclusions": [],
    }
    document.update(overrides)
    return document


def test_v2_manifest_requires_assignments_and_allows_repeatable_evidence():
    manifest = PackageManifestV2.model_validate(complete_manifest_v2())
    assert [artifact.kind for artifact in manifest.artifacts].count("assignments") == 1
    assert [artifact.kind for artifact in manifest.artifacts].count("evidence") == 2

    duplicate = manifest.model_copy(update={"artifacts": manifest.artifacts + [manifest.artifacts[2]]})
    with pytest.raises(ValueError, match="single-instance artifact"):
        PackageManifestV2.model_validate(duplicate.model_dump(by_alias=True))


def test_v2_models_are_closed_and_reject_bool_as_integer_or_malformed_identifiers():
    manifest = complete_manifest_v2()
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate({**manifest, "unexpected": True})
    bad_size = copy.deepcopy(manifest)
    bad_size["artifacts"][0]["size"] = True
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate(bad_size)
    bad_id = copy.deepcopy(manifest)
    bad_id["sources"][0]["sourceId"] = "source X"
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate(bad_id)
    bad_digest = copy.deepcopy(manifest)
    bad_digest["proposalDigest"] = "A" * 64
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate(bad_digest)
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate({**manifest, "schemaVersion": "1.0"})


def test_v2_manifest_rejects_duplicate_ids_over_limit_evidence_and_unsafe_paths():
    manifest = complete_manifest_v2()
    duplicate_source = copy.deepcopy(manifest)
    duplicate_source["sources"].append(copy.deepcopy(duplicate_source["sources"][0]))
    with pytest.raises(ValidationError, match="source IDs"):
        PackageManifestV2.model_validate(duplicate_source)
    over_evidence = copy.deepcopy(manifest)
    evidence = over_evidence["artifacts"][-1]
    over_evidence["artifacts"].extend({**evidence, "artifactId": f"artifact-evidence-{index:04d}", "path": f"evidence/evidence-{index:04d}.png"} for index in range(3, 1003))
    with pytest.raises(ValidationError, match="evidence artifacts"):
        PackageManifestV2.model_validate(over_evidence)
    unsafe = copy.deepcopy(manifest)
    unsafe["artifacts"][0]["path"] = "../input.pdf"
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate(unsafe)


def test_v2_unacquired_source_cannot_claim_bytes_or_artifact_provenance():
    manifest = complete_manifest_v2()
    manifest["sources"].append({"bindingStatus": "unacquired-exclusion", "sourceId": "source-0004", "path": "incoming/unsafe", "acquisitionStatus": "unreadable", "issueCodes": ["document-unreadable"], "coverageState": "excluded-by-user", "decisionId": "decision-0006"})
    manifest["decisions"].append({"decisionId": "decision-0006", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "exclude-source", "actor": "user", "subjectRefs": ["source-0004"], "evidenceRefs": []})
    PackageManifestV2.model_validate(manifest)
    with_bytes = copy.deepcopy(manifest)
    with_bytes["sources"][-1]["size"] = 1
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate(with_bytes)
    provenance = copy.deepcopy(manifest)
    provenance["artifacts"][0]["sourceIds"].append("source-0004")
    with pytest.raises(ValidationError, match="unacquired"):
        PackageManifestV2.model_validate(provenance)


def test_v2_assignments_require_locators_and_exclusions_cover_only_manifest_decisions():
    assignments = complete_assignments_v2()
    missing_locator = copy.deepcopy(assignments)
    missing_locator["units"][0].pop("outputLocator")
    with pytest.raises(ValidationError):
        AssignmentsDocumentV2.model_validate(missing_locator)
    missing_decision = copy.deepcopy(assignments)
    missing_decision["exclusions"] = [{"recordType": "unit", "recordId": "unit-0003", "decisionId": "decision-9999", "reason": "duplicate"}]
    parsed = AssignmentsDocumentV2.model_validate(missing_decision)
    manifest = PackageManifestV2.model_validate(complete_manifest_v2())
    with pytest.raises(ValueError, match="exclusion decision"):
        parsed.validate_against_manifest(manifest)


def test_v2_assignments_and_roster_cross_validate_participants():
    assignments = AssignmentsDocumentV2.model_validate(complete_assignments_v2())
    roster = CanonicalRosterDocumentV2.model_validate({"schemaVersion": "2.0", "artifactId": "artifact-roster", "rows": [{"rosterRowId": "roster-row-0002", "values": {"name": "Synthetic Person 0001", "identity": "SYNTHETIC-IDENTITY-0001", "faCode": "FA-SYNTHETIC-001"}}]})
    with pytest.raises(ValueError, match="participant/roster mismatch"):
        assignments.validate_against_roster(roster)


def test_v2_valid_report_requires_completed_content_checks():
    report = {"schemaVersion": "2.0", "outcome": "valid", "packageStatus": "prepared", "checks": [], "errors": [], "warnings": [], "validatedAt": "2026-08-14T00:00:00Z", "validatorVersion": "validator-2.0.0", "packageId": "package-" + "b" * 64, "sourceObservationId": "observation-" + "c" * 64, "proposalDigest": _SHA, "manifestSha256": _SHA, "declaredArtifactSetSha256": "b" * 64}
    with pytest.raises(ValidationError, match="completed content checks"):
        ValidationReportV2.model_validate(report)
    assert ExceptionsDocumentV2.model_validate({"schemaVersion": "2.0", "items": []}).items == []


def test_v2_manifest_freezes_artifact_paths_and_rejects_cccd_or_path_aliases():
    cccd = complete_manifest_v2()
    cccd["artifacts"][-1]["kind"] = "cccd"
    with pytest.raises(ValidationError, match="cccd"):
        PackageManifestV2.model_validate(cccd)

    wrong_input_path = complete_manifest_v2()
    wrong_input_path["artifacts"][0]["path"] = "evidence/evidence-0001.png"
    with pytest.raises(ValidationError, match="input.pdf"):
        PackageManifestV2.model_validate(wrong_input_path)

    duplicate_path = complete_manifest_v2()
    duplicate_path["artifacts"][-1]["path"] = "evidence/evidence-0001.png"
    with pytest.raises(ValidationError, match="artifact paths"):
        PackageManifestV2.model_validate(duplicate_path)

    unsafe_evidence_name = complete_manifest_v2()
    unsafe_evidence_name["artifacts"][-1]["path"] = "evidence/other.png"
    with pytest.raises(ValidationError, match="evidence"):
        PackageManifestV2.model_validate(unsafe_evidence_name)


def test_v2_manifest_requires_contiguous_complete_pdf_page_coverage():
    empty = complete_manifest_v2(pdfPages=[])
    with pytest.raises(ValidationError, match="pdfPages"):
        PackageManifestV2.model_validate(empty)

    duplicate_source_page = complete_manifest_v2()
    duplicate_source_page["pdfPages"].append(copy.deepcopy(duplicate_source_page["pdfPages"][0]))
    with pytest.raises(ValidationError, match="source pages"):
        PackageManifestV2.model_validate(duplicate_source_page)

    non_contiguous_target = complete_manifest_v2()
    non_contiguous_target["pdfPages"][0]["targetPage"] = 2
    with pytest.raises(ValidationError, match="target pages"):
        PackageManifestV2.model_validate(non_contiguous_target)

    inconsistent_count = complete_manifest_v2()
    inconsistent_count["sources"][0]["pageCount"] = 2
    with pytest.raises(ValidationError, match="pageCount"):
        PackageManifestV2.model_validate(inconsistent_count)


def test_v2_manifest_requires_fa_code_and_unambiguous_roster_mapping():
    missing_fa = complete_manifest_v2()
    missing_fa.pop("faCode")
    with pytest.raises(ValidationError):
        PackageManifestV2.model_validate(missing_fa)

    missing_mapping = complete_manifest_v2()
    missing_mapping["rosterMapping"]["canonicalToSourceColumns"].pop("faCode")
    with pytest.raises(ValidationError, match="faCode"):
        PackageManifestV2.model_validate(missing_mapping)

    ambiguous_mapping = complete_manifest_v2()
    ambiguous_mapping["rosterMapping"]["canonicalToSourceColumns"]["identity"] = "Name"
    with pytest.raises(ValidationError, match="unambiguous"):
        PackageManifestV2.model_validate(ambiguous_mapping)

    with pytest.raises(ValidationError):
        CanonicalRosterDocumentV2.model_validate({"schemaVersion": "2.0", "artifactId": "artifact-roster", "rows": []})
    with pytest.raises(ValidationError):
        CanonicalRosterDocumentV2.model_validate({
            "schemaVersion": "2.0", "artifactId": "artifact-roster",
            "rows": [{"rosterRowId": "roster-row-0001", "values": {"name": "Synthetic Person 0001", "identity": "SYNTHETIC-IDENTITY-0001"}}],
        })


def test_v2_cross_validation_requires_exact_sources_locators_participants_and_decision_subjects():
    unknown_provenance = complete_manifest_v2()
    unknown_provenance["artifacts"][0]["sourceIds"] = ["source-9999"]
    with pytest.raises(ValidationError, match="artifact source"):
        PackageManifestV2.model_validate(unknown_provenance)

    manifest = PackageManifestV2.model_validate(complete_manifest_v2())
    wrong_locator = complete_assignments_v2()
    wrong_locator["units"][0]["outputLocator"]["artifactId"] = "artifact-roster"
    with pytest.raises(ValueError, match="locator artifact kind"):
        AssignmentsDocumentV2.model_validate(wrong_locator).validate_against_manifest(manifest)

    unknown_participant = complete_assignments_v2()
    unknown_participant["units"][0]["target"]["participantHandles"] = ["participant-9999"]
    with pytest.raises(ValueError, match="participant handle"):
        AssignmentsDocumentV2.model_validate(unknown_participant).validate_against_manifest(manifest)

    wrong_subject = complete_manifest_v2()
    wrong_subject["decisions"][0]["subjectRefs"] = ["unit-9999"]
    with pytest.raises(ValueError, match="decision subject"):
        AssignmentsDocumentV2.model_validate(complete_assignments_v2()).validate_against_manifest(
            PackageManifestV2.model_validate(wrong_subject)
        )

    duplicate_page_assignment = complete_assignments_v2()
    duplicate_page_assignment["units"].append({
        **copy.deepcopy(duplicate_page_assignment["units"][0]),
        "unitId": "unit-0005",
        "decisionId": "decision-0006",
    })
    duplicate_manifest = complete_manifest_v2()
    duplicate_manifest["decisions"].append({"decisionId": "decision-0006", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "accept-unit", "actor": "user", "subjectRefs": ["unit-0005"], "evidenceRefs": ["source-0001"]})
    with pytest.raises(ValueError, match="exactly one assignment"):
        AssignmentsDocumentV2.model_validate(duplicate_page_assignment).validate_against_manifest(
            PackageManifestV2.model_validate(duplicate_manifest)
        )

    unacquired_manifest = complete_manifest_v2()
    unacquired_manifest["sources"].append({"bindingStatus": "unacquired-exclusion", "sourceId": "source-0004", "path": "incoming/unsafe", "acquisitionStatus": "unreadable", "issueCodes": ["document-unreadable"], "coverageState": "excluded-by-user", "decisionId": "decision-0006"})
    unacquired_manifest["decisions"].append({"decisionId": "decision-0006", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "exclude-source", "actor": "user", "subjectRefs": ["source-0004"], "evidenceRefs": []})
    unacquired_assignment = complete_assignments_v2()
    unacquired_assignment["units"][0]["sourceId"] = "source-0004"
    with pytest.raises(ValueError, match="verified content"):
        AssignmentsDocumentV2.model_validate(unacquired_assignment).validate_against_manifest(
            PackageManifestV2.model_validate(unacquired_manifest)
        )

    missing_evidence_locator = complete_assignments_v2()
    missing_evidence_locator["units"] = [
        unit for unit in missing_evidence_locator["units"] if unit["unitId"] != "unit-0003"
    ]
    with pytest.raises(ValueError, match="evidence artifact"):
        AssignmentsDocumentV2.model_validate(missing_evidence_locator).validate_against_manifest(manifest)


def test_v2_fa_fields_reject_whitespace_without_canonicalizing_values():
    blank_manifest_fa = complete_manifest_v2()
    blank_manifest_fa["faCode"] = "   "
    with pytest.raises(ValidationError, match="faCode"):
        PackageManifestV2.model_validate(blank_manifest_fa)

    blank_mapping_fa = complete_manifest_v2()
    blank_mapping_fa["rosterMapping"]["canonicalToSourceColumns"]["faCode"] = "\t"
    with pytest.raises(ValidationError, match="faCode"):
        PackageManifestV2.model_validate(blank_mapping_fa)

    with pytest.raises(ValidationError, match="faCode"):
        CanonicalRosterDocumentV2.model_validate({
            "schemaVersion": "2.0", "artifactId": "artifact-roster",
            "rows": [{"rosterRowId": "roster-row-0001", "values": {"name": "Synthetic Person 0001", "identity": "SYNTHETIC-IDENTITY-0001", "faCode": "\n"}}],
        })


def test_v2_cross_validation_binds_pdf_targets_evidence_provenance_and_source_exclusions():
    manifest = PackageManifestV2.model_validate(complete_manifest_v2())
    wrong_pdf_target = complete_assignments_v2()
    wrong_pdf_target["units"][0]["outputLocator"]["targetPage"] = 2
    with pytest.raises(ValueError, match="target page"):
        AssignmentsDocumentV2.model_validate(wrong_pdf_target).validate_against_manifest(manifest)

    evidence_manifest = complete_manifest_v2()
    evidence_manifest["decisions"][3]["evidenceRefs"] = ["source-0002"]
    wrong_evidence_source = complete_assignments_v2()
    wrong_evidence_source["units"][2]["sourceId"] = "source-0002"
    with pytest.raises(ValueError, match="evidence provenance"):
        AssignmentsDocumentV2.model_validate(wrong_evidence_source).validate_against_manifest(
            PackageManifestV2.model_validate(evidence_manifest)
        )

    exclusion_manifest = complete_manifest_v2()
    exclusion_manifest["sources"].append({"bindingStatus": "unacquired-exclusion", "sourceId": "source-0004", "path": "incoming/unsafe", "acquisitionStatus": "unreadable", "issueCodes": ["document-unreadable"], "coverageState": "excluded-by-user", "decisionId": "decision-0006"})
    exclusion_manifest["decisions"].append({"decisionId": "decision-0006", "proposalVersion": "proposal-2.0", "proposalDigest": _SHA, "type": "exclude-source", "actor": "user", "subjectRefs": ["source-0004"], "evidenceRefs": []})
    source_exclusion = complete_assignments_v2()
    source_exclusion["exclusions"] = [{"recordType": "source", "recordId": "source-0004", "decisionId": "decision-0006", "reason": "unsupported"}]
    with pytest.raises(ValueError, match="acquisition status"):
        AssignmentsDocumentV2.model_validate(source_exclusion).validate_against_manifest(
            PackageManifestV2.model_validate(exclusion_manifest)
        )
