import criteria as cr
import evaluate as ev
from criteria import Status


# --- fixtures ----------------------------------------------------------------

def source(doc_id, value, page=0, conf=0.95, bbox=True):
    return {"docId": doc_id, "page": page, "value": value,
            "confidence": conf,
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 30} if bbox
            else None}


def doc(doc_id, kind, label="", anchors=None):
    return {"id": doc_id, "kind": kind, "label": label or kind,
            "pages": [{"src": "pg0.png", "width": 100, "height": 100}],
            "anchors": anchors or {}}


def manifest(docs=(), fields=()):
    return {"id": "p", "name": "CTV", "product": "", "docs": list(docs),
            "fields": [{"key": k, "expected": e, "sources": list(s)}
                       for k, e, s in fields]}


ROSTER = {
    "name": "Đinh Hữu Phúc",
    "cccd": "079203031329",
    "mst": "079203031329",
    "dob": "23/04/2003",
    "account": "0081001142415",
    "gross": "7777778",
    "pit": "777778",
    "net": "7000000",
}


def full_packet():
    """A packet with a contract and a BBNT that both read correctly."""
    return manifest(
        docs=[doc("contract-0", "contract"), doc("bbnt-0", "bbnt")],
        fields=[
            ("hoten", "Đinh Hữu Phúc", [
                source("contract-0", "Đinh Hữu Phúc"),
                source("bbnt-0", "Đinh Hữu Phúc"),
            ]),
            ("cccd", "079203031329", [
                source("contract-0", "079203031329"),
                source("bbnt-0", "079203031329"),
            ]),
        ],
    )


def by_stt(results):
    return {r.stt: r for r in results}


def cells_by_doc(result):
    return {c.document: c for c in result.cells}


# --- tests -------------------------------------------------------------------

class TestShape:
    def test_every_criterion_gets_a_result(self):
        results = ev.evaluate_packet(full_packet(), ROSTER)
        assert [r.stt for r in results] == [c.stt for c in cr.CRITERIA]

    def test_every_criterion_gets_one_cell_per_document(self):
        for result in ev.evaluate_packet(full_packet(), ROSTER):
            criterion = cr.BY_STT[result.stt]
            assert [c.document for c in result.cells] == list(criterion.docs)

    def test_the_criterion_status_is_the_rollup_of_its_cells(self):
        for result in ev.evaluate_packet(full_packet(), ROSTER):
            assert result.status is cr.roll_up([c.status for c in result.cells])

    def test_every_cell_explains_its_status(self):
        for result in ev.evaluate_packet(full_packet(), ROSTER):
            for cell in result.cells:
                assert cell.note, (result.stt, cell.document)


class TestTheExcelColumnIsTheReference:
    def test_it_shows_the_roster_value_verbatim(self):
        result = by_stt(ev.evaluate_packet(full_packet(), ROSTER))[1]
        assert cells_by_doc(result)[cr.EXCEL].value == "Đinh Hữu Phúc"

    def test_a_well_formed_reference_passes_its_format_rule(self):
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))
        assert cells_by_doc(results[2])[cr.EXCEL].status is Status.OK
        assert cells_by_doc(results[3])[cr.EXCEL].status is Status.OK

    def test_a_malformed_reference_is_the_finding(self):
        roster = {**ROSTER, "cccd": "07920303132"}   # 11 digits
        results = by_stt(ev.evaluate_packet(full_packet(), roster))
        cell = cells_by_doc(results[2])[cr.EXCEL]

        assert cell.status is Status.NO
        assert "12" in cell.note

    def test_a_date_not_in_the_format_acc_asks_for(self):
        roster = {**ROSTER, "dob": "2003-04-23"}
        results = by_stt(ev.evaluate_packet(full_packet(), roster))
        cell = cells_by_doc(results[3])[cr.EXCEL]

        assert cell.status is Status.NO
        assert "dd/mm/yyyy" in cell.note

    def test_an_empty_reference_is_pending_not_wrong(self):
        roster = {**ROSTER, "cccd": ""}
        results = by_stt(ev.evaluate_packet(full_packet(), roster))
        assert cells_by_doc(results[2])[cr.EXCEL].status is Status.PENDING

    def test_no_roster_row_at_all(self):
        results = by_stt(ev.evaluate_packet(full_packet(), None))
        cell = cells_by_doc(results[1])[cr.EXCEL]

        assert cell.status is Status.PENDING
        assert "chưa khớp" in cell.note

    def test_the_reference_provenance_is_the_roster(self):
        result = by_stt(ev.evaluate_packet(full_packet(), ROSTER))[1]
        cell = cells_by_doc(result)[cr.EXCEL]
        assert cell.evidence[0].provenance == "roster"


