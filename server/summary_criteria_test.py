import pathlib
import re

import roster_checks
import summary_criteria as sc
from criteria import Kind, Status
from roster_checks_test import GOOD, sheet


def by_stt(cells):
    return {c.stt: c for c in cells}


def packet(index, cccd="", duplicate_of=None, name=""):
    record = {
        "index": index,
        "flags": ["duplicate-roster-identity"] if duplicate_of else [],
        "rosterIdentity": {"cccd": cccd, "name": name} if cccd or name else None,
    }
    if duplicate_of:
        record["duplicateOf"] = duplicate_of
    return record


def unflagged(index, cccd="", name=""):
    """A packet as stored before `flag_duplicate_identities` existed."""
    return {"index": index, "flags": [],
            "rosterIdentity": {"cccd": cccd, "name": name}}


class TestRegistry:
    def test_the_five_roster_level_criteria(self):
        assert [c.stt for c in sc.ROSTER_CRITERIA] == [20, 26, 30, 31, 32]

    def test_nineteen_is_not_among_them(self):
        # #19 is "Phí dịch vụ khớp giữa các chứng từ", folded into #14's card
        assert 19 not in sc.BY_STT

    def test_each_carries_accs_instruction(self):
        for c in sc.ROSTER_CRITERIA:
            assert len(c.how) > 40, c.stt

    def test_signatures_are_a_presence_check(self):
        assert sc.BY_STT[26].kind is Kind.PRESENCE

    def test_every_finding_site_in_roster_checks_is_routed(self):
        """No finding may be silently dropped between the two views.

        Read from the source rather than a hand-kept list, so adding a new
        `Finding(...)` to `roster_checks` without routing it fails here.
        """
        source = pathlib.Path(roster_checks.__file__).read_text()
        routed = set(sc._SUMMARY_CODES) | set(sc.PER_CTV_CODES)
        sites = re.findall(r'Finding\(\s*"#\d+",\s*f?"([^"]+)"', source)
        assert len(sites) >= 8
        for code in sites:
            if "{" in code:  # f-string family, e.g. total-mismatch-{key}
                prefix = code[:code.index("{")]
                assert any(r.startswith(prefix) for r in routed), code
            else:
                assert code in routed, code


class TestTotals:
    def test_a_matching_total_row_passes(self):
        cells = by_stt(sc.assess(sheet([GOOD], total=(10_000_000, 1_000_000,
                                                      9_000_000))))
        assert cells[20].status is Status.OK
        assert "khớp dòng tổng" in cells[20].message

    def test_a_mismatched_total_row_states_the_gap(self):
        cells = by_stt(sc.assess(sheet([GOOD], total=(10_000_000, 1_000_000,
                                                      8_000_000))))
        assert cells[20].status is Status.NO
        assert "lệch 1,000,000" in cells[20].message

    def test_no_total_row_and_no_purchase_listing_stays_pending(self):
        # This is the real July case: no roster carries a total row.
        cells = by_stt(sc.assess(sheet([GOOD])))
        assert cells[20].status is Status.PENDING
        assert "Bảng Kê Thu Mua" in cells[20].message
        # it still shows the sum it computed, so the number is not lost
        assert "10,000,000" in cells[20].message

    def test_the_purchase_listing_total_resolves_it(self):
        cells = by_stt(sc.assess(
            sheet([GOOD]), purchase_total={"gross": 10_000_000}
        ))
        assert cells[20].status is Status.OK
        assert "Gross khớp" in cells[20].message

    def test_a_purchase_listing_mismatch_is_a_finding(self):
        cells = by_stt(sc.assess(
            sheet([GOOD]), purchase_total={"gross": 9_000_000}
        ))
        assert cells[20].status is Status.NO
        assert "lệch 1,000,000" in cells[20].message

    def test_the_real_july_reconciliation(self):
        """Two CTVs summing to the total printed on the purchase listing."""
        second = (2, "079303009458", "079303009458", "01/01/1990", "222",
                  5_000_000, "không", 500_000, 4_500_000)
        cells = by_stt(sc.assess(
            sheet([GOOD, second]),
            purchase_total={"gross": 15_000_000, "pit": 1_500_000,
                            "net": 13_500_000},
        ))
        assert cells[20].status is Status.OK
        assert "Gross, PIT, Net khớp" in cells[20].message


