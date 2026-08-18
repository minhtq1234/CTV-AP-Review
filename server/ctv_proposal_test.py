from io import BytesIO
import json

from openpyxl import Workbook
from PIL import Image
import pytest

from ctv_grouping_evidence import GroupingEvidence
from ctv_proposal import ProposalState
from ctv_inspection import inspect_observation
from ctv_inspection_model import (
    InspectionResult,
    InspectionSource,
    InspectionTotals,
    InspectionUnit,
)
from ctv_inventory import InventoryError, InventoryObservation, open_inventory_observation


def _roster_bytes(rows=(("Alice", "CTV-001"), ("Bao", "CTV-002"))):
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Payment roster"
    sheet.append(("Ho ten", "Ma so nhan vien", "faCode", "So tien"))
    for row in rows:
        if len(row) == 2:
            sheet.append((*row, "FA-SYNTHETIC-001", 100))
        elif len(row) == 3 and any(value is not None for value in row):
            sheet.append((row[0], row[1], "FA-SYNTHETIC-001", row[2]))
        else:
            sheet.append(row)
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
    first.append(("Ho ten", "Ma so nhan vien", "faCode", "So tien"))
    first.append(("Alice", "CTV-001", "FA-SYNTHETIC-001", 100))
    first.append(("Bao", "CTV-002", "FA-SYNTHETIC-001", 100))
    second = workbook.create_sheet("Second roster")
    second.append(("Ho ten", "Ma so nhan vien", "faCode", "So tien"))
    second.append(("Carol", "CTV-101", "FA-SYNTHETIC-002", 100))
    second.append(("Duy", "CTV-102", "FA-SYNTHETIC-002", 100))
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


def _grouping_state(tmp_path, source_roles, *, source_only=()):
    source = tmp_path / "generated-source"
    source.mkdir()
    (source / "roster.xlsx").write_bytes(_roster_bytes())
    context = open_inventory_observation(source)
    observation = context.__enter__()
    roster_inspection = inspect_observation(observation)
    roster_unit = roster_inspection.units[0]
    units = [roster_unit]
    sources = [roster_inspection.sources[0]]
    facts = GroupingEvidence()
    facts.capture(
        roster_unit.evidence_id,
        roster_unit.unit_kind,
        roster_unit.unit_index,
        "payment roster",
    )
    unit_number = 2
    for evidence_number, roles in enumerate(source_roles, start=2):
        evidence_id = f"evidence-{evidence_number:04d}"
        sources.append(
            InspectionSource(
                evidence_id=evidence_id,
                detected_type="pdf",
                inspection_status="inspected",
                unit_count=len(roles),
                issue_codes=(),
            )
        )
        for unit_index, role in enumerate(roles, start=1):
            unit = InspectionUnit(
                unit_id=f"unit-{unit_number:04d}",
                evidence_id=evidence_id,
                unit_kind="pdf-page",
                unit_index=unit_index,
                suggested_role=role,
                confidence_band="none" if role == "unknown" else "high",
                needs_user_review=role == "unknown",
                inspection_method="embedded-text",
                signal_codes=(),
                issue_codes=(),
            )
            units.append(unit)
            facts.capture(
                evidence_id,
                "pdf-page",
                unit_index,
                "unclassified continuation"
                if role == "unknown"
                else f"whole case {role} continuation",
            )
            unit_number += 1
    for status, detected_type, issue_codes in source_only:
        evidence_number = len(sources) + 1
        sources.append(
            InspectionSource(
                evidence_id=f"evidence-{evidence_number:04d}",
                detected_type=detected_type,
                inspection_status=status,
                unit_count=None if status in {"unreadable", "encrypted", "over-limit"} else 0,
                issue_codes=issue_codes,
            )
        )
    issue_count = sum(len(source.issue_codes) for source in sources)
    inspection = InspectionResult(
        inspection_version="1.0",
        inspection_status="complete-with-issues" if issue_count else "complete",
        observation_id=observation.observation_id,
        totals=InspectionTotals(
            sources=len(sources),
            units=len(units),
            classified=sum(unit.suggested_role != "unknown" for unit in units),
            unknown=sum(unit.suggested_role == "unknown" for unit in units),
            needs_user_review=sum(unit.needs_user_review for unit in units),
            issues=issue_count,
        ),
        sources=tuple(sources),
        units=tuple(units),
    )
    state = ProposalState.from_inspection(
        observation,
        inspection,
        _grouping_evidence=facts,
    )
    return context, state