class TestComparingDocumentsAgainstTheReference:
    def test_an_agreeing_document_passes(self):
        result = by_stt(ev.evaluate_packet(full_packet(), ROSTER))[2]
        assert cells_by_doc(result)[cr.CONTRACT].status is Status.OK

    def test_a_disagreeing_document_is_the_finding_and_shows_both_values(self):
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("cccd", "079203031329",
                     [source("contract-0", "079189016370")])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        cell = cells_by_doc(result)[cr.CONTRACT]

        assert cell.status is Status.NO
        # Acc's rule: state the wrong value, not just "không khớp"
        assert "079189016370" in cell.value
        assert "079203031329" in cell.note

    def test_a_tone_mark_only_name_difference_needs_a_human(self):
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("hoten", "Đinh Hữu Phúc",
                     [source("contract-0", "Dinh Huu Phuc")])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[1]
        cell = cells_by_doc(result)[cr.CONTRACT]

        assert cell.status is Status.REVIEW
        assert "dấu" in cell.note

    def test_a_low_confidence_agreement_is_a_clean_match_not_a_review(self):
        """Confidence measures legibility, not correctness (docs/handoff-ver3.md):
        an exact match against the roster is no longer downgraded just because
        the read was unsure."""
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("cccd", "079203031329",
                     [source("contract-0", "079203031329", conf=0.4)])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        cell = cells_by_doc(result)[cr.CONTRACT]

        assert cell.status is Status.OK
        assert "0.4" not in cell.note and "40" not in cell.note

    def test_the_evidence_carries_the_page_and_box(self):
        result = by_stt(ev.evaluate_packet(full_packet(), ROSTER))[2]
        evidence = cells_by_doc(result)[cr.CONTRACT].evidence[0]

        assert evidence.document_id == "contract-0"
        assert evidence.page == 0
        assert evidence.bbox is not None
        assert evidence.provenance == "ocr"

    def test_a_value_read_with_no_box_is_labelled_not_smoothed_over(self):
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("cccd", "079203031329",
                     [source("contract-0", "079203031329", bbox=None)])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        cell = cells_by_doc(result)[cr.CONTRACT]

        assert cell.evidence[0].bbox is None
        assert "Chưa định vị" in cell.note


class TestMissingAndUnread:
    def test_a_document_absent_from_the_packet_is_missing(self):
        packet = manifest(docs=[doc("contract-0", "contract")], fields=[
            ("cccd", "079203031329", [source("contract-0", "079203031329")]),
        ])
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]

        assert cells_by_doc(result)[cr.BBNT].status is Status.MISSING

    def test_a_present_document_with_nothing_extracted_is_pending(self):
        packet = manifest(docs=[doc("contract-0", "contract"),
                                doc("bbnt-0", "bbnt")],
                          fields=[("cccd", "079203031329",
                                   [source("contract-0", "079203031329")])])
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        cell = cells_by_doc(result)[cr.BBNT]

        assert cell.status is Status.PENDING
        assert "chưa trích xuất" in cell.note

    def test_a_document_that_read_nothing_is_pending_not_a_mismatch(self):
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("cccd", "079203031329",
                     [source("contract-0", "", conf=0.0)])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        assert cells_by_doc(result)[cr.CONTRACT].status is Status.PENDING

    def test_an_optional_document_absent_is_not_applicable(self):
        # #25 Phụ lục/KPI carries optional=True: "nếu có".
        packet = manifest(docs=[doc("contract-0", "contract")])
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[25]

        assert result.status is Status.NOT_APPLICABLE

    def test_the_batch_level_listing_is_not_expected_inside_a_packet(self):
        """One Bảng Kê Thu Mua covers all 41 CTVs and sits outside every
        packet, so a packet not containing it is not a missing document."""
        result = by_stt(ev.evaluate_packet(full_packet(), ROSTER))[1]
        cell = cells_by_doc(result)[cr.PURCHASE]

        assert cell.status is Status.PENDING
        assert "toàn bảng kê" in cell.note


