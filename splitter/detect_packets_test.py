import numpy as np

from detect_packets import derive_threshold, covers_from_scores, packets_from_covers
from detect_packets import seed_scores
from detect_packets import reconcile, Packet
from detect_packets import prune_excess_covers
from detect_packets import implausible_structure
from detect_packets import extract_roster_names
from detect_packets import snap_covers_to_starts
from detect_packets import insert_missed_starts
from detect_packets import build_report_html
from detect_packets import coarse_label
from detect_packets import build_report_html
from detect_packets import packet_filename

def _scores_for(bounds, cover=0.9):
    # build a per-page score list where each packet's start page scores `cover`
    n = max(e for _, e in bounds) + 1
    s = [0.1] * n
    for st, _ in bounds:
        s[st] = cover
    return s

def test_reconcile_aligns_names_in_order():
    bounds = [(3, 10), (11, 18)]
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, ["An", "Binh"], threshold=0.5)
    assert [p.name for p in ps] == ["An", "Binh"]
    assert all(p.confidence == "green" for p in ps), [p.flags for p in ps]

def test_reconcile_count_mismatch_is_not_a_per_card_flag():
    # Count mismatch belongs in the report banner only (build_report_html), so
    # attention stays on the actual exception packet, not every card.
    bounds = [(3, 10), (11, 18)]
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, ["An"], threshold=0.5)  # roster has 1, found 2
    assert ps[1].name is None
    assert "no-roster-match" in ps[1].flags
    assert all("count-mismatch" not in p.flags for p in ps)

def test_reconcile_no_roster_does_not_flag_no_roster_match():
    # With no roster at all, there's nothing to mismatch against -- packets
    # should just come back unnamed and green, not amber.
    bounds = [(3, 10), (11, 18)]
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, None, threshold=0.5)
    assert all(p.name is None for p in ps)
    assert all("no-roster-match" not in p.flags for p in ps)
    assert all(p.confidence == "green" for p in ps), [p.flags for p in ps]

def test_reconcile_flags_length_out_of_range():
    bounds = [(3, 30)]  # 28 pages, way over the norm
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, ["An"], threshold=0.5, len_range=(5, 12))
    assert "length-out-of-range" in ps[0].flags
    assert ps[0].confidence == "amber"

def test_reconcile_flags_near_threshold_cover():
    bounds = [(3, 10)]
    scores = _scores_for(bounds, cover=0.52)  # only just above threshold 0.5
    ps = reconcile(bounds, scores, ["An"], threshold=0.5, near_margin=0.05)
    assert "near-threshold" in ps[0].flags

def test_implausible_structure_flags_gross_overcount_with_roster():
    assert implausible_structure(n_covers=70, total_pages=262, roster_n=32) is True

def test_implausible_structure_ok_with_roster():
    assert implausible_structure(n_covers=33, total_pages=262, roster_n=32) is False

def test_implausible_structure_flags_without_roster():
    assert implausible_structure(n_covers=100, total_pages=262, roster_n=None) is True

def test_implausible_structure_ok_without_roster():
    assert implausible_structure(n_covers=33, total_pages=262, roster_n=None) is False

def test_prune_excess_covers_drops_too_close_cover_to_hit_roster_n():
    # 20 sits only 4 pages after 16 (< min_len) -- a mid-packet false positive,
    # like a "BIÊN BẢN NGHIỆM THU" cover that visually mimics the real cover.
    covers = [0, 8, 16, 20, 28]
    scores = [0.9] * 29
    kept, merged = prune_excess_covers(covers, scores, roster_n=4, min_len=5)
    assert kept == [0, 8, 16, 28]
    assert merged == [20]

def test_prune_excess_covers_leaves_short_packet_when_count_already_matches():
    # 12 is only 4 pages after 8, but the count already equals roster_n, so
    # nothing should be force-pruned.
    covers = [0, 8, 12]
    scores = [0.9] * 13
    kept, merged = prune_excess_covers(covers, scores, roster_n=3, min_len=5)
    assert kept == [0, 8, 12]
    assert merged == []

def test_prune_excess_covers_stops_when_no_too_close_candidate():
    # count > roster_n but every gap is a normal ~8 pages -- do not force-prune
    # a legitimate boundary; leave the excess for the report to flag.
    covers = [0, 8, 16, 24]
    scores = [0.9] * 25
    kept, merged = prune_excess_covers(covers, scores, roster_n=3, min_len=5)
    assert kept == [0, 8, 16, 24]
    assert merged == []

