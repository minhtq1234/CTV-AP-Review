import numpy as np

from detect_packets import derive_threshold, covers_from_scores, packets_from_covers
from detect_packets import seed_scores
from detect_packets import reconcile, Packet
from detect_packets import prune_excess_covers
from detect_packets import implausible_structure
from detect_packets import extract_roster_names
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
    assert packet_filename(0, "Huỳnh Thị Thúy Phượng", 7, 14, False) == \
        "01_Huỳnh-Thị-Thúy-Phượng_p8-15.pdf"

def test_packet_filename_none_name():
    assert packet_filename(6, None, 49, 56, False) == "07_CHUA-KHOP-TEN_p50-57.pdf"

def test_packet_filename_strips_path_illegal_chars():
    # '/' (and other path-illegal chars) are removed outright, not replaced.
    assert packet_filename(1, "A/B Co", 0, 7, False) == "02_AB-Co_p1-8.pdf"

def test_packet_filename_auto_merged_suffix():
    # Regression case: the real Trần Ứng Hỷ packet, p193-200, auto-merged.
    assert packet_filename(23, "Trần Ứng Hỷ", 192, 199, True) == \
        "24_Trần-Ứng-Hỷ_p193-200_can-xac-nhan.pdf"

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