class TestSeveralCopiesOfOneDocument:
    def test_agreeing_copies_still_pass(self):
        packet = manifest(
            docs=[doc("contract-0", "contract"), doc("contract-1", "contract")],
            fields=[("cccd", "079203031329", [
                source("contract-0", "079203031329"),
                source("contract-1", "079203031329"),
            ])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        assert cells_by_doc(result)[cr.CONTRACT].status is Status.OK

    def test_one_copy_naming_someone_else_is_the_finding(self):
        """Real July packet 0: two contracts, one belonging to another CTV. A
        mis-split packet must not look clean because one copy happens to
        agree."""
        packet = manifest(
            docs=[doc("contract-0", "contract"), doc("contract-1", "contract")],
            fields=[("hoten", "Đinh Hữu Phúc", [
                source("contract-0", "Huỳnh Thị Thúy Phượng"),
                source("contract-1", "Đinh Hữu Phúc"),
            ])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[1]
        cell = cells_by_doc(result)[cr.CONTRACT]

        assert cell.status is Status.NO
        assert "2 bản" in cell.note

    def test_an_unreadable_copy_does_not_veto_a_readable_one(self):
        """An illegible copy is not evidence of disagreement — excluding it is
        what a reviewer would do. Only when every copy is unreadable does the
        cell go pending."""
        packet = manifest(
            docs=[doc("contract-0", "contract"), doc("contract-1", "contract")],
            fields=[("cccd", "079203031329", [
                source("contract-0", "", conf=0.0),
                source("contract-1", "079203031329"),
            ])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        cell = cells_by_doc(result)[cr.CONTRACT]

        assert cell.status is Status.OK
        assert "1/2 bản" in cell.note

    def test_every_copy_unreadable_is_pending(self):
        packet = manifest(
            docs=[doc("contract-0", "contract"), doc("contract-1", "contract")],
            fields=[("cccd", "079203031329", [
                source("contract-0", "", conf=0.0),
                source("contract-1", "", conf=0.0),
            ])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        assert cells_by_doc(result)[cr.CONTRACT].status is Status.PENDING


class TestSignaturesNeverResolveThemselves:
    def test_all_six_open_needing_a_human(self):
        packet = manifest(docs=[doc("contract-0", "contract"),
                                doc("bbnt-0", "bbnt"),
                                doc("appendix-0", "appendix")])
        results = by_stt(ev.evaluate_packet(packet, ROSTER))

        for stt in (21, 22, 23, 24, 25):
            assert results[stt].status is Status.REVIEW, stt

    def test_the_note_says_where_to_look(self):
        packet = manifest(docs=[doc("contract-0", "contract")])
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        assert "chữ ký" in results[21].cells[0].note

    def test_a_signature_on_an_absent_document_is_missing_not_review(self):
        packet = manifest(docs=[doc("contract-0", "contract")])
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        assert results[23].status is Status.MISSING     # BBNT signature, no BBNT

    def test_the_listing_signature_says_it_is_batch_level(self):
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))
        assert results[28].status is Status.REVIEW
        assert "toàn bảng kê" in results[28].cells[0].note


class TestConditional:
    def test_no_commitment_document_is_not_applicable_and_says_so(self):
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))

        assert results[18].status is Status.NOT_APPLICABLE
        assert "Không có" in results[18].note

    def test_a_commitment_present_needs_a_person_to_check_it(self):
        packet = manifest(docs=[doc("commitment-0", "commitment")])
        results = by_stt(ev.evaluate_packet(packet, ROSTER))

        assert results[18].status is Status.REVIEW


class TestCompute:
    def test_the_formula_is_recomputed_not_read(self):
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))
        assert results[17].status is Status.OK
        assert "7,777,778" in results[17].note

    def test_a_broken_formula_states_the_gap(self):
        roster = {**ROSTER, "net": "7000001"}
        results = by_stt(ev.evaluate_packet(full_packet(), roster))

        assert results[17].status is Status.NO
        # signed, matching `roster_checks`: negative means Net is too high
        assert "lệch -1" in results[17].note

    def test_net_must_be_positive(self):
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))
        assert results[16].status is Status.OK

        negative = {**ROSTER, "net": "-1"}
        assert by_stt(ev.evaluate_packet(full_packet(), negative))[16].status \
            is Status.NO

    def test_zero_pit_with_no_commitment_is_the_finding(self):
        roster = {**ROSTER, "pit": "0", "net": "7777778"}
        results = by_stt(ev.evaluate_packet(full_packet(), roster))

        assert results[15].status is Status.NO
        assert "cam kết" in results[15].note

    def test_zero_pit_with_a_commitment_present_is_satisfied(self):
        packet = manifest(docs=[doc("commitment-0", "commitment")])
        roster = {**ROSTER, "pit": "0", "net": "7777778"}
        results = by_stt(ev.evaluate_packet(packet, roster))

        assert results[15].status is Status.OK

    def test_a_nonzero_pit_is_not_verified_because_the_rate_is_not_ours(self):
        # §7: the applicable rate lives in Acc's file, not in this code.
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))

        assert results[15].status is Status.PENDING
        assert "thuế suất" in results[15].note

    def test_gross_agreement_compares_documents_against_the_excel(self):
        packet = manifest(
            docs=[doc("contract-0", "contract"), doc("bbnt-0", "bbnt")],
            fields=[("phi", "7777778", [
                source("contract-0", "7.777.778"),
                source("bbnt-0", "7.777.778"),
            ])],
        )
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        assert cells_by_doc(results[14])[cr.CONTRACT].status is Status.OK

    def test_a_service_term_needs_dates_nobody_extracts_yet(self):
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))
        assert results[12].status is Status.PENDING
        assert "ngày" in results[12].note


class TestExternal:
    def test_the_lookup_artefact_present_needs_a_person_to_read_it(self):
        packet = manifest(docs=[doc("pit-0", "pit")])
        results = by_stt(ev.evaluate_packet(packet, ROSTER))

        assert results[6].status is Status.REVIEW
        assert "tra cứu" in results[6].cells[0].note

    def test_no_lookup_artefact_is_a_missing_document(self):
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER))
        assert results[6].status is Status.MISSING


class TestNothingResolvesByDefault:
    def test_no_criterion_needing_a_scan_passes_on_an_empty_packet(self):
        """The inversion this whole design exists to prevent. #16 and #17 do
        pass: they read the roster alone and their arithmetic really is
        verified. Nothing that needs a document in the packet may."""
        results = ev.evaluate_packet(manifest(), ROSTER)

        passed = [r.stt for r in results if r.status is Status.OK]
        assert passed == [16, 17]
        for result in results:
            if cr.BY_STT[result.stt].docs != (cr.EXCEL,):
                assert result.status is not Status.OK, result.stt

    def test_an_empty_packet_is_mostly_missing_documents(self):
        counts = ev.summarise(ev.evaluate_packet(manifest(), ROSTER))
        assert counts["missing"] > 10
        assert sum(counts.values()) == len(cr.CRITERIA)
        assert counts["ok"] == 2      # only the Excel-only computes

    def test_a_full_packet_still_never_reports_all_clear(self):
        counts = ev.summarise(ev.evaluate_packet(full_packet(), ROSTER))
        assert counts["rv"] >= 5     # the signature criteria, at least


