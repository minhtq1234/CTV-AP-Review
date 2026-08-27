import criteria as cr
from criteria import Kind, Status


class TestRegistryMatchesTheChecklist:
    def test_twenty_five_per_ctv_criteria(self):
        # 24 from Checklist_Binhnt10.xlsx "Requirement CTV Remove" + #28
        assert len(cr.CRITERIA) == 25

    def test_section_counts_match_the_prototype(self):
        # The prototype's own section-count text: 8 + 1 + 5 + 5 + 6 = 25
        assert cr.group_counts() == {"01": 8, "02": 1, "03": 5, "04": 5, "05": 6}

    def test_every_group_has_a_name(self):
        assert {c.group for c in cr.CRITERIA} <= set(cr.GROUPS)

    def test_stts_are_unique(self):
        stts = [c.stt for c in cr.CRITERIA]
        assert len(stts) == len(set(stts))

    def test_the_missing_stts_are_accounted_for(self):
        present = {c.stt for c in cr.CRITERIA}
        # 19 is folded into #14's card; 20/26/30/31/32 are roster-level
        assert 19 not in present
        assert not present & set(cr.ROSTER_LEVEL_STT)

    def test_the_five_kinds_partition_all_criteria(self):
        by_kind = {}
        for c in cr.CRITERIA:
            by_kind.setdefault(c.kind, []).append(c.stt)
        assert sorted(by_kind[Kind.COMPARE]) == [1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 13, 27]
        assert sorted(by_kind[Kind.COMPUTE]) == [12, 14, 15, 16, 17]
        assert sorted(by_kind[Kind.PRESENCE]) == [21, 22, 23, 24, 25, 28]
        assert by_kind[Kind.EXTERNAL] == [6]
        assert by_kind[Kind.CONDITIONAL] == [18]

    def test_every_criterion_carries_accs_own_instruction(self):
        # `how` is what a reviewer follows when the tool abstains, so an
        # abstention is never a dead end.
        for c in cr.CRITERIA:
            assert len(c.how) > 40, c.stt

    def test_every_criterion_names_at_least_one_document(self):
        for c in cr.CRITERIA:
            assert c.docs, c.stt

    def test_excel_is_the_reference_for_identity_and_money(self):
        for stt in (1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 14):
            assert cr.EXCEL in cr.BY_STT[stt].docs, stt

    def test_signature_criteria_never_reference_excel(self):
        # A signature lives on a scan; the roster has nothing to say about it.
        for stt in (21, 22, 23, 24, 25, 28):
            assert cr.EXCEL not in cr.BY_STT[stt].docs, stt

    def test_pit_carries_no_hardcoded_rate(self):
        # The checklist asserts only that zero PIT needs a stated basis.
        params = cr.BY_STT[15].params or {}
        assert "rate" not in params
        assert not any(
            isinstance(v, (int, float)) and v in (0.1, 10) for v in params.values()
        )

    def test_cards_are_the_computed_and_single_source_ones(self):
        cards = {c.stt for c in cr.CRITERIA if c.render == "card"}
        assert cards == {6, 12, 14, 15, 16, 17, 18}


class TestCellStatus:
    contract_signature = property(lambda self: cr.BY_STT[21])

    def test_a_document_out_of_scope_is_not_applicable(self):
        name = cr.BY_STT[1]  # Họ và tên: no MST lookup among its documents
        assert not cr.applies(name, cr.MST_LOOKUP)
        assert cr.cell_status(name, cr.MST_LOOKUP, None) is Status.NOT_APPLICABLE

    def test_nothing_evaluated_is_pending_not_ok(self):
        # The inversion this design exists for: the prototype returns `ok` here.
        assert cr.cell_status(cr.BY_STT[1], cr.EXCEL, None) is Status.PENDING

    def test_a_comparator_result_passes_through(self):
        for computed in (Status.OK, Status.NO, Status.REVIEW, Status.MISSING):
            assert cr.cell_status(cr.BY_STT[1], cr.EXCEL, computed) is computed

    def test_an_override_beats_the_computed_status(self):
        assert cr.cell_status(
            cr.BY_STT[1], cr.EXCEL, Status.OK, override=Status.NO
        ) is Status.NO

    def test_an_override_cannot_resurrect_an_out_of_scope_cell(self):
        assert cr.cell_status(
            cr.BY_STT[1], cr.MST_LOOKUP, None, override=Status.OK
        ) is Status.NOT_APPLICABLE

    def test_a_signature_criterion_opens_needing_a_human(self):
        # The tool navigates to the block; it does not judge the signature.
        for stt in (21, 22, 23, 24, 25, 28):
            criterion = cr.BY_STT[stt]
            document = criterion.docs[0]
            assert cr.cell_status(criterion, document, None) is Status.REVIEW, stt

    def test_a_human_can_settle_a_signature_either_way(self):
        signature = cr.BY_STT[21]
        assert cr.cell_status(
            signature, cr.CONTRACT, None, override=Status.OK
        ) is Status.OK
        assert cr.cell_status(
            signature, cr.CONTRACT, None, override=Status.NO
        ) is Status.NO