def test_automatic_groups_leave_only_exact_exception_clusters_unresolved(tmp_path):
    context, state = _grouping_state(
        tmp_path,
        (
            ("service-contract",) * 10,
            ("unknown", "unknown"),
            ("unknown",),
        ),
    )
    try:
        local = state.local_review_snapshot()

        assert set(local) == {"roster", "review", "summary"}
        assert local["roster"]["status"] == "selected"
        assert local["review"]["coverage"] == {
            "groups": 4,
            "automaticallyOrganizedUnits": 11,
            "exceptionClusters": 2,
            "exceptionUnits": 3,
            "unaccountedUnits": 0,
        }
        assert len(local["review"]["exceptions"]) == 2
        assert state.approval_summary()["readyToPrepare"] is False
    finally:
        context.__exit__(None, None, None)


def test_local_review_snapshot_is_ready_after_automatic_groups_need_no_exceptions(
    tmp_path,
):
    context, state = _grouping_state(
        tmp_path,
        (("service-contract", "service-contract"),),
    )
    try:
        local = state.local_review_snapshot()
        expected_count_keys = {
            "sources",
            "units",
            "participants",
            "accepted",
            "reassigned",
            "excluded",
            "unresolved",
        }

        assert local["review"]["exceptions"] == []
        assert local["summary"]["readyToPrepare"] is True
        assert set(local["summary"]["counts"]) == expected_count_keys
        digest = state.approval_summary()["proposalDigest"]
        assert set(state.approve(digest)["counts"]) == expected_count_keys
    finally:
        context.__exit__(None, None, None)


def _review_bytes(state):
    return json.dumps(
        state.local_review_snapshot(),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def test_resolve_exception_assigns_exact_cluster_and_expands_every_member(tmp_path):
    context, state = _grouping_state(
        tmp_path,
        (("unknown", "unknown"), ("unknown",)),
    )
    try:
        before = state.approval_summary()["proposalDigest"]
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "assign",
                "role": "acceptance-record",
                "target": {
                    "scope": "individual",
                    "participantHandles": ["participant-0001"],
                },
                "applyToSimilar": False,
            }
        )

        local = state.local_review_snapshot()
        assert state.approval_summary()["proposalDigest"] != before
        assert local["review"]["coverage"] == {
            "groups": 3,
            "automaticallyOrganizedUnits": 1,
            "exceptionClusters": 1,
            "exceptionUnits": 1,
            "unaccountedUnits": 0,
        }
        assert state.approval_summary()["counts"] == {
            "sources": 3,
            "units": 4,
            "participants": 2,
            "accepted": 1,
            "reassigned": 2,
            "excluded": 0,
            "unresolved": 1,
        }
    finally:
        context.__exit__(None, None, None)


def test_apply_to_similar_touches_only_unresolved_matching_clusters(tmp_path):
    context, state = _grouping_state(
        tmp_path,
        (("unknown",), ("unknown",), ("identity-front",)),
    )
    try:
        state.resolve_exception(
            {
                "exceptionId": "exception-0002",
                "action": "exclude",
                "reason": "irrelevant",
                "applyToSimilar": False,
            }
        )
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "assign",
                "role": "acceptance-record",
                "target": {
                    "scope": "individual",
                    "participantHandles": ["participant-0001"],
                },
                "applyToSimilar": True,
            }
        )

        local = state.local_review_snapshot()
        assert [
            item["exceptionId"] for item in local["review"]["exceptions"]
        ] == ["exception-0003"]
        assert state.approval_summary()["counts"] == {
            "sources": 4,
            "units": 4,
            "participants": 2,
            "accepted": 1,
            "reassigned": 1,
            "excluded": 1,
            "unresolved": 1,
        }
    finally:
        context.__exit__(None, None, None)