class TestTheNoteHelpsTriage:
    """Acc's rule: "Không chỉ báo 'Không khớp'; phải nêu trường sai, giá trị tại
    từng chứng từ, chênh lệch và nội dung cần kiểm tra lại."."""

    #: Real July packet 0's roster row: account 104883868364.
    ROW = {**ROSTER, "account": "104883868364"}

    def test_a_one_digit_difference_says_so(self):
        # Real July packet 0: the contract's account reads 13 digits where the
        # roster has 12 — an inserted digit, not a different account.
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("tk", "104883868364",
                     [source("contract-0", "1048836868364")])],
        )
        result = by_stt(ev.evaluate_packet(packet, self.ROW))[7]
        cell = cells_by_doc(result)[cr.CONTRACT]

        # still a finding — the tool does not decide it was an OCR slip
        assert cell.status is Status.NO
        assert "Chênh 1 chữ số" in cell.note
        assert "đọc sai" in cell.note

    def test_a_wholly_different_number_gets_no_such_hint(self):
        # Real July packet 0: the BBNT carries another CTV's account entirely.
        packet = manifest(
            docs=[doc("bbnt-0", "bbnt")],
            fields=[("tk", "104883868364",
                     [source("bbnt-0", "0081001142415")])],
        )
        result = by_stt(ev.evaluate_packet(packet, self.ROW))[7]
        cell = cells_by_doc(result)[cr.BBNT]

        assert cell.status is Status.NO
        assert "chênh" not in cell.note.casefold()
        assert "0081001142415" in cell.value

    def test_a_name_mismatch_gets_no_digit_hint(self):
        packet = manifest(
            docs=[doc("bbnt-0", "bbnt")],
            fields=[("hoten", "Đinh Hữu Phúc",
                     [source("bbnt-0", "Huỳnh Thị Thúy Phượng")])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[1]
        assert "chữ số" not in cells_by_doc(result)[cr.BBNT].note


class TestDocumentOrder:
    def test_the_reference_column_comes_first(self):
        # The reviewer reads the Excel value, then checks the scans against it.
        assert ev.DOCUMENT_ORDER[0] == cr.EXCEL

    def test_every_document_any_criterion_names_has_a_column(self):
        named = {d for c in cr.CRITERIA for d in c.docs}
        assert named <= set(ev.DOCUMENT_ORDER)

    def test_the_order_has_no_documents_nobody_uses(self):
        named = {d for c in cr.CRITERIA for d in c.docs}
        assert set(ev.DOCUMENT_ORDER) == named


class TestPayload:
    def test_it_serialises_to_json(self):
        import json

        payload = ev.as_payload(full_packet(), ROSTER)
        assert json.loads(json.dumps(payload)) == payload

    def test_it_carries_the_matrix_columns_and_every_criterion(self):
        payload = ev.as_payload(full_packet(), ROSTER)

        assert payload["documents"] == list(ev.DOCUMENT_ORDER)
        assert len(payload["criteria"]) == len(cr.CRITERIA)

    def test_each_criterion_carries_accs_instruction_and_its_group(self):
        for item in ev.as_payload(full_packet(), ROSTER)["criteria"]:
            assert len(item["how"]) > 40, item["stt"]
            assert item["groupLabel"]
            assert item["render"] in ("matrix", "card")

    def test_the_counts_are_by_criterion(self):
        payload = ev.as_payload(full_packet(), ROSTER)
        assert sum(payload["counts"].values()) == len(cr.CRITERIA)

    def test_group_counts_add_up_to_the_group_sizes(self):
        payload = ev.as_payload(full_packet(), ROSTER)
        for code, group in payload["groups"].items():
            assert sum(group["counts"].values()) == cr.group_counts()[code]
            assert group["label"] == cr.GROUPS[code]

    def test_evidence_reaches_the_payload_in_json_shape(self):
        payload = ev.as_payload(full_packet(), ROSTER)
        cccd = next(c for c in payload["criteria"] if c["stt"] == 2)
        cell = next(c for c in cccd["cells"] if c["document"] == cr.CONTRACT)

        assert cell["evidence"][0]["documentId"] == "contract-0"
        assert cell["evidence"][0]["provenance"] == "ocr"
        assert cell["evidence"][0]["bbox"]["width"] == 100

    def test_a_cell_for_a_document_outside_the_criterion_is_absent(self):
        """A criterion that does not span a document has no cell there — the
        matrix renders a static dash, not a clickable `na`."""
        payload = ev.as_payload(full_packet(), ROSTER)
        net = next(c for c in payload["criteria"] if c["stt"] == 16)

        assert [c["document"] for c in net["cells"]] == [cr.EXCEL]


class TestTheNoteMustBeTrue:
    def test_a_tone_mark_difference_is_described_as_one(self):
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("hoten", "Đinh Hữu Phúc",
                     [source("contract-0", "Dinh Huu Phuc")])],
        )
        note = cells_by_doc(
            by_stt(ev.evaluate_packet(packet, ROSTER))[1])[cr.CONTRACT].note

        assert "khác dấu" in note

    def test_a_near_miss_is_not_described_as_a_tone_mark_difference(self):
        """`Trần Văn Bải` is not `Trần Văn Bảy` with the accents dropped — it is
        a different string. Saying otherwise tells the reviewer something
        false."""
        roster = {**ROSTER, "name": "Trần Văn Bảy"}
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("hoten", "Trần Văn Bảy",
                     [source("contract-0", "Trần Văn Bải")])],
        )
        note = cells_by_doc(
            by_stt(ev.evaluate_packet(packet, roster))[1])[cr.CONTRACT].note

        assert "khác dấu" not in note
        assert "gần khớp" in note.casefold()

    def test_copies_that_disagree_with_each_other_are_reported(self):
        """Two contracts in one packet reading two different names is a finding
        about the packet, whatever the verdict against the bảng kê is."""
        roster = {**ROSTER, "name": "Trần Văn Bảy"}
        packet = manifest(
            docs=[doc("contract-0", "contract"), doc("contract-1", "contract")],
            fields=[("hoten", "Trần Văn Bảy", [
                source("contract-0", "Trần Văn Bải"),
                source("contract-1", "Trần Văn Bảy"),
            ])],
        )
        note = cells_by_doc(
            by_stt(ev.evaluate_packet(packet, roster))[1])[cr.CONTRACT].note

        assert "2 bản ghi khác nhau" in note
        assert "Trần Văn Bải" in note

    def test_agreeing_copies_are_not_reported_as_differing(self):
        note = cells_by_doc(
            by_stt(ev.evaluate_packet(full_packet(), ROSTER))[1])[cr.CONTRACT].note
        assert "khác nhau" not in note