class TestSharedValues:
    def test_a_clean_roster_passes_thirty(self):
        cells = by_stt(sc.assess(sheet([GOOD])))
        assert cells[30].status is Status.OK

    def test_a_shared_cccd_is_a_finding_naming_the_rows(self):
        twin = (2, GOOD[1], "079303009459", "01/01/1990", "222",
                1_000_000, "không", 100_000, 900_000)
        cells = by_stt(sc.assess(sheet([GOOD, twin])))
        assert cells[30].status is Status.NO
        assert any("dòng 1+2" in d for d in cells[30].detail)

    def test_a_shared_bank_account_is_a_finding(self):
        twin = (2, "079303009459", "079303009459", "01/01/1990", GOOD[4],
                1_000_000, "không", 100_000, 900_000)
        cells = by_stt(sc.assess(sheet([GOOD, twin])))
        assert cells[30].status is Status.NO


class TestDuplicatePayment:
    def test_no_packets_is_pending_not_clean(self):
        cells = by_stt(sc.assess(sheet([GOOD])))
        assert cells[31].status is Status.PENDING

    def test_packets_that_matched_nobody_cannot_pass(self):
        """No identity to compare is not the same as no collision."""
        cells = by_stt(sc.assess(
            sheet([GOOD]), packets=[packet(0), packet(1)],
        ))
        assert cells[31].status is Status.PENDING
        assert "chưa khớp" in cells[31].message

    def test_packets_with_distinct_identities_pass(self):
        cells = by_stt(sc.assess(
            sheet([GOOD]),
            packets=[packet(0, "079303009457"), packet(1, "001204004530")],
        ))
        assert cells[31].status is Status.OK

    def test_two_packets_on_one_roster_row_warn_and_name_them(self):
        cells = by_stt(sc.assess(
            sheet([GOOD]),
            packets=[
                packet(0, "079303009457", duplicate_of=[1]),
                packet(1, "079303009457", duplicate_of=[0]),
            ],
        ))
        assert cells[31].status is Status.NO
        # Acc's rule is warn-only: "Chỉ cảnh báo trùng, không tự động xóa dòng"
        assert "Chỉ cảnh báo" in cells[31].message
        assert cells[31].detail == ("gói 1 + 2",)

    def test_a_collision_is_found_without_the_pipeline_flag(self):
        """The stored July case predates `flag_duplicate_identities`: 9 CCCDs
        appear on two packets each and not one packet carries the flag. The
        criterion must read the identities, not trust a persisted flag."""
        cells = by_stt(sc.assess(sheet([GOOD]), packets=[
            unflagged(0, "079303009457"),
            unflagged(1, "079303009457"),
            unflagged(2, "001204004530"),
        ]))
        assert cells[31].status is Status.NO
        assert cells[31].detail == ("gói 1 + 2",)

    def test_a_collision_on_name_alone_is_found(self):
        cells = by_stt(sc.assess(sheet([GOOD]), packets=[
            unflagged(0, "", "Nguyễn Văn A"),
            unflagged(1, "", "NGUYEN VAN A"),
        ]))
        assert cells[31].status is Status.NO

    def test_the_real_july_shape(self):
        """Nine CTVs with two packets each — 18 of 36 flagged."""
        packets = []
        for pair in range(9):
            a, b = pair * 2, pair * 2 + 1
            cccd = f"07930300{pair:04d}"
            packets.append(packet(a, cccd, duplicate_of=[b]))
            packets.append(packet(b, cccd, duplicate_of=[a]))
        packets += [packet(i, f"00120400{i:04d}") for i in range(18, 36)]
        cells = by_stt(sc.assess(sheet([GOOD]), packets=packets))
        assert cells[31].status is Status.NO
        assert "9 CTV" in cells[31].message
        assert "18 gói" in cells[31].message
        assert len(cells[31].detail) == 9


