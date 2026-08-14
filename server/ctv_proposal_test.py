from io import BytesIO

from openpyxl import Workbook
from PIL import Image
import pytest

from ctv_proposal import ProposalState
from ctv_inspection import inspect_observation
from ctv_inventory import InventoryError, open_inventory_observation


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


def _source_with_two_rosters(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    workbook = Workbook()
    first = workbook.active
    first.title = "First roster"
    first.append(("Ho ten", "Ma so nhan vien", "So tien"))
    first.append(("Alice", "CTV-001", 100))
    first.append(("Bao", "CTV-002", 100))
    second = workbook.create_sheet("Second roster")
    second.append(("Ho ten", "Ma so nhan vien", "So tien"))
    second.append(("Carol", "CTV-101", 100))
    second.append(("Duy", "CTV-102", 100))
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    (source / "rosters.xlsx").write_bytes(output.getvalue())
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


def test_local_participant_display_keeps_name_and_masked_identity_out_of_public_results(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        assert state.participants_for_local_review() == [
            {"participantHandle": "participant-0001", "name": "Alice", "identityHint": "***-001"},
            {"participantHandle": "participant-0002", "name": "Bao", "identityHint": "***-002"},
        ]
        public = state.draft_result()
        assert "Alice" not in repr(public)
        assert "CTV-001" not in repr(public)
        assert "***-001" not in repr(public)
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


def test_header_only_roster_is_invalid_and_has_no_usable_participants(tmp_path):
    source = _source(tmp_path, roster_rows=())
    with open_inventory_observation(source) as observation:
        state = ProposalState.from_inspection(observation, inspect_observation(observation))
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        assert state.approval_summary()["participantHandles"] == []
        assert "roster-row-invalid" in state.approval_summary()["issueCodes"]
        assert state.approval_summary()["readyToPrepare"] is False


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
                    "unitId": unit["unitId"], "decision": "reassigned", "role": "identity-front",
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


def test_roster_change_invalidates_existing_participant_targeted_assignments(tmp_path):
    source = _source_with_two_rosters(tmp_path)
    with open_inventory_observation(source) as observation:
        state = ProposalState.from_inspection(observation, inspect_observation(observation))
        rosters = [unit for unit in state.units if unit["suggestedRole"] == "payment-roster"]
        state.select_roster({"rosterUnitId": rosters[0]["unitId"]})
        state.set_unit_decision({
            "unitId": rosters[0]["unitId"], "decision": "accepted", "role": "payment-roster",
            "target": {"scope": "individual", "participantHandles": ["participant-0001"]},
        })
        state.select_roster({"rosterUnitId": rosters[1]["unitId"]})
        assert state.approval_summary()["counts"]["unresolved"] == len(state.units)


def test_accepted_and_reassigned_enforce_their_distinct_suggested_role_meanings(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        unknown = next(unit for unit in state.units if unit["suggestedRole"] == "unknown")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        with pytest.raises(ValueError):
            state.set_unit_decision({
                "unitId": roster["unitId"], "decision": "reassigned", "role": "payment-roster",
                "target": {"scope": "individual", "participantHandles": ["participant-0001"]},
            })
        with pytest.raises(ValueError):
            state.set_unit_decision({
                "unitId": unknown["unitId"], "decision": "accepted", "role": "identity-front",
                "target": {"scope": "individual", "participantHandles": ["participant-0001"]},
            })
        state.set_unit_decision({
            "unitId": unknown["unitId"], "decision": "reassigned", "role": "identity-front",
            "target": {"scope": "individual", "participantHandles": ["participant-0001"]},
        })
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


def test_approved_proposal_stays_private_and_observation_close_rejects_source_mutation(tmp_path):
    source = _source(tmp_path)
    with pytest.raises(InventoryError, match="inventory-tree-changed"):
        with open_inventory_observation(source) as observation:
            state = ProposalState.from_inspection(observation, inspect_observation(observation))
            roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
            state.select_roster({"rosterUnitId": roster["unitId"]})
            for unit in state.units:
                state.set_unit_decision({"unitId": unit["unitId"], "decision": "excluded", "reason": "irrelevant"})
            digest = state.approval_summary()["proposalDigest"]
            approved = state.approve(digest)
            assert approved["approval"] == {"status": "user-approved", "approvedProposalDigest": digest}
            assert "Alice" not in repr(approved)
            (source / "identity.png").write_bytes(b"changed after approval")


def test_draft_and_cancelled_results_have_their_fixed_public_shapes(tmp_path):
    context, observation, state = _state(tmp_path)
    try:
        assert set(state.draft_result()) == {"version", "outcome", "observationId", "readyToPrepare", "counts", "issueCodes"}
        assert state.cancelled_result() == {"version": "1.0", "outcome": "cancelled", "readyToPrepare": False}
    finally:
        context.__exit__(None, None, None)


def test_roster_switch_keeps_public_digest_and_review_values_private(tmp_path):
    source = _source_with_two_rosters(tmp_path)
    with open_inventory_observation(source) as observation:
        state = ProposalState.from_inspection(observation, inspect_observation(observation))
        rosters = [unit for unit in state.units if unit["suggestedRole"] == "payment-roster"]
        state.select_roster({"rosterUnitId": rosters[0]["unitId"]})
        first = state.approval_summary()
        state.select_roster({"rosterUnitId": rosters[1]["unitId"]})
        second = state.approval_summary()
        assert first["proposalDigest"] != second["proposalDigest"]
        assert all(value not in repr(second) for value in ("Alice", "CTV-001", "Carol", "CTV-101"))