class TestOverridesLayerOverTheComputedStatus:
    """Spec §6: overrides always win, and the computed value is retained.

    Applied as one pass over the assembled cells rather than threaded through
    each of the 23 Cell construction sites — the precedence I need is only
    "an override wins unless the cell is `na`", and `criteria.cell_status`
    already states it. One chokepoint cannot silently move a status the way
    twenty-three edits could.
    """

    def _override(self, stt, document, frm, to, reason="đã đối chiếu bản scan"):
        return cr.Override(stt=stt, document=document, from_status=frm,
                           to_status=to, reason=reason,
                           at="2026-08-27T00:00:00+00:00", by="")

    def test_no_overrides_changes_nothing(self):
        plain = ev.evaluate_packet(full_packet(), ROSTER)
        same = ev.evaluate_packet(full_packet(), ROSTER, overrides={})

        assert [(r.stt, r.status) for r in plain] == [(r.stt, r.status) for r in same]

    def test_an_override_wins_over_the_computed_status(self):
        o = self._override(21, cr.CONTRACT, Status.REVIEW, Status.OK)
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o}))
        cell = cells_by_doc(results[21])[cr.CONTRACT]

        assert cell.status is Status.OK

    def test_the_computed_status_is_retained(self):
        """The most valuable data this product generates: what the engine
        thought, beside what the human decided."""
        o = self._override(21, cr.CONTRACT, Status.REVIEW, Status.OK)
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o}))
        cell = cells_by_doc(results[21])[cr.CONTRACT]

        assert cell.computed_status is Status.REVIEW
        assert cell.status is Status.OK

    def test_the_criterion_rolls_up_from_the_overridden_cells(self):
        # #21's only document is the contract, so overriding it settles the row.
        o = self._override(21, cr.CONTRACT, Status.REVIEW, Status.OK)
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o}))

        assert results[21].status is Status.OK

    def test_the_note_carries_the_reviewer_s_reason(self):
        o = self._override(21, cr.CONTRACT, Status.REVIEW, Status.OK,
                           reason="đã xem chữ ký, đúng CTV")
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o}))
        cell = cells_by_doc(results[21])[cr.CONTRACT]

        assert "đã xem chữ ký, đúng CTV" in cell.note

    def test_the_override_appears_as_evidence_with_its_own_provenance(self):
        """Spec §5 lists "override" as a provenance value; nothing produced it
        until now. A reviewer's decision is a claim like any other."""
        o = self._override(21, cr.CONTRACT, Status.REVIEW, Status.OK)
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o}))
        cell = cells_by_doc(results[21])[cr.CONTRACT]

        provenances = [e.provenance for e in cell.evidence]
        assert "override" in provenances

    def test_a_cell_outside_the_criterion_cannot_be_overridden(self):
        """`na` is a fact about the checklist, not a judgment. `cell_status`
        already refuses this, and routing through it keeps one source of truth."""
        # #16 Net spans only Excel; force a stray override at another document
        stray = {cr.override_key(16, cr.BBNT): self._override(
            14, cr.BBNT, Status.OK, Status.NO)}
        results = by_stt(ev.evaluate_packet(full_packet(), ROSTER,
                                            overrides=stray))

        assert [c.document for c in results[16].cells] == [cr.EXCEL]
        assert results[16].status is Status.OK      # untouched

    def test_an_override_for_another_document_leaves_this_cell_alone(self):
        o = self._override(1, cr.BBNT, Status.OK, Status.NO)
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o}))
        cells = cells_by_doc(results[1])

        assert cells[cr.BBNT].status is Status.NO
        assert cells[cr.CONTRACT].status is Status.OK

    def test_a_plain_dict_override_is_accepted(self):
        """What comes back off disk is JSON, not a dataclass."""
        o = self._override(21, cr.CONTRACT, Status.REVIEW, Status.OK)
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o.as_dict()}))

        assert cells_by_doc(results[21])[cr.CONTRACT].status is Status.OK

    def test_a_downgrade_is_recorded_the_same_way(self):
        o = self._override(2, cr.CONTRACT, Status.OK, Status.NO,
                           reason="số trên scan khác, đã kiểm tra")
        results = by_stt(ev.evaluate_packet(
            full_packet(), ROSTER, overrides={o.key: o}))
        cell = cells_by_doc(results[2])[cr.CONTRACT]

        assert cell.status is Status.NO
        assert cell.computed_status is Status.OK
        assert results[2].status is Status.NO