def test_prune_excess_covers_tie_breaks_by_lowest_score():
    # two candidates tie on gap (both 4 pages); the weaker (lower cover_score)
    # one is dropped.
    covers = [0, 8, 12, 20, 24]
    scores = [0.9] * 25
    scores[12] = 0.6
    scores[24] = 0.95
    kept, merged = prune_excess_covers(covers, scores, roster_n=4, min_len=5)
    assert merged == [12]
    assert kept == [0, 8, 20, 24]

def test_prune_excess_covers_prefers_cadence_over_near_tied_score():
    # Regression for the real FA-PM260226080.pdf case: a false-positive cover
    # (a "BIÊN BẢN NGHIỆM THU" cover visually mimicking the real contract
    # cover) sits sandwiched between two real ones, so BOTH neighbouring
    # covers tie on gap-to-previous (4 pages each) and have near-identical
    # cover_score. Removing the true false positive (like p197) restores the
    # document's normal ~8-page cadence in one step; removing the other one
    # (like p201) leaves a lopsided 4/12 split. Cadence must win over a
    # razor-thin score difference.
    covers = [178, 186, 193, 197, 201, 209, 216]  # mirrors the real cover run
    scores = [0.9] * 217
    scores[197] = 0.590   # the true false positive: barely higher score
    scores[201] = 0.585   # the real next-packet cover: barely lower score
    kept, merged = prune_excess_covers(covers, scores, roster_n=6, min_len=5)
    assert merged == [197], merged
    assert kept == [178, 186, 193, 201, 209, 216]

def test_extract_roster_names_finds_column_below_header():
    rows = [
        ["BẢNG KÊ THANH TOÁN CTV", None, None],   # title band, skipped
        ["STT", "Họ và tên", "Số CCCD"],           # header row
        [1, "Nguyễn Văn A", "079..."],
        [2, "Trần Thị B", "052..."],
        [None, None, None],                         # trailing blank, skipped
    ]
    assert extract_roster_names(rows) == ["Nguyễn Văn A", "Trần Thị B"]

def test_extract_roster_names_empty_when_no_header():
    assert extract_roster_names([["x", "y"], [1, 2]]) == []

def test_coarse_label_cover_wins():
    assert coarse_label(aspect=0.71, ink=0.003, is_cover=True) == "Hợp đồng (bìa)"

def test_coarse_label_rotated_by_aspect():
    assert coarse_label(aspect=1.4, ink=0.001, is_cover=False) == "Phụ lục (xoay)"

def test_coarse_label_dense_vs_sparse():
    # Ink thresholds are calibrated to real low-DPI ink density (fraction of
    # dark pixels over the *whole page*), not a naive guess: on the real file
    # this ranges ~0.00001-0.0051 (median ~0.0014), nowhere near 0.1+.
    assert coarse_label(aspect=0.71, ink=0.003, is_cover=False) == "Văn bản"
    assert coarse_label(aspect=0.71, ink=0.0008, is_cover=False) == "Biểu mẫu"

def test_report_html_has_summary_and_cards():
    ps = [Packet(index=0, start=7, end=14, cover_score=0.9, name="Nguyễn Văn A",
                 labels=["Hợp đồng (bìa)", "Văn bản"])]
    ps[0]  # green (no flags)
    html = build_report_html(ps, roster_n=1, thumbs={0: "data:image/png;base64,AAAA"},
                             title="Test")
    assert "<html" in html.lower()
    assert "Nguyễn Văn A" in html          # name rendered
    assert "p8–15" in html                 # 1-based inclusive range (7->8, 14->15)
    assert "1 / 1" in html                 # found / roster
    assert "data:image/png;base64,AAAA" in html  # thumbnail embedded

def test_report_html_marks_amber_and_mismatch():
    ps = [Packet(index=0, start=7, end=40, cover_score=0.9, flags=["length-out-of-range"])]
    html = build_report_html(ps, roster_n=2, thumbs={}, title="T")
    assert "amber" in html
    assert "length-out-of-range" in html

def test_report_html_shows_auto_merged_count_in_banner():
    ps = [Packet(index=0, start=0, end=15, cover_score=0.9, flags=["auto-merged"])]
    html = build_report_html(ps, roster_n=1, thumbs={}, title="T")
    assert "gộp tự động" in html
    assert "auto-merged" in html

