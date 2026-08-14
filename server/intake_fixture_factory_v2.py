"""Materialize production-backed synthetic intake v2 fixtures for tests."""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from datetime import date, datetime
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

import fitz
from openpyxl import Workbook
from PIL import Image

from ctv_inspection import inspect_observation
from ctv_inspection_workbook import _canonical_package_workbook_bytes
from ctv_inventory import open_inventory_observation
from ctv_package_builder import (
    ArtifactReceipt,
    RenderedArtifact,
    _canonical_json_bytes,
    build_manifest_bytes,
    create_build_plan,
    iter_rendered_artifacts,
)
from ctv_proposal import ProposalState
from intake_contract_v2 import AssignmentsDocumentV2, PackageManifestV2


@dataclass(frozen=True)
class MaterializedV2Fixture:
    package_dir: Path
    source_dir: Path
    manifest: PackageManifestV2
    assignments: AssignmentsDocumentV2
    observation_id: str
    proposal_digest: str
    manifest_sha256: str


def _fixed_workbook_bytes(sheets) -> bytes:
    workbook = Workbook()
    workbook.remove(workbook.active)
    fixed = datetime(1980, 1, 1)
    workbook.properties.created = fixed
    workbook.properties.modified = fixed
    for title, rows in sheets:
        worksheet = workbook.create_sheet(title)
        for row in rows:
            worksheet.append(row)
    return _canonical_package_workbook_bytes(workbook, max_bytes=25 * 1024 * 1024)


def _write_sources(source_dir: Path) -> None:
    source_dir.mkdir(mode=0o700)

    document = fitz.open()
    output = BytesIO()
    try:
        for page_number in range(1, 5):
            page = document.new_page()
            page.insert_text(
                (72, 72),
                "HOP DONG DICH VU SYNTHETIC "
                f"PAGE {page_number}\nBEN A\nBEN B\nCHU KY",
            )
        document.set_metadata({})
        fixed_id = "0123456789abcdef0123456789abcdef"
        document.xref_set_key(-1, "ID", f"[<{fixed_id}><{fixed_id}>]")
        document.save(output, no_new_id=1)
    finally:
        document.close()
    (source_dir / "a-pages.pdf").write_bytes(output.getvalue())

    image_bytes = BytesIO()
    with Image.new("RGB", (3, 2), (10, 20, 30)) as image:
        image.save(image_bytes, format="PNG", compress_level=9, optimize=False)
    (source_dir / "b-image.png").write_bytes(image_bytes.getvalue())

    evidence_bytes = _fixed_workbook_bytes(
        (
            ("Synthetic support one", (("Reference", "Amount"), ("SYN-1", 10))),
            ("Synthetic support two", (("Reference", "Amount"), ("SYN-2", 20))),
        )
    )
    (source_dir / "c-evidence.xlsx").write_bytes(evidence_bytes)
    (source_dir / "d-excluded.bin").write_bytes(
        b"SYNTHETIC-EXCLUDED-BYTES-079123456789"
    )
    roster_bytes = _fixed_workbook_bytes(
        ((
            "Payment roster",
            (
                (
                    "name", "identity", "faCode", "taxId", "birthDate",
                    "bankAccount", "serviceFee", "product", "So tien",
                ),
                (
                    "Synthetic Person 1", "079123456781", "FA-SYNTHETIC-001",
                    "TAX-1", date(1990, 1, 1), "BANK-1", "100", "Product 1", "100",
                ),
                (
                    "Synthetic Person 2", "079123456782", "FA-SYNTHETIC-001",
                    "TAX-2", "1990-01-02", "BANK-2", "200", "Product 2", "200",
                ),
            ),
        ),)
    )
    (source_dir / "z-roster.xlsx").write_bytes(roster_bytes)


