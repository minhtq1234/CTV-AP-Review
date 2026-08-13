from io import BytesIO

from openpyxl import Workbook
from PIL import Image
import pytest

from ctv_proposal import ProposalState
from ctv_inspection import inspect_observation
from ctv_inventory import open_inventory_observation


def _roster_bytes(rows=(("Alice", "CTV-001"), ("Bao", "CTV-002"))):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Payment roster"
    sheet.append(("Ho ten", "Ma so nhan vien", "So tien"))
    for name, identity in rows:
        sheet.append((name, identity, 100))
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _source(tmp_path, *, roster_rows=(("Alice", "CTV-001"), ("Bao", "CTV-002"))):
    source = tmp_path / "source"
    source.mkdir()
    (source / "roster.xlsx").write_bytes(_roster_bytes(roster_rows))
    image = BytesIO()
    with Image.new("RGB", (10, 10)) as value:
        value.save(image, format="PNG")
    (source / "identity.png").write_bytes(image.getvalue())
    return source


def _state(tmp_path):
    source = _source(tmp_path)
    observation_context = open_inventory_observation(source)
    observation = observation_context.__enter__()
    inspection = inspect_observation(observation)
    return observation_context, observation, ProposalState.from_inspection(observation, inspection)


def test_caller_owned_observation_is_inspected_without_being_closed(tmp_path):
    source = _source(tmp_path)
    with open_inventory_observation(source) as observation:
        inspection = inspect_observation(observation)
        assert inspection.observation_id == observation.observation_id
        assert observation.snapshot(inspection.sources[0].evidence_id, max_bytes=25 * 1024 * 1024)


def test_selected_roster_maps_usable_rows_to_opaque_handles_in_row_order(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        assert state.approval_summary()["participantHandles"] == [
            "participant-0001", "participant-0002"
        ]
        assert "Alice" not in repr(state.approval_summary())
    finally:
        context.__exit__(None, None, None)


def test_roster_duplicate_blank_and_malformed_rows_block_readiness_with_fixed_issues(tmp_path):
    source = _source(tmp_path, roster_rows=(("Alice", "CTV-001"), ("", ""), ("Bao", "CTV-001")))
    with open_inventory_observation(source) as observation:
        state = ProposalState.from_inspection(observation, inspect_observation(observation))
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        summary = state.approval_summary()
        assert summary["readyToPrepare"] is False
        assert {"roster-row-invalid", "roster-identity-duplicate"} <= set(summary["issueCodes"])


def test_assignments_require_exact_mappings_and_resolve_every_unit_and_source(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        with pytest.raises(ValueError):
            state.set_unit_decision({"unitId": roster["unitId"], "decision": "accepted"})
        for unit in state.units:
            if unit["unitId"] == roster["unitId"]:
                state.set_unit_decision({
                    "unitId": unit["unitId"], "decision": "excluded", "reason": "irrelevant"
                })
            else:
                state.set_unit_decision({
                    "unitId": unit["unitId"], "decision": "accepted", "role": "identity-front",
                    "target": {"scope": "individual", "participantHandles": ["participant-0001"]},
                })
        for source in state.sources:
            if source["evidenceId"] not in {unit["evidenceId"] for unit in state.units}:
                state.set_source_disposition({
                    "evidenceId": source["evidenceId"], "decision": "excluded", "reason": "irrelevant"
                })
        assert state.approval_summary()["readyToPrepare"] is True
    finally:
        context.__exit__(None, None, None)


def test_digest_excludes_private_roster_values_and_changes_for_each_decision(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        before = state.approval_summary()["proposalDigest"]
        state.set_unit_decision({"unitId": roster["unitId"], "decision": "excluded", "reason": "irrelevant"})
        after = state.approval_summary()["proposalDigest"]
        assert before != after
        assert "Alice" not in repr(state.approval_summary())
        assert "CTV-001" not in repr(state.approval_summary())
    finally:
        context.__exit__(None, None, None)


def test_approval_is_privacy_safe_and_rejects_a_changed_observation(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        for unit in state.units:
            state.set_unit_decision({"unitId": unit["unitId"], "decision": "excluded", "reason": "irrelevant"})
        digest = state.approval_summary()["proposalDigest"]
        approved = state.approve(digest)
        assert approved["approval"] == {"status": "user-approved", "approvedProposalDigest": digest}
        assert "Alice" not in repr(approved)
    finally:
        context.__exit__(None, None, None)


def test_draft_and_cancelled_results_have_their_fixed_public_shapes(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        assert set(state.draft_result()) == {"version", "outcome", "observationId", "readyToPrepare", "counts", "issueCodes"}
        assert state.cancelled_result() == {"version": "1.0", "outcome": "cancelled", "readyToPrepare": False}
    finally:
        context.__exit__(None, None, None)