class TestTheOverrideReachesThePayload:
    def test_the_cell_carries_both_statuses(self):
        o = cr.Override(stt=21, document=cr.CONTRACT,
                        from_status=Status.REVIEW, to_status=Status.OK,
                        reason="đã xem", at="t", by="")
        payload = ev.as_payload(full_packet(), ROSTER, overrides={o.key: o})
        row = next(c for c in payload["criteria"] if c["stt"] == 21)
        cell = next(c for c in row["cells"] if c["document"] == cr.CONTRACT)

        assert cell["status"] == "ok"
        assert cell["computedStatus"] == "rv"

    def test_it_serialises_to_json(self):
        import json
        o = cr.Override(stt=21, document=cr.CONTRACT,
                        from_status=Status.REVIEW, to_status=Status.OK,
                        reason="đã xem", at="t", by="")
        payload = ev.as_payload(full_packet(), ROSTER, overrides={o.key: o})
        assert json.loads(json.dumps(payload)) == payload

    def test_a_cell_with_no_override_reports_no_difference(self):
        payload = ev.as_payload(full_packet(), ROSTER)
        row = next(c for c in payload["criteria"] if c["stt"] == 1)
        cell = next(c for c in row["cells"] if c["document"] == cr.CONTRACT)

        assert cell["computedStatus"] == cell["status"]

    def test_the_payload_counts_the_overridden_statuses(self):
        o = cr.Override(stt=21, document=cr.CONTRACT,
                        from_status=Status.REVIEW, to_status=Status.OK,
                        reason="đã xem", at="t", by="")
        before = ev.as_payload(full_packet(), ROSTER)["counts"]
        after = ev.as_payload(full_packet(), ROSTER,
                              overrides={o.key: o})["counts"]

        assert after["ok"] == before["ok"] + 1
        assert after["rv"] == before["rv"] - 1


def test_a_signature_criterion_points_at_the_block_it_asks_about():
    """These five criteria are locate-and-look: a person decides, but the tool
    has to point first. Evidence used to be built with page 0 and no box, which
    pointed at the top of the first page -- that is, nowhere."""
    box = {"x": 616, "y": 973, "width": 268, "height": 225}
    packet = manifest([doc("contract-0", "contract",
                           anchors={"ctv": {"page": 3, "bbox": box}})])

    cells = by_stt(ev.evaluate_packet(packet, {}))[21].cells

    assert cells[0].evidence[0].page == 3
    assert cells[0].evidence[0].bbox == box
    # Still a person's call: locating never resolves the verdict.
    assert cells[0].status is Status.REVIEW


def test_the_other_party_gets_the_signing_page_even_with_no_box_of_its_own():
    """Both parties sign the same sheet, so the page is right even when only one
    side reads -- and on real contracts `Đại diện VNG` is routinely mangled by
    OCR, so this is the common case for #22 and #24, not an edge one."""
    packet = manifest([doc("contract-0", "contract", anchors={
        "ctv": {"page": 3, "bbox": {"x": 616, "y": 973, "width": 268, "height": 225}},
    })])

    cells = by_stt(ev.evaluate_packet(packet, {}))[22].cells

    assert cells[0].evidence[0].page == 3, "the signing page is known"
    assert cells[0].evidence[0].bbox is None, "but no box is invented for it"
    assert cells[0].status is Status.REVIEW


def test_a_document_with_no_block_found_points_at_no_particular_place():
    """One real appendix carries no signature phrase at all. The honest answer
    is the right document and nothing more -- not a box that means nothing."""
    packet = manifest([doc("contract-0", "contract", anchors={})])

    cells = by_stt(ev.evaluate_packet(packet, {}))[21].cells

    assert cells[0].evidence[0].page == 0
    assert cells[0].evidence[0].bbox is None
    assert cells[0].status is Status.REVIEW