def test_report_html_no_roster_does_not_claim_mismatch():
    ps = [Packet(index=0, start=0, end=7, cover_score=0.9)]
    html = build_report_html(ps, roster_n=None, thumbs={}, title="T")
    assert "lệch số lượng" not in html
    assert "không có bảng kê" in html

def test_report_html_includes_structure_warning():
    ps = [Packet(index=0, start=0, end=7, cover_score=0.9)]
    html = build_report_html(ps, roster_n=1, thumbs={}, title="T",
                              warning="Không phát hiện cấu trúc hồ sơ lặp lại")
    assert "Không phát hiện cấu trúc hồ sơ lặp lại" in html

def test_seed_scores_self_similarity_not_corrupted():
    # 3 near-identical "cover" bands (the recurring boundary) + 5 distinct
    # "noise" bands (unique page content), as small synthetic arrays -- no PDF
    # needed. Regression test for the bug where sim's diagonal (masked to -1.0
    # for recurrence/seed-selection) leaked into the returned per-page scores,
    # forcing the seed's own score to a false -1.0 outlier instead of its true
    # self-similarity (~1.0) and corrupting derive_threshold's gap search.
    base = np.array([[10.0, 20.0], [30.0, 40.0]], dtype=np.float32)
    covers = [base + i * 0.01 for i in range(3)]
    # Genuinely distinct directions (not scalar multiples of one pattern --
    # those would collapse to the same direction after zero-mean/unit-norm).
    noise = [
        np.array([[1.0, 9.0], [4.0, 2.0]], dtype=np.float32),
        np.array([[7.0, 1.0], [8.0, 3.0]], dtype=np.float32),
        np.array([[2.0, 6.0], [1.0, 5.0]], dtype=np.float32),
        np.array([[9.0, 2.0], [3.0, 7.0]], dtype=np.float32),
        np.array([[4.0, 8.0], [6.0, 1.0]], dtype=np.float32),
    ]
    bands = covers + noise
    scores, seed = seed_scores(bands)
    assert seed < 3, seed                     # seed picked from the recurring covers
    assert scores[seed] > 0.9, scores[seed]   # true self-similarity, NOT -1.0

def test_packet_filename_normal_name():
    # index 0 -> order "01"; pages are 1-based inclusive (start+1..end+1).
    assert packet_filename(0, "Vũ Thị Kim Ngân", 7, 14, False) == \
        "01_Vũ-Thị-Kim-Ngân_p8-15.pdf"

def test_packet_filename_none_name():
    assert packet_filename(6, None, 49, 56, False) == "07_CHUA-KHOP-TEN_p50-57.pdf"

def test_packet_filename_strips_path_illegal_chars():
    # '/' (and other path-illegal chars) are removed outright, not replaced.
    assert packet_filename(1, "A/B Co", 0, 7, False) == "02_AB-Co_p1-8.pdf"

def test_packet_filename_auto_merged_suffix():
    # Regression case: a real packet at p193-200, auto-merged. The name is a
    # synthetic stand-in -- this repo is published to a public remote.
    assert packet_filename(23, "Lưu Ứng Kỳ", 192, 199, True) == \
        "24_Lưu-Ứng-Kỳ_p193-200_can-xac-nhan.pdf"

def test_derive_threshold_splits_bimodal():
    # covers ~0.9, rest ~0.2 -> threshold sits in the gap
    scores = [0.2, 0.18, 0.9, 0.22, 0.88, 0.19]
    t = derive_threshold(scores)
    assert 0.22 < t < 0.88, t

def test_covers_from_scores_selects_high():
    scores = [0.2, 0.9, 0.22, 0.88]
    assert covers_from_scores(scores, 0.5) == [1, 3]

def test_packets_drop_preamble_and_span_to_next_cover():
    # covers at pages 3 and 7, 10 pages total; pages 0-2 are preamble
    assert packets_from_covers([3, 7], 10) == [(3, 6), (7, 9)]

def test_packets_empty_when_no_covers():
    assert packets_from_covers([], 10) == []

if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn(); print(f"  ok {name}")
    print("ALL OK")


# ---------------------------------------------------------------------------
# snap_covers_to_starts — the boundary fix.
#
# The band detector finds a strongly recurring page once per packet, but that
# page is not necessarily the packet's first. On the real July submission it is
# the *fourth*: covers landed on pages 12, 20, 28 while each CTV's documents
# actually begin at 9, 17, 25. Every packet therefore held the tail of the
# previous CTV's documents, which is what the criteria matrix surfaced as 32 of
# 36 packets disagreeing on the CTV's name.
# ---------------------------------------------------------------------------

