"""TDD coverage for the private approved-package snapshot boundary."""

from __future__ import annotations

import json
from io import BytesIO
import zipfile

import fitz
from openpyxl import Workbook
import pytest

from ctv_inspection import inspect_observation
from ctv_inventory import open_inventory_observation
from ctv_package_assignment import build_assignments
from ctv_inspection_model import InspectionLimits
from ctv_proposal import ProposalState
from intake_contract_v2 import PdfPageLocatorV2, RosterLocatorV2, WorksheetLocatorV2


_PRIVATE = ("Synthetic Person", "079123456781", "FA-SYNTHETIC-001")


def _source(tmp_path, *, headers=None, rows=None):
    source = tmp_path / "private-source"
    source.mkdir()
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Payment roster"
    sheet.append(headers or ("name", "identity", "faCode", "taxId", "birthDate", "bankAccount", "serviceFee", "product", "So tien"))
    for row in rows or (("Synthetic Person", "079123456781", "FA-SYNTHETIC-001", "0123456789", "1990-01-01", "123", "100", "Synthetic product", "100"),):
        sheet.append(row)
    workbook.save(source / "private-roster.xlsx")
    workbook.close()
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "HOP DONG DICH VU\nBEN A\nBEN B\nCHU KY")
    document.save(source / "private-contract.pdf")
    document.close()
    return source


def _approved_state(tmp_path, **source_kwargs):
    source = _source(tmp_path, **source_kwargs)
    context = open_inventory_observation(source)
    observation = context.__enter__()
    state = ProposalState.from_inspection(observation, inspect_observation(observation))
    roster = next(unit for unit in state.units if unit["unitKind"] == "worksheet")
    state.select_roster({"rosterUnitId": roster["unitId"]})
    for unit in state.units:
        if unit["unitId"] == roster["unitId"]:
            mapping = {
                "unitId": unit["unitId"], "decision": "accepted", "role": "payment-roster",
                "target": {"scope": "case", "participantHandles": []},
            }
        else:
            mapping = {
                "unitId": unit["unitId"], "decision": "accepted", "role": unit["suggestedRole"],
                "target": {"scope": "case", "participantHandles": []},
            }
        state.set_unit_decision(mapping)
    digest = state.approval_summary()["proposalDigest"]
    return context, state, digest


def _cache_formula_value(path, *, cell_reference, formula, cached_value):
    snapshot = path.read_bytes()
    output = BytesIO()
    with zipfile.ZipFile(BytesIO(snapshot), "r") as source:
        worksheet = source.read("xl/worksheets/sheet1.xml")
        original = (
            f'<c r="{cell_reference}"><f>{formula}</f><v></v></c>'.encode()
        )
        replacement = (
            f'<c r="{cell_reference}"><f>{formula}</f>'
            f'<v>{cached_value}</v></c>'
        ).encode()
        assert worksheet.count(original) == 1
        with zipfile.ZipFile(
            output, "w", compression=zipfile.ZIP_DEFLATED
        ) as target:
            for info in source.infolist():
                content = source.read(info)
                if info.filename == "xl/worksheets/sheet1.xml":
                    content = worksheet.replace(original, replacement)
                target.writestr(info.filename, content)
    path.write_bytes(output.getvalue())


def test_consume_freezes_one_private_approved_snapshot_and_invalidates_on_mutation(tmp_path):
    context, state, digest = _approved_state(tmp_path)
    try:
        approved_public = state.approve(digest)
        snapshot = state.consume_approved_package_snapshot(approved_public["proposalDigest"])
        assert snapshot.fa_code == "FA-SYNTHETIC-001"
        assert snapshot.roster_rows[0].participant_handle == "participant-0001"
        assert all(value not in repr(snapshot) for value in _PRIVATE)
        assert all(value not in repr(approved_public) for value in _PRIVATE)
        with pytest.raises(ValueError, match="approved package snapshot is unavailable"):
            state.consume_approved_package_snapshot(digest)
        state.set_unit_decision({
            "unitId": state.units[0]["unitId"], "decision": "excluded", "reason": "irrelevant",
        })
        with pytest.raises(ValueError, match="approved package snapshot is unavailable"):
            state.consume_approved_package_snapshot(digest)
    finally:
        context.__exit__(None, None, None)