class TestNotYetBuilt:
    def test_date_sequencing_says_so_rather_than_passing(self):
        cells = by_stt(sc.assess(sheet([GOOD])))
        assert cells[32].status is Status.PENDING
        assert "Chưa kiểm tra tự động" in cells[32].message

    def test_signatures_ask_for_a_person(self):
        cells = by_stt(sc.assess(sheet([GOOD])))
        assert cells[26].status is Status.REVIEW
        assert "Cần người kiểm tra" in cells[26].message


class TestSummary:
    def test_all_five_are_always_reported(self):
        cells = sc.assess(sheet([GOOD]))
        assert len(cells) == 5
        assert sum(sc.summarise(cells).values()) == 5

    def test_an_unhelpable_roster_never_reports_ok(self):
        """A bare roster with no packets and no purchase total: nothing is fine."""
        counts = sc.summarise(sc.assess(sheet([GOOD])))
        assert counts["ok"] == 1        # only #30, which the Excel alone settles
        assert counts["rv"] == 1        # #26 signatures
        assert counts["pending"] == 3   # #20 needs the listing, #31 packets, #32 unbuilt

    def test_every_cell_explains_itself(self):
        for cell in sc.assess(sheet([GOOD])):
            assert cell.message, cell.stt
            assert cell.label


class TestAnUnreadableRoster:
    """The inversion this design exists to prevent: nothing evaluated must not
    look like everything fine."""

    def test_an_empty_roster_cannot_pass_the_duplicate_check(self):
        cells = by_stt(sc.assess([]))
        assert cells[30].status is Status.PENDING

    def test_a_roster_with_no_locatable_columns_cannot_pass_it_either(self):
        cells = by_stt(sc.assess([("a", "b"), ("c", "d")]))
        assert cells[30].status is Status.PENDING
        assert "Không đọc được" in cells[30].message

    def test_a_header_with_no_data_rows_cannot_pass_it(self):
        cells = by_stt(sc.assess(sheet([])))
        assert cells[30].status is Status.PENDING

    def test_nothing_reports_ok_on_an_unreadable_roster(self):
        counts = sc.summarise(sc.assess([]))
        assert counts["ok"] == 0
        assert counts["no"] == 0


class TestSerialisation:
    def test_a_cell_carries_what_the_reviewer_needs_to_act(self):
        cell = by_stt(sc.assess(sheet([GOOD])))[26]
        out = sc.as_dict(cell)
        assert out["stt"] == 26
        assert out["status"] == "rv"
        assert out["label"] == sc.BY_STT[26].label
        # Acc's own instruction travels with the cell, so an abstention is
        # never a dead end for the reviewer.
        assert out["how"] == sc.BY_STT[26].how
        assert out["docs"] == list(sc.BY_STT[26].docs)
        assert out["group"] == "TH"

    def test_detail_survives_as_a_list(self):
        cells = by_stt(sc.assess(
            sheet([GOOD]),
            packets=[packet(0, "079303009457", duplicate_of=[1]),
                     packet(1, "079303009457", duplicate_of=[0])],
        ))
        assert sc.as_dict(cells[31])["detail"] == ["gói 1 + 2"]

    def test_the_whole_tab_serialises_to_json(self):
        import json

        payload = sc.as_payload(sheet([GOOD]))
        assert json.loads(json.dumps(payload)) == payload
        assert [c["stt"] for c in payload["criteria"]] == [20, 26, 30, 31, 32]
        assert payload["counts"]["pending"] == 3
        assert payload["people"] == 1

    def test_the_payload_reports_what_it_could_not_reach(self):
        payload = sc.as_payload(sheet([GOOD]))
        # neither the purchase listing total nor any packet was supplied
        assert payload["missing"] == ["purchaseTotal", "packets"]

    def test_an_unreadable_roster_is_named_first_among_the_gaps(self):
        payload = sc.as_payload([])
        assert payload["missing"][0] == "rosterRows"
        assert payload["people"] == 0

    def test_nothing_is_reported_missing_once_supplied(self):
        payload = sc.as_payload(
            sheet([GOOD]),
            packets=[packet(0, "079303009457")],
            purchase_total={"gross": 10_000_000},
        )
        assert payload["missing"] == []
        assert payload["counts"]["ok"] == 3


