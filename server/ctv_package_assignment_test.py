"""TDD coverage for the private approved-package snapshot boundary."""

from __future__ import annotations

import json
from dataclasses import replace
from io import BytesIO

import fitz
from openpyxl import Workbook
import pytest

from ctv_inspection import inspect_observation
from ctv_inventory import open_inventory_observation
from ctv_package_assignment import build_assignments
from ctv_proposal import ProposalState, SourceDispositionSnapshot
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
    ),
)
def test_source_only_exclusion_reason_is_derived_from_frozen_acquisition_facts(
    tmp_path, acquisition_status, coverage_state, issue_codes, expected_reason
):
    context, state, digest = _approved_state(tmp_path)
    try:
        state.approve(digest)
        snapshot = state.consume_approved_package_snapshot(digest)
        snapshot = replace(snapshot, source_dispositions=(SourceDispositionSnapshot(
            evidence_id="evidence-0099", decision="excluded",
            acquisition_status=acquisition_status, coverage_state=coverage_state,
            issue_codes=issue_codes,
        ),))
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
    finally:
        context.__exit__(None, None, None)