def test_consumption_requires_the_exact_approved_digest(tmp_path):
    context, state, digest = _approved_state(tmp_path)
    try:
        state.approve(digest)
        with pytest.raises(ValueError, match="approved package snapshot is unavailable"):
            state.consume_approved_package_snapshot("0" * 64)
    finally:
        context.__exit__(None, None, None)


def test_package_snapshot_ignores_wholly_blank_roster_separator(tmp_path):
    rows = (
        (
            "Synthetic Person",
            "079123456781",
            "FA-SYNTHETIC-001",
            "0123456789",
            "1990-01-01",
            "123",
            "100",
            "Synthetic product",
            "100",
        ),
        (None, None, None, None, None, None, None, None, None),
        (
            "Other Person",
            "079123456782",
            "FA-SYNTHETIC-001",
            "0123456788",
            "1990-01-02",
            "456",
            "200",
            "Other product",
            "200",
        ),
    )
    context, state, digest = _approved_state(tmp_path, rows=rows)
    try:
        summary = state.approval_summary()
        assert summary["participantHandles"] == [
            "participant-0001",
            "participant-0002",
        ]
        assert "roster-row-invalid" not in summary["issueCodes"]
        state.approve(digest)
        snapshot = state.consume_approved_package_snapshot(digest)
        assert [row.row_index for row in snapshot.roster_rows] == [2, 4]
        assert snapshot.fa_code == "FA-SYNTHETIC-001"
    finally:
        context.__exit__(None, None, None)


def test_formula_only_trailing_roster_row_blocks_approval_before_builder(tmp_path):
    rows = (
        (
            "Synthetic Person",
            "079123456781",
            "FA-SYNTHETIC-001",
            "0123456789",
            "1990-01-01",
            "123",
            "100",
            "Synthetic product",
            "100",
        ),
        (None, None, None, None, None, None, None, None, "=1+1"),
    )
    context, state, digest = _approved_state(tmp_path, rows=rows)
    try:
        summary = state.approval_summary()
        assert summary["participantHandles"] == ["participant-0001"]
        assert "roster-row-invalid" in summary["issueCodes"]
        assert summary["readyToPrepare"] is False
        with pytest.raises(ValueError, match="proposal is not ready"):
            state.approve(digest)
    finally:
        context.__exit__(None, None, None)


def test_cached_formula_on_valid_roster_row_remains_approvable_and_private(tmp_path):
    rows = ((
        "Synthetic Person",
        "079123456781",
        "FA-SYNTHETIC-001",
        "0123456789",
        "1990-01-01",
        "123",
        "100",
        "Synthetic product",
        "=1+1",
    ),)
    source = _source(tmp_path, rows=rows)
    _cache_formula_value(
        source / "private-roster.xlsx",
        cell_reference="I2",
        formula="1+1",
        cached_value="2",
    )
    context = open_inventory_observation(source)
    observation = context.__enter__()
    try:
        inspection = inspect_observation(observation)
        state = ProposalState.from_inspection(observation, inspection)
        roster = next(unit for unit in state.units if unit["unitKind"] == "worksheet")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        for unit in state.units:
            state.set_unit_decision(
                {
                    "unitId": unit["unitId"],
                    "decision": "accepted",
                    "role": unit["suggestedRole"],
                    "target": {"scope": "case", "participantHandles": []},
                }
            )
        digest = state.approval_summary()["proposalDigest"]
        assert "roster-row-invalid" not in state.approval_summary()["issueCodes"]
        state.approve(digest)
        snapshot = state.consume_approved_package_snapshot(digest)
        assert len(snapshot.roster_rows) == 1
        assert "1+1" not in repr(snapshot)
    finally:
        context.__exit__(None, None, None)