class TestDetailIsWhatToLookAt:
    """`detail` names rows or packets to open; the documents are already on the
    criterion itself, so repeating them there renders them twice in the UI."""

    def test_no_cell_repeats_its_own_documents_as_detail(self):
        cases = (
            ([], None, None),
            (sheet([GOOD]), None, None),
            (sheet([GOOD]), [packet(0, "079303009457")], {"gross": 10_000_000}),
            (sheet([GOOD]), [packet(0), packet(1)], None),
            (sheet([GOOD], total=(10_000_000, 1_000_000, 8_000_000)), None, None),
        )
        for rows, packets, total in cases:
            for cell in sc.assess(rows, packets, total):
                docs = set(sc.BY_STT[cell.stt].docs)
                assert not (set(cell.detail) & docs), (cell.stt, cell.detail)


class TestTheListingReadFeedsTwenty:
    """`purchaseTotal` now arrives from `pipeline.read_purchase_total`, which
    carries the read's provenance alongside the amount."""

    RICH = {"gross": 10_000_000, "page": 7,
            "reason": "digits-and-words-agree", "digitsRepaired": False}

    def test_the_richer_shape_resolves_it(self):
        cells = by_stt(sc.assess(sheet([GOOD]), purchase_total=self.RICH))

        assert cells[20].status is Status.OK
        assert "Gross khớp" in cells[20].message

    def test_a_repaired_digit_read_is_disclosed(self):
        repaired = {**self.RICH, "digitsRepaired": True}
        cells = by_stt(sc.assess(sheet([GOOD]), purchase_total=repaired))

        assert cells[20].status is Status.OK
        # the reviewer should eyeball the printed digits themselves
        assert "chữ số bị mờ" in cells[20].message

    def test_an_unreadable_total_is_pending_not_a_mismatch(self):
        """`gross: None` means the listing was found but not read. Comparing
        against None would report a bogus discrepancy against the roster."""
        unread = {"gross": None, "page": 7,
                  "reason": "digits-and-words-disagree", "digitsRepaired": False}

        cells = by_stt(sc.assess(sheet([GOOD]), purchase_total=unread))

        assert cells[20].status is Status.PENDING
        assert "lệch" not in cells[20].message
        assert "trang 8" in cells[20].message

    def test_it_says_which_way_the_read_failed(self):
        for reason, expected in (
            ("digits-and-words-disagree", "chữ số và chữ không khớp"),
            ("front-matter-too-long", "chưa tìm được Bảng Kê Thu Mua"),
        ):
            cells = by_stt(sc.assess(
                sheet([GOOD]),
                purchase_total={"gross": None, "page": None, "reason": reason,
                                "digitsRepaired": False},
            ))
            assert expected in cells[20].message, reason

    def test_the_page_is_named_so_the_reviewer_can_open_it(self):
        cells = by_stt(sc.assess(sheet([GOOD]), purchase_total=self.RICH))
        assert "trang 8" in cells[20].message

    def test_a_real_mismatch_still_reports_the_gap(self):
        cells = by_stt(sc.assess(
            sheet([GOOD]), purchase_total={**self.RICH, "gross": 9_000_000},
        ))

        assert cells[20].status is Status.NO
        assert "lệch 1,000,000" in cells[20].message

    def test_an_unread_total_still_counts_as_a_gap(self):
        payload = sc.as_payload(
            sheet([GOOD]),
            purchase_total={"gross": None, "page": 7, "reason": "x",
                            "digitsRepaired": False},
        )
        assert "purchaseTotal" in payload["missing"]