def _classifier(kinds):
    """A fake page classifier over `{page_index: kind}`, counting its calls."""
    calls = []

    def classify(page):
        calls.append(page)
        return kinds.get(page)
    return classify, calls


class TestSnapCoversToStarts:
    #: The real July shape: contract at 9/17/25 (0-based 8/16/24), cover three
    #: pages later, then bbnt, appendix, pit.
    JULY = {
        8: "contract", 12: "bbnt", 13: "bbnt", 14: "appendix", 15: "pit",
        16: "contract", 20: "bbnt", 22: "appendix", 23: "pit",
        24: "contract", 27: "bbnt", 30: "appendix", 31: "pit",
    }

    def test_it_moves_each_cover_back_to_its_contract(self):
        classify, _ = _classifier(self.JULY)

        starts, report = snap_covers_to_starts([11, 19, 27], classify)

        assert starts == [8, 16, 24]
        assert report["shifted"] == 3

    def test_a_cover_already_at_a_start_does_not_move(self):
        classify, _ = _classifier(self.JULY)

        starts, report = snap_covers_to_starts([8, 16, 24], classify)

        assert starts == [8, 16, 24]
        assert report["shifted"] == 0

    def test_the_nearest_start_wins(self):
        # Walking back from 24 must stop at 24, not continue to 16.
        classify, calls = _classifier(self.JULY)

        starts, _ = snap_covers_to_starts([24], classify)

        assert starts == [24]
        assert calls == [24]

    def test_no_start_within_the_window_leaves_the_cover_alone(self):
        """The PUBGm nghiệm thu submission has no contracts at all. Its
        boundaries must not move on a guess."""
        classify, _ = _classifier({})

        starts, report = snap_covers_to_starts([32, 38, 44], classify)

        assert starts == [32, 38, 44]
        assert report["offset"] is None
        assert report["shifted"] == 0

    def test_one_cover_finding_a_start_moves_them_both(self):
        """A cover that found nothing is a failed page read, not evidence of a
        different offset — so the offset the other cover found applies to it
        too, keeping the packets evenly sized."""
        classify, _ = _classifier({8: "contract"})

        starts, report = snap_covers_to_starts([11, 19], classify)

        assert starts == [8, 16]
        assert report["offset"] == 3
        assert report["inferred"] == [19]

    def test_a_cover_too_near_the_front_to_move_stays_put(self):
        """Shifting it would put a packet's start inside the batch-level front
        matter, so it keeps its place and says so."""
        classify, _ = _classifier({5: "contract"})

        starts, report = snap_covers_to_starts([2, 8], classify)

        assert report["offset"] == 3
        assert report["immovable"] == [2]
        assert starts == [2, 5]

    def test_distinct_covers_always_give_distinct_starts(self):
        classify, _ = _classifier({i * 8: "contract" for i in range(5)})
        covers = [i * 8 + 3 for i in range(5)]

        starts, _ = snap_covers_to_starts(covers, classify)

        assert len(starts) == len(set(starts)) == len(covers)

    def test_the_window_bounds_the_search(self):
        classify, calls = _classifier({0: "contract"})

        starts, _ = snap_covers_to_starts([20], classify, window=4)

        assert starts == [20]
        assert calls == [20, 19, 18, 17]

    def test_a_page_before_the_document_start_is_never_asked_for(self):
        classify, calls = _classifier({})

        snap_covers_to_starts([1], classify, window=8)

        assert calls == [1, 0]

    def test_pages_are_classified_once_across_overlapping_windows(self):
        """Adjacent covers walk over the same pages; OCR is the expensive part
        here, so it must not be repeated."""
        classify, calls = _classifier({8: "contract"})

        snap_covers_to_starts([11, 12, 13], classify, window=8)

        assert len(calls) == len(set(calls))

    def test_what_counts_as_a_start_is_configurable(self):
        classify, _ = _classifier({8: "bbnt"})

        starts, _ = snap_covers_to_starts(
            [11], classify, start_kinds=("bbnt",),
        )

        assert starts == [8]

    def test_no_covers_at_all(self):
        classify, calls = _classifier({})
        assert snap_covers_to_starts([], classify)[0] == []
        assert calls == []

    def test_the_report_names_the_single_offset_it_applied(self):
        classify, _ = _classifier(self.JULY)

        _, report = snap_covers_to_starts([11, 19, 27], classify)

        assert report["offset"] == 3
        assert report["shifted"] == 3
        assert report["reason"] == ""


