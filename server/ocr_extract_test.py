from ocr_extract import scale_words, group_lines, union_bbox, norm, find_in_lines, PATTERNS

def W(text, x, y, w, h, conf=90): return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf}

def test_scale_words_halves_boxes():
    out = scale_words([W("a", 100, 200, 40, 20)], 0.5)
    assert out[0]["x"] == 50 and out[0]["y"] == 100 and out[0]["w"] == 20 and out[0]["h"] == 10
    assert out[0]["text"] == "a"

def test_group_lines_clusters_by_y():
    words = [W("Ho", 10, 100, 20, 18), W("ten", 40, 102, 20, 18), W("MST", 10, 200, 30, 18)]
    lines = group_lines(words, y_tol=8)
    assert len(lines) == 2
    assert [w["text"] for w in lines[0]] == ["Ho", "ten"]   # x-sorted, same row
    assert [w["text"] for w in lines[1]] == ["MST"]

def test_union_bbox_encloses():
    b = union_bbox([W("a", 10, 20, 30, 10), W("b", 50, 25, 20, 15)])
    assert b == {"x": 10, "y": 20, "width": 60, "height": 20}

def test_norm_strips_diacritics_and_case():
    assert norm("Mã số thuế") == "ma so thue"
    assert norm("CĂN CƯỚC") == "can cuoc"

def test_find_mst_on_anchor_line():
    lines = [[W("Mã", 10, 50, 20, 18), W("số", 35, 50, 15, 18), W("thuế", 55, 50, 25, 18),
              W("0303490096", 120, 50, 90, 18, conf=95)]]
    hits = find_in_lines(lines, anchors=["ma so thue"], pattern=PATTERNS["MST"])
    assert len(hits) == 1
    assert hits[0]["value"] == "0303490096"
    assert abs(hits[0]["confidence"] - 0.95) < 1e-6
    assert hits[0]["bbox"]["x"] == 120 and hits[0]["bbox"]["width"] == 90

def test_find_cccd_spaced_boxes_joins_digits():
    # boxed CCCD: single-digit words across the line
    digs = [W(d, 100 + i*20, 80, 12, 18) for i, d in enumerate("048091001309")]
    lines = [[W("Mã", 10, 80, 20, 18), W("số", 35, 80, 15, 18), W("thuế", 55, 80, 25, 18)] + digs]
    hits = find_in_lines(lines, anchors=["ma so thue"], pattern=PATTERNS["CCCD_SPACED"])
    assert hits and hits[0]["value"] == "048091001309"
    # bbox spans the 12 digit words
    assert hits[0]["bbox"]["x"] == 100 and hits[0]["bbox"]["width"] == 12*20 - 8

def test_find_value_on_next_line():
    lines = [[W("Ngày", 10, 50, 30, 18), W("sinh", 45, 50, 25, 18)],
             [W("24/04/1991", 10, 72, 90, 18, conf=88)]]
    hits = find_in_lines(lines, anchors=["ngay sinh"], pattern=PATTERNS["DATE"], allow_next_line=True)
    assert hits and hits[0]["value"] == "24/04/1991"

def test_find_returns_empty_when_no_anchor():
    lines = [[W("random", 10, 50, 40, 18)]]
    assert find_in_lines(lines, anchors=["ma so thue"], pattern=PATTERNS["MST"]) == []

if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