def test_an_absent_appendix_is_not_applicable_but_an_absent_contract_is_missing():
    """Only 22 of 169 real packets carry a Phụ lục, so requiring one rolled
    #9/#10/#11/#13/#14 up to `missing` on 147 of them before any check ran.

    `optional` could not express this: it is per-criterion, so it would also
    have excused a missing Hợp đồng on the same criteria -- which is a real gap
    -- and its note claims the criterion says "nếu có", which only #25 does.
    """
    no_appendix = manifest([doc("contract-0", "contract"), doc("bbnt-0", "bbnt")])

    cells = {c.document: c for c in by_stt(ev.evaluate_packet(no_appendix, {}))[9].cells}

    assert cells["Phụ lục/KPI"].status is Status.NOT_APPLICABLE
    assert "nếu có" not in cells["Phụ lục/KPI"].note, "that wording belongs to #25"

    # The same criterion still calls a genuinely absent document missing.
    no_contract = manifest([doc("bbnt-0", "bbnt")])
    cells = {c.document: c for c in by_stt(ev.evaluate_packet(no_contract, {}))[9].cells}
    assert cells["Hợp đồng"].status is Status.MISSING


def test_every_criterion_naming_an_appendix_treats_it_as_optional():
    """One line each, and easy to forget on the next criterion that names one."""
    import criteria as cr_module

    for criterion in cr_module.CRITERIA:
        if cr_module.APPENDIX not in criterion.docs:
            continue
        # Only COMPARE traverses the missing-document branch. #12 names an
        # appendix and is COMPUTE, so it never reaches it -- measured: pending
        # on all 169 real manifests, never missing.
        if criterion.kind is not cr_module.Kind.COMPARE:
            continue
        params = criterion.params or {}
        excused = (
            params.get("optional")
            or cr_module.APPENDIX in (params.get("optional_docs") or ())
        )
        assert excused, f"#{criterion.stt} requires a Phụ lục that most packets lack"


class TestPendingReason:
    """A pending cell says WHY, because one chip was doing five jobs.

    Measured over 166 real packets and 4,813 pending cells: 41% no extractor
    exists for the criterion at all, 14% are the batch-level bảng kê and are
    checked on Tổng hợp, 12% are an empty bảng kê cell, 15% are a document
    that is present and whose value would not read. Only the last is the tool
    failing at something it can do, and showing all of them identically taught
    the reviewer to ignore the one about their own packet.
    """

    def _cells(self, results, stt):
        return {c.document: c for c in by_stt(results)[stt].cells}

    def test_no_extractor_for_the_criterion_is_not_automated(self):
        # #08 has no FIELD_BY_STT entry, so no packet will ever change this.
        results = ev.evaluate_packet(full_packet(), ROSTER)
        cell = self._cells(results, 8)[cr.CONTRACT]
        assert cell.status is Status.PENDING
        assert cell.pending_reason == "not-automated"

    def test_the_batch_level_document_says_it_is_checked_elsewhere(self):
        results = ev.evaluate_packet(full_packet(), ROSTER)
        for row in results:
            cell = next(
                (c for c in row.cells if c.document == cr.PURCHASE), None)
            if cell is not None and cell.status is Status.PENDING:
                assert cell.pending_reason == "roster-level"
                break
        else:
            raise AssertionError("no batch-level pending cell to check")

    def test_an_unmatched_packet_says_so_on_the_excel_column(self):
        results = ev.evaluate_packet(full_packet(), {})
        cell = self._cells(results, 2)[cr.EXCEL]
        assert cell.status is Status.PENDING
        assert cell.pending_reason == "unmatched"

    def test_an_empty_roster_cell_is_distinguished_from_an_unread_document(self):
        blank = {**ROSTER, "cccd": ""}
        cell = self._cells(ev.evaluate_packet(full_packet(), blank), 2)[cr.EXCEL]
        assert cell.pending_reason == "no-roster-value"

    def test_a_settled_status_carries_no_reason(self):
        results = ev.evaluate_packet(full_packet(), ROSTER)
        for row in results:
            for cell in row.cells:
                if cell.status is not Status.PENDING:
                    assert cell.pending_reason is None, (row.stt, cell.document)

    def test_the_reason_reaches_the_payload(self):
        results = ev.evaluate_packet(full_packet(), ROSTER)
        row = next(r for r in results if r.stt == 8)
        payload = ev.as_dict(row)
        assert any(c["pendingReason"] == "not-automated"
                   for c in payload["cells"])