class TestReconcileAfterSnapping:
    """Snapping moves each packet's start off the recurring cover page, whose
    score is what `near-threshold` is about. Reading the score at the *start*
    page instead would flag every packet."""

    #: The real July shape: cover ~0.96, contract first page ~0.19, threshold
    #: ~0.50.
    SCORES = [0.19, 0.17, 0.19, 0.96, 0.06, 0.17, 0.11, 0.04,
              0.19, 0.12, 0.22, 0.97, 0.07, 0.16, 0.17, 0.10]

    def test_without_cover_scores_it_reads_the_start_page(self):
        # Unchanged behaviour for the splitter CLI, which does not snap.
        packets = reconcile([(3, 10), (11, 15)], self.SCORES, None, 0.50)
        assert [p.cover_score for p in packets] == [0.96, 0.97]

    def test_supplied_cover_scores_are_used_instead(self):
        packets = reconcile([(0, 7), (8, 15)], self.SCORES, None, 0.50,
                            cover_scores=[0.96, 0.97])

        assert [p.cover_score for p in packets] == [0.96, 0.97]
        assert not any("near-threshold" in p.flags for p in packets)

    def test_without_them_a_snapped_packet_looks_falsely_marginal(self):
        packets = reconcile([(0, 7), (8, 15)], self.SCORES, None, 0.50)
        assert all("near-threshold" in p.flags for p in packets)

    def test_a_genuinely_marginal_cover_is_still_flagged(self):
        packets = reconcile([(0, 7)], self.SCORES, None, 0.50,
                            cover_scores=[0.52])
        assert "near-threshold" in packets[0].flags

    def test_a_short_cover_score_list_falls_back_per_packet(self):
        packets = reconcile([(0, 7), (8, 15)], self.SCORES, None, 0.50,
                            cover_scores=[0.96])
        assert packets[0].cover_score == 0.96
        assert packets[1].cover_score == self.SCORES[8]


class TestSnapReportsItsCovers:
    """`reconcile` needs each packet's cover score, and after snapping the start
    page is no longer the cover — so the mapping has to come back out."""

    def test_each_start_names_the_cover_it_came_from(self):
        classify, _ = _classifier({8: "contract", 16: "contract"})

        starts, report = snap_covers_to_starts([11, 19], classify)

        assert report["cover_of"] == {8: 11, 16: 19}

    def test_a_submission_that_did_not_snap_has_no_mapping_to_make(self):
        classify, _ = _classifier({})
        _, report = snap_covers_to_starts([11], classify)
        assert report["cover_of"] == {}
        assert report["offset"] is None

    def test_too_few_covers_finding_a_start_snaps_nothing(self):
        """One page's evidence must not shift a whole submission."""
        classify, _ = _classifier({8: "contract"})

        starts, report = snap_covers_to_starts([11, 19, 27, 35], classify)

        assert starts == [11, 19, 27, 35]
        assert "too-few-starts: 1/4" in report["reason"]