class TestRollUp:
    def test_worst_wins(self):
        assert cr.roll_up([Status.OK, Status.NO]) is Status.NO
        assert cr.roll_up([Status.OK, Status.REVIEW]) is Status.REVIEW
        assert cr.roll_up([Status.OK, Status.PENDING]) is Status.PENDING
        assert cr.roll_up([Status.OK, Status.OK]) is Status.OK

    def test_a_missing_document_outranks_a_question(self):
        # An absent document is a gate failure, not something to look into.
        assert cr.roll_up([Status.REVIEW, Status.MISSING]) is Status.MISSING
        assert cr.roll_up([Status.MISSING, Status.NO]) is Status.NO

    def test_not_applicable_cells_are_ignored(self):
        assert cr.roll_up(
            [Status.NOT_APPLICABLE, Status.OK, Status.NOT_APPLICABLE]
        ) is Status.OK

    def test_all_not_applicable_stays_not_applicable(self):
        assert cr.roll_up(
            [Status.NOT_APPLICABLE] * 3
        ) is Status.NOT_APPLICABLE

    def test_no_cells_at_all_is_not_applicable(self):
        assert cr.roll_up([]) is Status.NOT_APPLICABLE


class TestSummary:
    def test_counts_by_criterion(self):
        # Modelled on the prototype's own header: 23 ok, 1 rv, 1 na = 25
        statuses = {}
        for index, c in enumerate(cr.CRITERIA):
            if index == 0:
                statuses[c.stt] = Status.REVIEW
            elif index == 1:
                statuses[c.stt] = Status.NOT_APPLICABLE
            else:
                statuses[c.stt] = Status.OK
        counts = cr.summarise(statuses)
        assert counts["ok"] == 23
        assert counts["rv"] == 1
        assert counts["na"] == 1
        assert sum(counts.values()) == 25

    def test_every_status_is_reported_even_at_zero(self):
        # The header should be able to render a zero rather than omit a state.
        counts = cr.summarise({1: Status.OK})
        assert set(counts) == {s.value for s in Status}
        assert counts["no"] == 0


class TestAnUnevaluatedPacketIsHonest:
    def test_a_fresh_packet_is_pending_not_clean(self):
        """The whole point: nothing evaluated must not look like everything fine."""
        statuses = {}
        for c in cr.CRITERIA:
            cells = [cr.cell_status(c, d, None) for d in c.docs]
            statuses[c.stt] = cr.roll_up(cells)
        counts = cr.summarise(statuses)
        assert counts["ok"] == 0
        # the six signature criteria ask for a person; the rest are unevaluated
        assert counts["rv"] == 6
        assert counts["pending"] == 19
        assert sum(counts.values()) == 25