def _approve(
    observation,
    inspection,
    *,
    unit_exclusion_reason: str | None = None,
    source_exclusion_reason: str = "irrelevant",
):
    state = ProposalState.from_inspection(observation, inspection)
    roster = next(
        unit for unit in state.units if unit["suggestedRole"] == "payment-roster"
    )
    state.select_roster({"rosterUnitId": roster["unitId"]})
    pdf_targets = {
        "unit-0001": ("individual", ["participant-0001"]),
        "unit-0002": ("shared", ["participant-0001", "participant-0002"]),
        "unit-0003": ("individual", ["participant-0002"]),
        "unit-0004": ("case", []),
    }
    excluded_unit_id = next(
        (
            unit["unitId"]
            for unit in state.units
            if unit["unitKind"] == "image"
        ),
        None,
    )
    for unit in state.units:
        if unit_exclusion_reason is not None and unit["unitId"] == excluded_unit_id:
            state.set_unit_decision({
                "unitId": unit["unitId"],
                "decision": "excluded",
                "reason": unit_exclusion_reason,
            })
            continue
        if unit["unitId"] == roster["unitId"]:
            role, target = "payment-roster", ("case", [])
        elif unit["unitKind"] == "pdf-page":
            role, target = "service-contract", pdf_targets[unit["unitId"]]
        elif unit["unitKind"] == "image":
            role, target = "identity-front", ("individual", ["participant-0001"])
        else:
            role, target = "other-supporting-evidence", ("case", [])
        decision = "accepted" if unit["suggestedRole"] == role else "reassigned"
        state.set_unit_decision({
            "unitId": unit["unitId"],
            "decision": decision,
            "role": role,
            "target": {
                "scope": target[0],
                "participantHandles": target[1],
            },
        })
    unit_evidence_ids = {unit["evidenceId"] for unit in state.units}
    for source in state.sources:
        if source["evidenceId"] not in unit_evidence_ids:
            state.set_source_disposition({
                "evidenceId": source["evidenceId"],
                "decision": "excluded",
                "reason": source_exclusion_reason,
            })
    digest = state.approval_summary()["proposalDigest"]
    state.approve(digest)
    return state.consume_approved_package_snapshot(digest)


def _invalid_assignment(
    rendered: tuple[RenderedArtifact, ...],
) -> tuple[RenderedArtifact, ...]:
    assignments_artifact = next(
        item for item in rendered if item.kind == "assignments"
    )
    document = json.loads(assignments_artifact.content)
    document["units"][0]["decisionId"] = "decision-missing"
    content = _canonical_json_bytes(document)
    return tuple(
        dataclasses.replace(item, content=content)
        if item is assignments_artifact
        else item
        for item in rendered
    )


def materialize_v2_fixture(
    name: str,
    output: Path,
    include_receipt: bool = False,
    *,
    unit_exclusion_reason: str | None = None,
    source_exclusion_reason: str = "irrelevant",
) -> MaterializedV2Fixture:
    """Generate one bounded fixture through inspection, approval, and Task 4."""
    if name not in {"complete", "invalid-assignment"}:
        raise ValueError("unsupported-v2-fixture")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    source_dir = output / "source"
    package_dir = output / "package"
    _write_sources(source_dir)
    package_dir.mkdir(mode=0o700)

    with open_inventory_observation(source_dir) as observation:
        inspection = inspect_observation(observation)
        approved = _approve(
            observation,
            inspection,
            unit_exclusion_reason=unit_exclusion_reason,
            source_exclusion_reason=source_exclusion_reason,
        )
        plan = create_build_plan(observation, inspection, approved)
        first = tuple(iter_rendered_artifacts(plan, observation))
        second = tuple(iter_rendered_artifacts(plan, observation))
        if [(item.path, item.content) for item in first] != [
            (item.path, item.content) for item in second
        ]:
            raise RuntimeError("v2-fixture-nondeterministic")
        rendered = _invalid_assignment(first) if name == "invalid-assignment" else first
        receipts = tuple(ArtifactReceipt.from_rendered(item) for item in rendered)
        manifest_bytes = build_manifest_bytes(plan, receipts)
        manifest_sha256 = sha256(manifest_bytes).hexdigest()
        for item in rendered:
            target = package_dir.joinpath(*item.path.split("/"))
            target.parent.mkdir(mode=0o700, exist_ok=True)
            target.write_bytes(item.content)
        (package_dir / "case-manifest.json").write_bytes(manifest_bytes)

        if include_receipt:
            from intake_package_validator import _PackageReader
            from intake_package_validator_v2 import (
                V2ValidationExpectation,
                canonical_v2_receipt_bytes,
                validate_v2_content_reader,
            )

            reader, failure = _PackageReader.open(package_dir)
            if reader is None or failure is not None:
                raise RuntimeError("v2-fixture-reader-unavailable")
            try:
                content = validate_v2_content_reader(
                    reader,
                    observation,
                    V2ValidationExpectation(
                        observation_id=observation.observation_id,
                        proposal_digest=approved.proposal_digest,
                        expected_manifest_sha256=manifest_sha256,
                    ),
                )
            finally:
                reader.close()
            if content.report.outcome != "valid":
                raise ValueError("v2-fixture-content-invalid")
            (package_dir / "validation-report.json").write_bytes(
                canonical_v2_receipt_bytes(content)
            )

        manifest = PackageManifestV2.model_validate(json.loads(manifest_bytes))
        assignment_bytes = next(
            item.content for item in rendered if item.kind == "assignments"
        )
        assignments = AssignmentsDocumentV2.model_validate(json.loads(assignment_bytes))
        return MaterializedV2Fixture(
            package_dir=package_dir,
            source_dir=source_dir,
            manifest=manifest,
            assignments=assignments,
            observation_id=observation.observation_id,
            proposal_digest=approved.proposal_digest,
            manifest_sha256=manifest_sha256,
        )