def test_undo_exception_and_reopen_group_restore_the_exact_prior_digest(tmp_path):
    context, state = _grouping_state(tmp_path, (("unknown",),))
    try:
        before = state.approval_summary()["proposalDigest"]
        before_review = _review_bytes(state)
        request = {
            "exceptionId": "exception-0001",
            "action": "exclude",
            "reason": "irrelevant",
            "applyToSimilar": False,
        }

        state.resolve_exception(request)
        state.undo_exception({"exceptionId": "exception-0001"})
        assert state.approval_summary()["proposalDigest"] == before
        assert _review_bytes(state) == before_review

        state.resolve_exception(request)
        state.reopen_group({"groupId": "group-0002"})
        assert state.approval_summary()["proposalDigest"] == before
        assert _review_bytes(state) == before_review
    finally:
        context.__exit__(None, None, None)


@pytest.mark.parametrize(
    "mapping",
    (
        {
            "exceptionId": "exception-9999",
            "action": "exclude",
            "reason": "irrelevant",
            "applyToSimilar": False,
        },
        {
            "exceptionId": "exception-0001",
            "action": "split",
            "splitBeforeUnitId": "unit-0004",
            "applyToSimilar": False,
        },
        {
            "exceptionId": "exception-0001",
            "action": "merge-next",
            "applyToSimilar": False,
        },
        {
            "exceptionId": "exception-0001",
            "action": "exclude",
            "reason": "irrelevant",
            "applyToSimilar": False,
            "extra": False,
        },
    ),
    ids=("stale", "invalid-member", "cross-source-merge", "extra-key"),
)
def test_resolve_exception_invalid_requests_leave_digest_and_state_byte_identical(
    tmp_path,
    mapping,
):
    context, state = _grouping_state(
        tmp_path,
        (("unknown", "unknown"), ("unknown",)),
    )
    try:
        before_digest = state.approval_summary()["proposalDigest"]
        before_review = _review_bytes(state)

        with pytest.raises(ValueError):
            state.resolve_exception(mapping)

        assert state.approval_summary()["proposalDigest"] == before_digest
        assert _review_bytes(state) == before_review
    finally:
        context.__exit__(None, None, None)


def test_resolve_exception_split_changes_only_contiguous_group_review_and_digest(
    tmp_path,
):
    context, state = _grouping_state(
        tmp_path,
        (("unknown", "unknown", "unknown"),),
    )
    try:
        before = state.approval_summary()["proposalDigest"]
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "split",
                "splitBeforeUnitId": "unit-0003",
                "applyToSimilar": False,
            }
        )
        local = state.local_review_snapshot()

        assert state.approval_summary()["proposalDigest"] != before
        assert [
            group["memberUnitIds"] for group in local["review"]["groups"]
        ] == [["unit-0001"], ["unit-0002"], ["unit-0003", "unit-0004"]]
        assert local["review"]["coverage"] == {
            "groups": 3,
            "automaticallyOrganizedUnits": 1,
            "exceptionClusters": 2,
            "exceptionUnits": 3,
            "unaccountedUnits": 0,
        }
        assert {
            item["similarityKey"] for item in local["review"]["exceptions"]
        } == {"similarity-df5727804e07e13b"}
        assert state.approval_summary()["counts"]["unresolved"] == 3
    finally:
        context.__exit__(None, None, None)


def test_exact_coverage_holds_after_every_exception_cluster_is_resolved(tmp_path):
    context, state = _grouping_state(
        tmp_path,
        (("unknown",), ("unknown",)),
    )
    try:
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "assign",
                "role": "acceptance-record",
                "target": {
                    "scope": "individual",
                    "participantHandles": ["participant-0001"],
                },
                "applyToSimilar": True,
            }
        )
        summary = state.approval_summary()
        approved = state.approve(summary["proposalDigest"])

        assert summary["readyToPrepare"] is True
        assert [
            assignment["unitId"] for assignment in approved["unitAssignments"]
        ] == ["unit-0001", "unit-0002", "unit-0003"]
        assert len({
            assignment["unitId"] for assignment in approved["unitAssignments"]
        }) == 3
    finally:
        context.__exit__(None, None, None)


