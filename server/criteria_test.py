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
