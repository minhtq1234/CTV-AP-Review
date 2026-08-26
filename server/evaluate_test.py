import criteria as cr
import evaluate as ev
from criteria import Status


# --- fixtures ----------------------------------------------------------------

def source(doc_id, value, page=0, conf=0.95, bbox=True):
    return {"docId": doc_id, "page": page, "value": value,
            "confidence": conf,
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 30} if bbox
            else None}


def doc(doc_id, kind, label=""):
    return {"id": doc_id, "kind": kind, "label": label or kind,
            "pages": [{"src": "pg0.png", "width": 100, "height": 100}]}


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

    def test_a_low_confidence_agreement_needs_a_human(self):
        packet = manifest(
            docs=[doc("contract-0", "contract")],
            fields=[("cccd", "079203031329",
                     [source("contract-0", "079203031329", conf=0.4)])],
        )
        result = by_stt(ev.evaluate_packet(packet, ROSTER))[2]
        cell = cells_by_doc(result)[cr.CONTRACT]

        assert cell.status is Status.REVIEW
        assert "0.4" in cell.note or "40" in cell.note

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