@pytest.mark.parametrize(
    ("headers", "rows"),
    (
        (("name", "identity", "So tien"), (("Synthetic Person", "079123456781", "100"),)),
        (("name", "identity", "faCode", "faCode", "So tien"), (("Synthetic Person", "079123456781", "FA-SYNTHETIC-001", "FA-SYNTHETIC-001", "100"),)),
        (("name", "identity", "faCode", "So tien"), (("Synthetic Person", "079123456781", "", "100"),)),
        (("name", "identity", "faCode", "So tien"), (("Synthetic Person", "079123456781", "FA-SYNTHETIC-001", "100"), ("Other Person", "079123456782", "FA-SYNTHETIC-002", "100"))),
        (("name", "identity", "faCode", "So tien"), (("Synthetic Person", "079123456781", "=CONCAT(\"FA\",\"-SYNTHETIC-001\")", "100"),)),
    ),
)
def test_package_only_fa_code_blockers_do_not_widen_public_proposal_readiness(tmp_path, headers, rows):
    context, state, digest = _approved_state(tmp_path, headers=headers, rows=rows)
    try:
        assert state.approval_summary()["readyToPrepare"] is True
        approved = state.approve(digest)
        with pytest.raises(ValueError, match="approved package snapshot is unavailable"):
            state.consume_approved_package_snapshot(approved["proposalDigest"])
        assert all(value not in repr(approved) for value in _PRIVATE)
    finally:
        context.__exit__(None, None, None)


def test_package_consumption_rejects_before_approval_wrong_roster_scope_and_no_pdf(tmp_path):
    context, state, digest = _approved_state(tmp_path)
    try:
        with pytest.raises(ValueError, match="approved package snapshot is unavailable"):
            state.consume_approved_package_snapshot(digest)
        roster = next(unit for unit in state.units if unit["unitKind"] == "worksheet")
        state.set_unit_decision({
            "unitId": roster["unitId"], "decision": "accepted", "role": "payment-roster",
            "target": {"scope": "individual", "participantHandles": ["participant-0001"]},
        })
        digest = state.approval_summary()["proposalDigest"]
        state.approve(digest)
        with pytest.raises(ValueError, match="approved package snapshot is unavailable"):
            state.consume_approved_package_snapshot(digest)
        state.set_unit_decision({
            "unitId": roster["unitId"], "decision": "excluded", "reason": "irrelevant",
        })
        for unit in state.units:
            if unit["unitKind"] == "pdf-page":
                state.set_unit_decision({"unitId": unit["unitId"], "decision": "excluded", "reason": "irrelevant"})
        digest = state.approval_summary()["proposalDigest"]
        state.approve(digest)
        with pytest.raises(ValueError, match="approved package snapshot is unavailable"):
            state.consume_approved_package_snapshot(digest)
    finally:
        context.__exit__(None, None, None)


def test_build_assignments_is_complete_deterministic_and_private_value_free(tmp_path):
    context, state, digest = _approved_state(tmp_path)
    try:
        state.approve(digest)
        snapshot = state.consume_approved_package_snapshot(digest)
        locators = {}
        for unit in snapshot.unit_decisions:
            if unit.unit_kind == "worksheet":
                locators[unit.unit_id] = RosterLocatorV2(kind="roster", artifactId="artifact-roster", worksheetIndex=1)
            else:
                locators[unit.unit_id] = PdfPageLocatorV2(kind="pdf-page", artifactId="artifact-inputpdf", targetPage=1)
        result = build_assignments(snapshot, package_id="package-" + "a" * 64, locators=locators)
        document = result.document.model_dump(by_alias=True)
        assert [participant["participantHandle"] for participant in document["participants"]] == ["participant-0001"]
        assert [unit["unitId"] for unit in document["units"]] == sorted(locators)
        rendered = json.dumps(document, sort_keys=True)
        assert all(value not in rendered for value in _PRIVATE)
        with pytest.raises(ValueError, match="complete"):
            build_assignments(snapshot, package_id="package-" + "a" * 64, locators={})
        with pytest.raises(ValueError, match="complete"):
            build_assignments(snapshot, package_id="package-" + "a" * 64, locators={**locators, "unit-9999": locators[snapshot.roster_unit_id]})
        wrong = dict(locators)
        pdf_unit = next(item for item in snapshot.unit_decisions if item.unit_kind == "pdf-page")
        wrong[pdf_unit.unit_id] = WorksheetLocatorV2(kind="worksheet", artifactId="artifact-evidence", worksheetIndex=1)
        with pytest.raises(ValueError, match="locator"):
            build_assignments(snapshot, package_id="package-" + "a" * 64, locators=wrong)
    finally:
        context.__exit__(None, None, None)


