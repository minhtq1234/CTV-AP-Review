from ocr_extract import (
    scale_words, group_lines, union_bbox, norm, find_in_lines, PATTERNS,
    extract_fields, build_manifest,
)

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

def test_extract_fields_assembles_manifest_fields():
    words_by_doc = {
        "bbnt": {0: [
            W("Mã", 10, 50, 20, 18), W("số", 35, 50, 15, 18), W("thuế", 55, 50, 25, 18),
            W("0303490096", 120, 50, 90, 18, conf=95),
            W("Căn", 10, 100, 25, 18), W("cước", 40, 100, 30, 18),
            *[W(d, 100 + i * 20, 130, 12, 18) for i, d in enumerate("048091001309")],
            W("Bên", 10, 160, 25, 18), W("cung", 40, 160, 30, 18), W("ứng", 75, 160, 25, 18),
            W("dịch", 105, 160, 30, 18), W("vụ", 140, 160, 20, 18),
            W("Nguyễn", 180, 160, 55, 18), W("Văn", 240, 160, 35, 18), W("A", 280, 160, 15, 18),
        ]},
        "tra_cuu_mst": {0: [
            W("Mã", 10, 50, 20, 18), W("số", 35, 50, 15, 18), W("thuế", 55, 50, 25, 18),
            W("0303490096", 120, 50, 90, 18, conf=90),
        ]},
    }
    roster_row = {
        "name": "Nguyễn Văn A",
        "cccd": "048091001309",
        "mst": "0303490096",
        "tk": "19001234567",
        "ngaysinh": "24/04/1991",
        "phi": "10.000.000",
    }
    fields = extract_fields(words_by_doc, roster_row)
    assert len(fields) == 6
    by_key = {f["key"]: f for f in fields}
    assert set(by_key) == {"hoten", "cccd", "mst", "tk", "ngaysinh", "phi"}
    for f in fields:
        assert f["check"] == "compare"

    assert by_key["mst"]["expected"] == "0303490096"
    assert len(by_key["mst"]["sources"]) == 2
    assert {s["docId"] for s in by_key["mst"]["sources"]} == {"bbnt", "tra_cuu_mst"}
    for s in by_key["mst"]["sources"]:
        assert s["value"] == "0303490096"
        assert s["page"] == 0
        assert 0 < s["confidence"] <= 1

    assert by_key["hoten"]["expected"] == "Nguyễn Văn A"
    assert len(by_key["hoten"]["sources"]) == 1
    assert by_key["hoten"]["sources"][0]["value"] == "Nguyễn Văn A"
    assert by_key["hoten"]["sources"][0]["docId"] == "bbnt"

    assert by_key["cccd"]["expected"] == "048091001309"
    assert len(by_key["cccd"]["sources"]) == 1
    assert by_key["cccd"]["sources"][0]["value"] == "048091001309"

    # phi has no OCR hit anywhere -> single empty/low-confidence fallback source,
    # so it reads as an exception in the reviewer rather than silently vanishing.
    assert by_key["phi"]["expected"] == "10.000.000"
    assert len(by_key["phi"]["sources"]) == 1
    assert by_key["phi"]["sources"][0]["value"] == ""
    assert by_key["phi"]["sources"][0]["confidence"] == 0.0


def test_build_manifest_shape():
    fields = extract_fields({}, {"name": "X"})
    docs = [{"id": "packet", "kind": "contract", "label": "Hồ sơ",
             "pages": [{"src": "p0.png", "width": 100, "height": 200}]}]
    m = build_manifest("f1", "Nguyễn Văn A", "CTV Flight", docs, fields)
    assert m["id"] == "f1"
    assert m["name"] == "Nguyễn Văn A"
    assert m["product"] == "CTV Flight"
    assert m["heading"] == "Hồ sơ CTV"
    assert m["status"] == "pending"
    assert m["exempt"] is False
    assert m["docs"] == docs
    assert m["fields"] == fields
    assert set(m.keys()) == {"id", "name", "product", "heading", "status", "exempt", "docs", "fields"}


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