class TestTheSnapMustBeConsistent:
    """The offset from a packet's start to its recurring cover is a property of
    the submission's document template, so it is the same for every packet. A
    mixed result means the classification is unreliable, not that the offsets
    genuinely vary — and snapping some covers but not others produces packets of
    wildly different lengths. On the PUBGm submission an unfixed classifier
    snapped 19 of 25 covers and left a two-page packet in the split.
    """

    def test_a_unanimous_shift_is_applied(self):
        classify, _ = _classifier({0: "contract", 8: "contract", 16: "contract"})

        starts, report = snap_covers_to_starts([3, 11, 19], classify)

        assert starts == [0, 8, 16]
        assert report["offset"] == 3

    def test_a_dominant_shift_is_applied_to_every_cover(self):
        # Three covers agree on 3; the fourth found nothing. Applying the
        # dominant offset keeps the packets evenly sized.
        classify, _ = _classifier({0: "contract", 8: "contract", 16: "contract"})

        starts, report = snap_covers_to_starts([3, 11, 19, 27], classify)

        assert starts == [0, 8, 16, 24]
        assert report["offset"] == 3
        assert report["inferred"] == [27]

    def test_a_scattered_result_snaps_nothing(self):
        # Half the covers say 4, the rest say 0 — nothing to trust.
        classify, _ = _classifier({
            0: "contract", 6: "contract",
            14: "contract", 20: "contract",
        })

        starts, report = snap_covers_to_starts([4, 6, 14, 20], classify)

        assert starts == [4, 6, 14, 20]
        assert report["offset"] is None
        assert report["shifted"] == 0
        assert "inconsistent" in report["reason"]

    def test_no_start_found_anywhere_snaps_nothing(self):
        classify, _ = _classifier({})

        starts, report = snap_covers_to_starts([4, 10, 16], classify)

        assert starts == [4, 10, 16]
        assert report["offset"] is None
        assert "no-start-found" in report["reason"]

    def test_an_offset_of_zero_is_a_valid_answer(self):
        # The February submission: covers already sit on the packet starts.
        classify, _ = _classifier({4: "contract", 12: "contract"})

        starts, report = snap_covers_to_starts([4, 12], classify)

        assert starts == [4, 12]
        assert report["offset"] == 0
        assert report["shifted"] == 0

    def test_a_shift_is_never_applied_before_the_document_start(self):
        classify, _ = _classifier({0: "contract", 8: "contract", 16: "contract"})

        starts, report = snap_covers_to_starts([1, 9, 17], classify)

        # cover 1 cannot move back 8; it stays, and says so
        assert starts[0] >= 0
        assert report["offset"] is not None

    def test_the_real_july_shape_is_unanimous(self):
        kinds = {}
        for block in range(6):
            kinds[block * 8] = "contract"
            kinds[block * 8 + 4] = "bbnt"
        covers = [block * 8 + 3 for block in range(6)]

        starts, report = snap_covers_to_starts(covers, _classifier(kinds)[0])

        assert starts == [block * 8 for block in range(6)]
        assert report["offset"] == 3


# ---------------------------------------------------------------------------
# insert_missed_starts — the other half of the boundary problem.
#
# Snapping fixes covers that are in the wrong *place*. This handles covers that
# were never found at all: five July packets ran 14-16 pages against a median of
# 8, each holding two CTVs, which is why 36 packets came back for 41 roster rows.
# ---------------------------------------------------------------------------

