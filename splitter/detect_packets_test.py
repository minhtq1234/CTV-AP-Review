from detect_packets import derive_threshold, covers_from_scores, packets_from_covers
from detect_packets import reconcile, Packet
from detect_packets import extract_roster_names
from detect_packets import coarse_label

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

def test_reconcile_flags_count_mismatch():
    bounds = [(3, 10), (11, 18)]
    scores = _scores_for(bounds)
    ps = reconcile(bounds, scores, ["An"], threshold=0.5)  # roster has 1, found 2
    assert ps[1].name is None
    assert "no-roster-match" in ps[1].flags
    assert all("count-mismatch" in p.flags for p in ps)

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
    assert coarse_label(aspect=0.71, ink=0.3, is_cover=True) == "Hợp đồng (bìa)"

def test_coarse_label_rotated_by_aspect():
    assert coarse_label(aspect=1.4, ink=0.2, is_cover=False) == "Phụ lục (xoay)"

def test_coarse_label_dense_vs_sparse():
    assert coarse_label(aspect=0.71, ink=0.25, is_cover=False) == "Văn bản"
    assert coarse_label(aspect=0.71, ink=0.04, is_cover=False) == "Biểu mẫu"

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