def test_resolve_exception_accepts_fixed_source_recommendation_and_disposition(
    tmp_path,
):
    context, state = _grouping_state(
        tmp_path,
        (("service-contract",),),
        source_only=(("unreadable", "pdf", ("document-unreadable",)),),
    )
    try:
        assert state.local_review_snapshot()["review"]["exceptions"] == [
            {
                "exceptionId": "exception-0001",
                "kind": "source",
                "issueCode": "source-unreadable",
                "recommendedAction": "exclude",
                "allowedActions": ["exclude"],
                "similarityKey": "similarity-8af016f0fcf7d9a6",
                "evidenceId": "evidence-0003",
            }
        ]
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "accept-recommendation",
                "applyToSimilar": False,
            }
        )
        summary = state.approval_summary()
        approved = state.approve(summary["proposalDigest"])

        assert approved["sourceDispositions"] == [
            {
                "evidenceId": "evidence-0003",
                "decision": "excluded",
                "reason": "unreadable-replacement-available",
            }
        ]
        assert summary["readyToPrepare"] is True
    finally:
        context.__exit__(None, None, None)


def test_split_then_merge_next_is_atomic_and_undo_restores_split_state(tmp_path):
    context, state = _grouping_state(
        tmp_path,
        (("unknown", "unknown", "unknown"),),
    )
    try:
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "split",
                "splitBeforeUnitId": "unit-0003",
                "applyToSimilar": False,
            }
        )
        split_digest = state.approval_summary()["proposalDigest"]
        split_review = _review_bytes(state)

        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "merge-next",
                "applyToSimilar": False,
            }
        )
        assert [
            group["memberUnitIds"]
            for group in state.local_review_snapshot()["review"]["groups"]
        ] == [["unit-0001"], ["unit-0002", "unit-0003", "unit-0004"]]

        state.undo_exception({"exceptionId": "exception-0001"})
        assert state.approval_summary()["proposalDigest"] == split_digest
        assert _review_bytes(state) == split_review
    finally:
        context.__exit__(None, None, None)


def test_choose_roster_exception_recomputes_groups_from_preloaded_candidates(
    tmp_path,
):
    source = _source_with_two_rosters(tmp_path)
    with open_inventory_observation(source) as observation:
        facts = GroupingEvidence()
        inspection = inspect_observation(
            observation,
            _private_text_sink=facts.capture,
        )
        state = ProposalState.from_inspection(
            observation,
            inspection,
            _grouping_evidence=facts,
        )
        roster_units = [
            unit["unitId"]
            for unit in state.units
            if unit["suggestedRole"] == "payment-roster"
        ]

        assert state.local_review_snapshot()["roster"]["status"] == "ambiguous"
        assert state.local_review_snapshot()["review"]["exceptions"][0][
            "kind"
        ] == "roster"
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "choose-roster",
                "rosterUnitId": roster_units[1],
                "applyToSimilar": False,
            }
        )

        local = state.local_review_snapshot()
        assert local["roster"]["status"] == "selected"
        assert local["roster"]["rosterUnitId"] == roster_units[1]
        assert local["review"]["coverage"]["unaccountedUnits"] == 0
        assert state.approval_summary()["counts"]["unresolved"] == 2
        state.resolve_exception(
            {
                "exceptionId": "exception-0001",
                "action": "assign",
                "role": "payment-roster",
                "target": {"scope": "case", "participantHandles": []},
                "applyToSimilar": True,
            }
        )
        assert state.approval_summary()["readyToPrepare"] is True
        assert all(
            private not in repr(local)
            for private in ("Alice", "CTV-001", "Carol", "CTV-101")
        )


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
        summary = state.approval_summary()
        assert summary["rosterUnitId"] == roster["unitId"]
        assert summary["participantHandles"] == [
            "participant-0001", "participant-0002"
        ]
        assert "Alice" not in repr(summary)
    finally:
        context.__exit__(None, None, None)