@pytest.mark.parametrize(
    ("acquisition_status", "coverage_state", "issue_codes", "expected_reason"),
    (
        ("opaque", "duplicate", ("opaque-archive",), "duplicate"),
        ("unreadable", "excluded-by-user", ("document-unreadable",), "unreadable"),
        ("encrypted", "excluded-by-user", ("document-encrypted",), "encrypted"),
        ("unsupported", "excluded-by-user", ("unsupported-document-type",), "unsupported"),
        ("over-limit", "excluded-by-user", ("document-over-limit",), "over-limit"),
    ),
)
def test_source_only_exclusion_reason_is_derived_from_frozen_acquisition_facts(
    tmp_path, acquisition_status, coverage_state, issue_codes, expected_reason
):
    source = _source(tmp_path)
    private_marker = "PRIVATE-SOURCE-ONLY-079123456789"
    if acquisition_status == "opaque":
        archive = BytesIO()
        with zipfile.ZipFile(archive, "w") as contents:
            contents.writestr("private.txt", private_marker)
        (source / "source-only.zip").write_bytes(archive.getvalue())
        limits = InspectionLimits()
    elif acquisition_status == "unreadable":
        (source / "source-only.pdf").write_bytes(b"%PDF-1.7\n" + private_marker.encode())
        limits = InspectionLimits()
    elif acquisition_status == "encrypted":
        document = fitz.open()
        document.new_page()
        encrypted = BytesIO()
        document.save(encrypted, encryption=fitz.PDF_ENCRYPT_AES_256, user_pw="synthetic-user", owner_pw="synthetic-owner")
        document.close()
        (source / "source-only.pdf").write_bytes(encrypted.getvalue())
        limits = InspectionLimits()
    elif acquisition_status == "unsupported":
        (source / "source-only.bin").write_bytes(private_marker.encode())
        limits = InspectionLimits()
    else:
        source_bytes = (source / "private-contract.pdf").read_bytes()
        (source / "source-only.pdf").write_bytes(source_bytes + private_marker.encode())
        limits = InspectionLimits(max_pdf_source_bytes=len(source_bytes))
    context = open_inventory_observation(source)
    observation = context.__enter__()
    try:
        state = ProposalState.from_inspection(observation, inspect_observation(observation, limits=limits))
        roster = next(unit for unit in state.units if unit["unitKind"] == "worksheet")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        for unit in state.units:
            state.set_unit_decision({
                "unitId": unit["unitId"], "decision": "accepted", "role": unit["suggestedRole"],
                "target": {"scope": "case", "participantHandles": []},
            })
        unit_evidence_ids = {unit["evidenceId"] for unit in state.units}
        for record in state.sources:
            if record["evidenceId"] not in unit_evidence_ids:
                state.set_source_disposition({
                    "evidenceId": record["evidenceId"], "decision": "excluded",
                    "reason": "duplicate" if coverage_state == "duplicate" else "irrelevant",
                })
        digest = state.approval_summary()["proposalDigest"]
        assert state.approval_summary()["readyToPrepare"] is True
        state.approve(digest)
        snapshot = state.consume_approved_package_snapshot(digest)
        frozen = snapshot.source_dispositions
        assert len(frozen) == 1
        assert (frozen[0].acquisition_status, frozen[0].coverage_state, frozen[0].issue_codes) == (
            acquisition_status, coverage_state, issue_codes,
        )
        locators = {
            item.unit_id: (
                RosterLocatorV2(kind="roster", artifactId="artifact-roster", worksheetIndex=1)
                if item.unit_kind == "worksheet"
                else PdfPageLocatorV2(kind="pdf-page", artifactId="artifact-inputpdf", targetPage=1)
            )
            for item in snapshot.unit_decisions
        }
        result = build_assignments(snapshot, package_id="package-" + "b" * 64, locators=locators)
        source_exclusion = next(
            record for record in result.document.exclusions if record.record_type == "source"
        )
        assert source_exclusion.reason == expected_reason
        assert source_exclusion.record_id.startswith("source-")
        rendered = json.dumps(result.document.model_dump(by_alias=True), sort_keys=True)
        assert private_marker not in repr(snapshot)
        assert private_marker not in rendered
        assert "source-only" not in rendered
    finally:
        context.__exit__(None, None, None)