class TestTheOverrideRecord:
    """Spec §6. A reviewer may change any computed status, and the record keeps
    what the engine thought — `from_status` is the labelled corpus this project
    does not otherwise have, accumulated at no marginal cost.
    """

    def _override(self, **kw):
        base = dict(stt=1, document=cr.CONTRACT, from_status=Status.OK,
                    to_status=Status.NO, reason="tên trên hợp đồng là người khác",
                    at="2026-08-27T00:00:00+00:00", by="")
        return cr.Override(**{**base, **kw})

    def test_it_carries_what_the_engine_thought_and_what_the_human_decided(self):
        o = self._override()
        assert o.from_status is Status.OK
        assert o.to_status is Status.NO

    def test_it_is_frozen(self):
        import dataclasses
        import pytest as _pytest
        with _pytest.raises(dataclasses.FrozenInstanceError):
            self._override().stt = 2

    def test_an_author_is_empty_until_auth_exists(self):
        # Spec §6: `by: str  # reviewer identity when auth exists; "" until then`
        assert self._override().by == ""

    def test_no_reason_is_needed(self):
        """Acc's call: a decision is one click. Requiring a written reason on
        each of 322 `rv` cells would be a different product."""
        for blank in ("", "   ", "\n"):
            assert self._override(reason=blank).reason == blank

    def test_a_reason_is_kept_when_one_is_given(self):
        o = self._override(reason="đã xem chữ ký trang 1")
        assert o.reason == "đã xem chữ ký trang 1"
        assert o.as_dict()["reason"] == "đã xem chữ ký trang 1"

    def test_the_default_is_no_reason(self):
        o = cr.Override(stt=1, document=cr.CONTRACT, from_status=Status.OK,
                        to_status=Status.NO, at="t")
        assert o.reason == "" and o.by == ""

    def test_the_document_must_be_one_the_criterion_spans(self):
        import pytest as _pytest
        # #01 spans Excel/CCCD/Hợp đồng/BBNT/Bảng Kê Thu Mua, never the cam kết
        with _pytest.raises(ValueError, match="document"):
            self._override(stt=1, document=cr.COMMITMENT)

    def test_an_unknown_criterion_is_refused(self):
        import pytest as _pytest
        with _pytest.raises(ValueError, match="stt"):
            self._override(stt=99)

    def test_a_roster_level_criterion_is_refused_here(self):
        """#20/#26/#30/#31/#32 hang off no packet and have no document axis, so
        they cannot be keyed this way. Overriding them is separate work."""
        import pytest as _pytest
        for stt in cr.ROSTER_LEVEL_STT:
            with _pytest.raises(ValueError, match="stt"):
                self._override(stt=stt, document=cr.EXCEL)

    def test_a_same_status_record_is_a_confirmation(self):
        """Not a no-op: a person putting a timestamp to the engine's finding is
        what lets `cần gửi lại` count conclusions rather than candidates."""
        o = self._override(from_status=Status.NO, to_status=Status.NO)
        assert o.confirms is True
        assert o.to_status is Status.NO

    def test_a_change_is_not_a_confirmation(self):
        assert self._override(from_status=Status.OK,
                              to_status=Status.NO).confirms is False

    def test_na_cannot_be_overridden_to_or_from(self):
        """`na` means the document is outside the criterion — a fact about the
        checklist, not a judgment, so there is nothing for a person to decide."""
        import pytest as _pytest
        with _pytest.raises(ValueError, match="na"):
            self._override(to_status=Status.NOT_APPLICABLE)
        with _pytest.raises(ValueError, match="na"):
            self._override(from_status=Status.NOT_APPLICABLE)

    def test_every_transition_between_decidable_statuses_is_allowed(self):
        decidable = [s for s in Status if s is not Status.NOT_APPLICABLE]
        for a in decidable:
            for b in decidable:
                self._override(from_status=a, to_status=b)   # must not raise


class TestTheOverrideKey:
    """A record needs to identify one cell of one packet. `stt` + `document`
    alone cannot: July has 41 packets."""

    def test_a_cell_is_addressed_by_criterion_and_document(self):
        assert cr.override_key(1, cr.CONTRACT) == "01:Hợp đồng"

    def test_the_key_is_stable_across_the_two_digit_form(self):
        assert cr.override_key(7, cr.EXCEL) == "07:Excel"
        assert cr.override_key(27, cr.BBNT) == "27:BBNT"

    def test_a_record_knows_its_own_key(self):
        o = cr.Override(stt=7, document=cr.EXCEL, from_status=Status.OK,
                        to_status=Status.NO, reason="x", at="t", by="")
        assert o.key == cr.override_key(7, cr.EXCEL)

    def test_it_round_trips_through_a_dict(self):
        o = cr.Override(stt=7, document=cr.EXCEL, from_status=Status.NO,
                        to_status=Status.OK, reason="đã đối chiếu bản scan",
                        at="2026-08-27T01:00:00+00:00", by="")
        assert cr.Override.from_dict(o.as_dict()) == o

    def test_the_dict_is_json_serialisable(self):
        import json
        o = cr.Override(stt=7, document=cr.EXCEL, from_status=Status.NO,
                        to_status=Status.OK, reason="x", at="t", by="")
        assert json.loads(json.dumps(o.as_dict())) == o.as_dict()

    def test_the_statuses_serialise_as_their_wire_values(self):
        o = cr.Override(stt=7, document=cr.EXCEL, from_status=Status.NO,
                        to_status=Status.OK, reason="x", at="t", by="")
        assert o.as_dict()["fromStatus"] == "no"
        assert o.as_dict()["toStatus"] == "ok"