class TestInsertMissedStarts:
    #: The real July shape after snapping: mostly 8-page packets, with one
    #: 16-page packet whose interior carries a contract page 8 pages in.
    def _july(self, merged_at=4):
        starts = [i * 8 for i in range(6)]
        kinds = {s: "contract" for s in starts}
        merged = starts.pop(merged_at)      # its cover was never found
        kinds[merged] = "contract"          # but its contract page is there
        return starts, kinds, merged

    def test_it_splits_a_packet_that_holds_two_ctvs(self):
        starts, kinds, merged = self._july()
        classify, _ = _classifier(kinds)

        out, report = insert_missed_starts(starts, 48, classify)

        assert merged in out
        assert out == sorted(set(starts) | {merged})
        assert report["inserted"] == [merged]

    def test_a_packet_of_normal_length_is_left_alone(self):
        classify, calls = _classifier({i * 8: "contract" for i in range(4)})

        out, report = insert_missed_starts([0, 8, 16, 24], 32, classify)

        assert out == [0, 8, 16, 24]
        assert report["inserted"] == []
        assert calls == []               # nothing even read

    def test_a_slightly_long_packet_is_not_split(self):
        """A 9-page packet against a median of 8 is normal variation, not two
        CTVs. Only a packet at least half again as long is a candidate."""
        starts = [0, 8, 16, 24, 33]      # last runs 33..41 = 9 pages
        classify, calls = _classifier({s: "contract" for s in starts})

        out, report = insert_missed_starts(starts, 42, classify)

        assert out == starts
        assert calls == []

    def test_it_will_not_slice_off_a_fragment(self):
        """A contract page two pages into a long packet would leave a two-page
        packet behind — that is a stray title page, not a CTV's documents."""
        classify, _ = _classifier({0: "contract", 8: "contract", 18: "contract"})

        out, report = insert_missed_starts([0, 8], 32, classify)

        # 8..31 is 24 pages, so it is scanned; 18 is far enough in to be real
        assert 18 in out
        # but a page at 9 would not be
        classify2, _ = _classifier({0: "contract", 8: "contract", 9: "contract"})
        out2, report2 = insert_missed_starts([0, 8], 32, classify2)
        assert out2 == [0, 8]
        assert report2["inserted"] == []

    def test_two_missed_covers_in_one_run_are_both_found(self):
        classify, _ = _classifier({0: "contract", 8: "contract",
                                   16: "contract", 24: "contract"})

        out, report = insert_missed_starts([0, 8], 32, classify)

        assert out == [0, 8, 16, 24]
        assert report["inserted"] == [16, 24]

    def test_the_baseline_is_the_most_common_length_not_the_median(self):
        """Three 8-page packets and two merged 16-page ones: the median of
        [8, 8, 8, 16, 16] is 8, but of [8, 8, 16, 16] it is 16 — which would
        hide both merges. The mode is 8 either way."""
        starts = [0, 8, 16, 32]          # 16..31 and 32..47 are 16pp each
        classify, _ = _classifier({s: "contract" for s in
                                   (0, 8, 16, 24, 32, 40)})

        out, report = insert_missed_starts(starts, 48, classify)

        assert report["typical"] == 8
        assert report["inserted"] == [24, 40]
        assert out == [0, 8, 16, 24, 32, 40]

    def test_a_long_packet_with_no_contract_inside_is_left_alone(self):
        """One CTV really can have more documents than the rest. Without a
        document start inside, there is nothing to act on."""
        classify, _ = _classifier({0: "contract", 8: "contract"})

        out, report = insert_missed_starts([0, 8], 40, classify)

        assert out == [0, 8]
        assert report["inserted"] == []

    def test_no_starts_at_all(self):
        classify, calls = _classifier({})
        assert insert_missed_starts([], 10, classify) == ([], {
            "inserted": [], "scanned": 0, "typical": 0, "classified": 0})
        assert calls == []

    def test_a_single_packet_has_no_baseline_to_compare_against(self):
        # One packet spanning the whole document: nothing to call anomalous.
        classify, calls = _classifier({0: "contract", 8: "contract"})
        out, report = insert_missed_starts([0], 16, classify)
        assert out == [0]
        assert calls == []

    def test_the_report_names_what_it_scanned(self):
        starts, kinds, merged = self._july()
        classify, _ = _classifier(kinds)

        _, report = insert_missed_starts(starts, 48, classify)

        assert report["typical"] == 8
        assert report["scanned"] == 1
        assert report["classified"] > 0

    def test_what_counts_as_a_start_is_configurable(self):
        classify, _ = _classifier({0: "bbnt", 8: "bbnt", 24: "bbnt"})

        out, _ = insert_missed_starts([0, 8], 32, classify,
                                      start_kinds=("bbnt",))

        assert 24 in out


class TestAnInsertedBoundaryHasNoCover:
    """A boundary found from a document title was never detected as a cover, so
    `near-threshold` — which is about how strongly the cover scored — says
    nothing about it. It gets its own flag instead."""

    SCORES = [0.19] * 8 + [0.96] + [0.11] * 8 + [0.97] + [0.08] * 8

    def test_a_none_score_is_flagged_as_inferred_not_marginal(self):
        packets = reconcile([(0, 7), (8, 15)], self.SCORES, None, 0.50,
                            cover_scores=[0.96, None])

        assert "near-threshold" not in packets[1].flags
        assert "inferred-boundary" in packets[1].flags

    def test_a_real_cover_is_not_flagged_as_inferred(self):
        packets = reconcile([(0, 7)], self.SCORES, None, 0.50,
                            cover_scores=[0.96])

        assert "inferred-boundary" not in packets[0].flags

    def test_an_inferred_packet_reports_no_cover_score(self):
        packets = reconcile([(0, 7)], self.SCORES, None, 0.50,
                            cover_scores=[None])
        assert packets[0].cover_score is None

    def test_a_marginal_real_cover_is_still_flagged(self):
        packets = reconcile([(0, 7), (8, 15)], self.SCORES, None, 0.50,
                            cover_scores=[0.52, None])

        assert "near-threshold" in packets[0].flags
        assert "inferred-boundary" in packets[1].flags


class TestTheReportSurvivesAnInferredBoundary:
    def test_it_renders_a_packet_with_no_cover_score(self):
        packets = [Packet(index=0, start=0, end=7, cover_score=None)]

        html = build_report_html(packets, None, {}, "x.pdf")

        assert "8 trang" in html
        assert "None" not in html