class TestPartsPresenceWiring:
    """#08 and #13 are answered on presence once a reader has covered them.

    The guard is the point. `check_parts` distinguishes "nobody looked" from
    "looked and found none", and passing an empty mapping on the first case
    turns every packet's #08 and #13 into a confident "no parts found" --
    measured, the batch rollup goes to all-red with +328 findings that are not
    there. So with no reader this path must not run at all.
    """

    def _llm(self, doc_id, part, value="x", bbox=None, page=0):
        return {
            "key": part, "label": part, "group": "Điều khoản",
            "check": "semantic", "kind": "text", "expected": "",
            "sources": [{
                "docId": doc_id, "page": page, "value": value,
                "bbox": bbox if bbox is not None
                else {"x": 1, "y": 2, "width": 30, "height": 10},
                "confidence": 1.0, "provenance": "llm",
            }],
        }

    def _packet(self, *fields):
        packet = manifest(docs=[doc("contract-0", "contract")])
        packet["fields"] = list(packet.get("fields") or []) + list(fields)
        return packet

    def test_with_no_reader_the_cell_is_exactly_what_it_was(self):
        # The regression this whole design exists to prevent.
        results = by_stt(ev.evaluate_packet(self._packet(), ROSTER))
        cell = next(c for c in results[8].cells if c.document == cr.CONTRACT)
        assert cell.status is Status.PENDING
        assert cell.pending_reason == "not-automated"

    def test_every_part_found_and_located_on_one_document_is_ok(self):
        packet = self._packet(
            self._llm("contract-0", "bank"),
            self._llm("contract-0", "branch"),
            self._llm("contract-0", "province"),
        )
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        cell = next(c for c in results[8].cells if c.document == cr.CONTRACT)
        assert cell.status is Status.OK
        assert "đủ 3" in cell.note
        assert len(cell.evidence) == 3
        assert all(e.provenance == "llm" for e in cell.evidence)

    def test_a_fuzzily_located_part_does_not_earn_an_automatic_pass(self):
        """A near-miss on characters is nearly blind to a changed digit.

        MIN_RATIO scores characters, so one substituted digit in a clause
        costs about 0.02 of a 0.10 budget -- measured, 95.9% of quotes with an
        altered digit were still boxed. `ocr_extract` records the distinction
        as confidence 1.0 (exact) against 0.9 (fuzzy); testing only for a box
        threw it away at the moment it decides an automatic pass.
        """
        packet = self._packet(
            self._llm("contract-0", "bank"),
            self._llm("contract-0", "branch"),
            self._llm("contract-0", "province"),
        )
        packet["fields"][-1]["sources"][0]["confidence"] = 0.9
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        cell = next(c for c in results[8].cells if c.document == cr.CONTRACT)
        assert cell.status is Status.REVIEW

    def test_a_part_found_but_not_locatable_goes_to_a_person(self):
        # A value the reviewer cannot see is a claim, not an answer.
        packet = self._packet(
            self._llm("contract-0", "bank", bbox=None),
            self._llm("contract-0", "branch"),
            self._llm("contract-0", "province"),
        )
        packet["fields"][-3]["sources"][0]["bbox"] = None
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        cell = next(c for c in results[8].cells if c.document == cr.CONTRACT)
        assert cell.status is Status.REVIEW
        assert "chỉ được vị trí" in cell.note

    def test_some_parts_missing_goes_to_a_person_not_to_a_finding(self):
        packet = self._packet(self._llm("contract-0", "bank"))
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        cell = next(c for c in results[8].cells if c.document == cr.CONTRACT)
        assert cell.status is Status.REVIEW
        assert "Chi nhánh" in cell.note and "Tỉnh/TP" in cell.note

    def test_a_reader_finding_nothing_is_review_not_no(self):
        """A reader failing to find a clause is not the clause being absent.

        Mapping this to NO is what fabricates findings at scale.
        """
        packet = self._packet(self._llm("contract-0", "bank", value="",
                                        bbox={"x": 0, "y": 0,
                                              "width": 0, "height": 0}))
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        cell = next(c for c in results[8].cells if c.document == cr.CONTRACT)
        assert cell.status is Status.REVIEW
        assert cell.status is not Status.NO

    def test_a_part_the_criterion_never_declared_cannot_complete_it(self):
        packet = self._packet(
            self._llm("contract-0", "bank"),
            self._llm("contract-0", "mood"),
        )
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        cell = next(c for c in results[8].cells if c.document == cr.CONTRACT)
        assert cell.status is Status.REVIEW

    def test_a_criterion_with_no_parts_is_untouched(self):
        packet = self._packet(self._llm("contract-0", "bank"))
        results = by_stt(ev.evaluate_packet(packet, ROSTER))
        # #02 declares no parts; the llm sources must not reach it.
        cell = next(c for c in results[2].cells if c.document == cr.CONTRACT)
        assert cell.pending_reason != "not-automated" or cell.evidence == ()
        assert all(e.provenance != "llm" for e in cell.evidence)


def test_every_pending_cell_says_why(tmp_path):
    """The invariant, rather than five separate assertions that drift apart.

    A census over the 166 real packets found 648 pending cells (13.5%) with no
    reason -- including every unmatched packet's document columns, where the
    Excel cell said `unmatched` and its siblings dropped the fact. An untagged
    cell falls back to the old one-chip-means-five-things behaviour, so the
    fix silently stops covering the screen it was written for.
    """
    packets = [
        manifest(docs=[doc("contract-0", "contract")]),
        manifest(docs=[]),
        manifest(docs=[doc("contract-0", "contract"),
                       doc("bbnt-0", "bbnt")]),
    ]
    rosters = [ROSTER, {}, {**ROSTER, "pit": "5000", "cccd": ""}]

    untagged = []
    for packet in packets:
        for roster in rosters:
            for result in ev.evaluate_packet(packet, roster):
                for cell in result.cells:
                    if (cell.status is Status.PENDING
                            and cell.pending_reason is None):
                        untagged.append((result.stt, cell.document, cell.note))
    assert not untagged, untagged[:5]


def test_a_settled_cell_never_carries_a_pending_reason():
    # The reason is a label for one status, not a second verdict channel.
    for roster in (ROSTER, {}):
        for result in ev.evaluate_packet(full_packet(), roster):
            for cell in result.cells:
                if cell.status is not Status.PENDING:
                    assert cell.pending_reason is None, (
                        result.stt, cell.document, cell.status)