def test_roster_selection_uses_explicit_owned_snapshot_capability(
    tmp_path, monkeypatch
):
    source = _source(tmp_path)
    with open_inventory_observation(source) as observation:
        inspection = inspect_observation(observation)
        owned_snapshot = observation.snapshot
        calls = []

        def snapshot_source(evidence_id, *, max_bytes):
            calls.append(evidence_id)
            return owned_snapshot(evidence_id, max_bytes=max_bytes)

        state = ProposalState.from_inspection(
            observation, inspection, _snapshot_source=snapshot_source
        )
        monkeypatch.setattr(
            InventoryObservation,
            "snapshot",
            lambda *_args, **_kwargs: pytest.fail(
                "default observation acquisition bypassed injected capability"
            ),
        )
        roster = next(
            unit for unit in state.units if unit["suggestedRole"] == "payment-roster"
        )
        state.select_roster({"rosterUnitId": roster["unitId"]})

        assert state.approval_summary()["participantHandles"] == [
            "participant-0001", "participant-0002"
        ]
        assert calls == [roster["evidenceId"]]


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


def test_roster_blank_separator_is_ignored_while_duplicate_identity_still_blocks(
    tmp_path,
):
    source = _source(
        tmp_path,
        roster_rows=(
            ("Alice", "CTV-001"),
            (None, None, None),
            ("Bao", "CTV-001"),
        ),
    )
    with open_inventory_observation(source) as observation:
        state = ProposalState.from_inspection(observation, inspect_observation(observation))
        roster = next(unit for unit in state.units if unit["suggestedRole"] == "payment-roster")
        state.select_roster({"rosterUnitId": roster["unitId"]})
        summary = state.approval_summary()
        assert summary["readyToPrepare"] is False
        assert summary["participantHandles"] == [
            "participant-0001",
            "participant-0002",
        ]
        assert "roster-row-invalid" not in summary["issueCodes"]
        assert "roster-identity-duplicate" in summary["issueCodes"]


@pytest.mark.parametrize(
    "invalid_row",
    [
        ("Alice", "", 100),
        ("", "CTV-001", 100),
        ("", "", 100),
    ],
    ids=("missing-identity", "missing-name", "trailing-data"),
)
def test_roster_nonblank_incomplete_rows_remain_invalid(tmp_path, invalid_row):
    source = _source(
        tmp_path,
        roster_rows=(("Alice", "CTV-001"), invalid_row),
    )
    with open_inventory_observation(source) as observation:
        state = ProposalState.from_inspection(
            observation, inspect_observation(observation)
        )
        roster = next(
            unit
            for unit in state.units
            if unit["suggestedRole"] == "payment-roster"
        )
        state.select_roster({"rosterUnitId": roster["unitId"]})

        summary = state.approval_summary()
        assert summary["participantHandles"] == ["participant-0001"]
        assert "roster-row-invalid" in summary["issueCodes"]
        assert summary["readyToPrepare"] is False


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


def test_equal_strong_rosters_remain_explicitly_resolvable_from_preloaded_candidates(
    tmp_path,
):
    source = _source_with_two_rosters(tmp_path)
    with open_inventory_observation(source) as observation:
        calls = []
        owned_snapshot = observation.snapshot

        def snapshot_source(evidence_id, *, max_bytes):
            calls.append((evidence_id, max_bytes))
            return owned_snapshot(evidence_id, max_bytes=max_bytes)

        state = ProposalState.from_inspection(
            observation,
            inspect_observation(observation),
            _snapshot_source=snapshot_source,
        )
        rosters = [
            unit
            for unit in state.units
            if unit["suggestedRole"] == "payment-roster"
        ]

        assert state.approval_summary()["rosterUnitId"] is None
        assert state.approval_summary()["issueCodes"] == ["roster-ambiguous"]
        assert len(calls) == 1

        state.select_roster({"rosterUnitId": rosters[1]["unitId"]})

        assert state.approval_summary()["rosterUnitId"] == rosters[1]["unitId"]
        assert "roster-ambiguous" not in state.approval_summary()["issueCodes"]
        assert len(calls) == 1


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
