from ocr_extract import (
    scale_words, group_lines, union_bbox, norm, find_in_lines, PATTERNS,
    extract_fields, build_manifest, find_name, FIELD_SPECS,
    classify_page, segment_docs,
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

def _mst_hits(lines):
    mst_spec = next(s for s in FIELD_SPECS if s["key"] == "mst")
    hits = []
    for pattern in mst_spec["patterns"]:
        hits.extend(find_in_lines(lines, anchors=mst_spec["anchors"], pattern=pattern))
    return hits

def test_mst_field_ignores_bare_company_label():
    # "Mã số thuế : 0303490096" with no TNCN marker -- this is what the
    # company ("Bên sử dụng dịch vụ") block and the VNG MST use; must not
    # produce an mst source, or it false-mismatches against the person's own
    # tax id under worst-wins.
    lines = [[W("Mã", 10, 50, 20, 18), W("số", 35, 50, 15, 18), W("thuế", 55, 50, 25, 18),
              W(":", 80, 50, 10, 18), W("0303490096", 100, 50, 90, 18, conf=95)]]
    assert _mst_hits(lines) == []

def test_mst_field_matches_msttncn_individual_marker():
    # spaced-box format (matches the cam-kết doc's boxed MSTTNCN digits, per
    # "Keep the digit pattern (plain + spaced-box)").
    digs = [W(d, 120 + i * 15, 50, 12, 18, conf=93) for i, d in enumerate("048091001309")]
    lines = [[W("MSTTNCN", 10, 50, 70, 18), W(":", 85, 50, 10, 18)] + digs]
    hits = _mst_hits(lines)
    assert len(hits) == 1
    assert hits[0]["value"] == "048091001309"
    assert hits[0]["bbox"]["x"] == 120

def test_mst_field_ignores_bare_mst_label_near_search_box_number():
    # Tax-lookup search box: a lone "MST" label next to an unrelated number
    # (e.g. the search input's own placeholder/example) -- must not match.
    lines = [[W("MST", 10, 50, 30, 18), W("8364842409", 50, 50, 90, 18, conf=91)]]
    assert _mst_hits(lines) == []

def test_extract_fields_assembles_manifest_fields():
    words_by_doc = {
        "bbnt": {0: [
            # MSTTNCN (individual tax-id marker, spaced-box digits), not the
            # bare "Mã số thuế" the company block also uses -- see
            # test_mst_field_ignores_bare_company_label. Real Vietnamese
            # individuals' MSTTNCN commonly equals their CCCD, hence the same
            # digit string as the "Căn cước" line below -- this doc also
            # legitimately cross-confirms the cccd field via that shared
            # "msttncn" anchor (cccd's own FIELD_SPEC already lists it).
            W("MSTTNCN", 10, 40, 70, 18), W(":", 85, 40, 10, 18),
            *[W(d, 120 + i * 15, 40, 12, 18, conf=93) for i, d in enumerate("048091001309")],

            W("Căn", 10, 100, 25, 18), W("cước", 40, 100, 30, 18),
            *[W(d, 100 + i * 20, 130, 12, 18) for i, d in enumerate("048091001309")],
            # ALL-CAPS signature line -- the labeled-context form real contracts
            # use (see test_find_name_accepts_all_caps_signature_line); a mixed
            # case in-prose occurrence should NOT produce a hoten source.
            W("BÊN", 10, 160, 25, 18), W("CUNG", 40, 160, 30, 18), W("ỨNG", 75, 160, 25, 18),
            W("DỊCH", 105, 160, 30, 18), W("VỤ", 140, 160, 20, 18),
            W("Nguyễn", 180, 160, 55, 18), W("Văn", 240, 160, 35, 18), W("A", 280, 160, 15, 18),
        ]},
        "tra_cuu_mst": {0: [
            W("MSTTNCN", 10, 40, 70, 18), W(":", 85, 40, 10, 18),
            *[W(d, 120 + i * 15, 40, 12, 18, conf=90) for i, d in enumerate("048091001309")],
        ]},
    }
    roster_row = {
        "name": "Nguyễn Văn A",
        "cccd": "048091001309",
        "mst": "048091001309",
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

    assert by_key["mst"]["expected"] == "048091001309"
    assert len(by_key["mst"]["sources"]) == 2
    assert {s["docId"] for s in by_key["mst"]["sources"]} == {"bbnt", "tra_cuu_mst"}
    for s in by_key["mst"]["sources"]:
        assert s["value"] == "048091001309"
        assert s["page"] == 0
        assert 0 < s["confidence"] <= 1

    assert by_key["hoten"]["expected"] == "Nguyễn Văn A"
    assert len(by_key["hoten"]["sources"]) == 1
    assert by_key["hoten"]["sources"][0]["value"] == "Nguyễn Văn A"
    assert by_key["hoten"]["sources"][0]["docId"] == "bbnt"

    # cccd's own FIELD_SPEC anchors on "msttncn" too (an individual's MSTTNCN
    # commonly equals their CCCD), so bbnt legitimately confirms it via two
    # different lines ("Căn cước" + "MSTTNCN") -- but both are the SAME
    # document agreeing with itself, so they dedupe to bbnt's single
    # highest-confidence hit (the "MSTTNCN" line, conf 0.93). tra_cuu_mst is
    # a different document, so it stays as its own, distinct source: 2
    # sources total, one per confirming document.
    assert by_key["cccd"]["expected"] == "048091001309"
    assert len(by_key["cccd"]["sources"]) == 2
    assert {s["docId"] for s in by_key["cccd"]["sources"]} == {"bbnt", "tra_cuu_mst"}
    assert all(s["value"] == "048091001309" for s in by_key["cccd"]["sources"])
    bbnt_cccd_source = next(s for s in by_key["cccd"]["sources"] if s["docId"] == "bbnt")
    assert abs(bbnt_cccd_source["confidence"] - 0.93) < 1e-6

    # phi has no OCR hit anywhere -> single empty/low-confidence fallback source,
    # so it reads as an exception in the reviewer rather than silently vanishing.
    assert by_key["phi"]["expected"] == "10.000.000"
    assert len(by_key["phi"]["sources"]) == 1
    assert by_key["phi"]["sources"][0]["value"] == ""
    assert by_key["phi"]["sources"][0]["confidence"] == 0.0


def test_extract_fields_dedupes_same_doc_same_value_sources():
    # Two different lines within the SAME document both yield the same value
    # for the same field (e.g. "Căn cước" line + "MSTTNCN" line both showing
    # the CCCD digits) -- these must collapse to one source per document
    # (highest confidence kept), not two, so the reviewer's "checked in N
    # documents" count reflects documents, not incidental duplicate lines.
    words_by_doc = {
        "bbnt": {0: [
            W("Căn", 10, 40, 25, 18), W("cước", 40, 40, 30, 18),
            *[W(d, 100 + i * 20, 40, 12, 18, conf=80) for i, d in enumerate("048091001309")],
            W("MSTTNCN", 10, 100, 70, 18), W(":", 85, 100, 10, 18),
            *[W(d, 120 + i * 15, 100, 12, 18, conf=97) for i, d in enumerate("048091001309")],
        ]},
    }
    fields = extract_fields(words_by_doc, {"cccd": "048091001309"})
    by_key = {f["key"]: f for f in fields}
    assert len(by_key["cccd"]["sources"]) == 1
    only = by_key["cccd"]["sources"][0]
    assert only["docId"] == "bbnt"
    assert only["value"] == "048091001309"
    assert abs(only["confidence"] - 0.97) < 1e-6  # kept the higher-confidence hit


def test_find_name_rejects_prose_anchor_mid_sentence():
    # "Bên Cung Ứng Dịch Vụ đồng ý rằng" -- Title Case anchor embedded in
    # ordinary prose, no colon/all-caps label context -> no source at all.
    lines = [[
        W("Bên", 10, 50, 25, 18), W("Cung", 40, 50, 35, 18), W("Ứng", 80, 50, 30, 18),
        W("Dịch", 115, 50, 30, 18), W("Vụ", 150, 50, 20, 18),
        W("đồng", 180, 50, 35, 18), W("ý", 220, 50, 15, 18), W("rằng", 240, 50, 30, 18),
    ]]
    assert find_name(lines, anchors=["ben cung ung dich vu"]) == []

def test_find_name_rejects_prose_anchor_followed_by_boilerplate_phrase():
    # Real false-positive pattern from the actual contract: two anchor-shaped
    # phrases back to back in Title Case, no label context. Even though the
    # trailing words are individually capitalized (name-shaped), the missing
    # label context must still reject this.
    lines = [[
        W("Bên", 10, 50, 25, 18), W("Cung", 40, 50, 35, 18), W("Ứng", 80, 50, 30, 18),
        W("Dịch", 115, 50, 30, 18), W("Vụ", 150, 50, 20, 18),
        W("Bên", 185, 50, 25, 18), W("Sử", 215, 50, 20, 18), W("Dụng", 240, 50, 35, 18),
        W("Dịch", 280, 50, 30, 18), W("Vụ", 315, 50, 20, 18),
    ]]
    assert find_name(lines, anchors=["ben cung ung dich vu"]) == []

def test_find_name_accepts_all_caps_signature_line():
    # Real pattern OCR'd from the contract: "BÊN CUNG ỨNG DỊCH VỤ Huỳnh Thị Thúy Phượng"
    lines = [[
        W("BÊN", 10, 160, 30, 18), W("CUNG", 45, 160, 40, 18), W("ỨNG", 90, 160, 35, 18),
        W("DỊCH", 130, 160, 35, 18), W("VỤ", 170, 160, 25, 18),
        W("Huỳnh", 210, 160, 50, 18), W("Thị", 265, 160, 30, 18),
        W("Thúy", 300, 160, 40, 18), W("Phượng", 345, 160, 55, 18),
    ]]
    hits = find_name(lines, anchors=["ben cung ung dich vu"])
    assert len(hits) == 1
    assert hits[0]["value"] == "Huỳnh Thị Thúy Phượng"
    assert hits[0]["bbox"]["x"] == 210

def test_find_name_accepts_colon_attached_to_anchor():
    lines = [[
        W("Bên", 10, 50, 25, 18), W("cung", 40, 50, 35, 18), W("ứng", 80, 50, 30, 18),
        W("dịch", 115, 50, 30, 18), W("vụ:", 150, 50, 25, 18),
        W("Trần", 190, 50, 30, 18), W("Văn", 225, 50, 30, 18), W("A", 260, 50, 15, 18),
    ]]
    hits = find_name(lines, anchors=["ben cung ung dich vu"])
    assert len(hits) == 1
    assert hits[0]["value"] == "Trần Văn A"

def test_find_name_accepts_standalone_colon_token():
    # "BÊN CUNG ỨNG DỊCH VỤ : Trần Văn A" -- colon as its own token, stripped
    # out of the value words.
    lines = [[
        W("BÊN", 10, 50, 25, 18), W("CUNG", 40, 50, 35, 18), W("ỨNG", 80, 50, 30, 18),
        W("DỊCH", 115, 50, 30, 18), W("VỤ", 150, 50, 20, 18), W(":", 175, 50, 10, 18),
        W("Trần", 190, 50, 30, 18), W("Văn", 225, 50, 30, 18), W("A", 260, 50, 15, 18),
    ]]
    hits = find_name(lines, anchors=["ben cung ung dich vu"])
    assert len(hits) == 1
    assert hits[0]["value"] == "Trần Văn A"

def test_find_name_dedupes_and_caps_at_three():
    def caps_line(y, given, conf):
        return [
            W("BÊN", 10, y, 30, 18), W("CUNG", 45, y, 40, 18), W("ỨNG", 90, y, 35, 18),
            W("DỊCH", 130, y, 35, 18), W("VỤ", 170, y, 25, 18),
        ] + [W(t, 210 + i * 40, y, 35, 18, conf=conf) for i, t in enumerate(given.split())]
    lines = [
        caps_line(50, "Trần Văn A", conf=95),
        caps_line(80, "Trần Văn A", conf=70),    # duplicate value, lower confidence -> dropped
        caps_line(110, "Nguyễn Thị B", conf=90),
        caps_line(140, "Lê Văn C", conf=85),
        caps_line(170, "Phạm Thị D", conf=80),   # 4th unique value -> beyond the cap, dropped
    ]
    hits = find_name(lines, anchors=["ben cung ung dich vu"])
    assert len(hits) == 3
    values = [h["value"] for h in hits]
    assert values.count("Trần Văn A") == 1
    assert "Phạm Thị D" not in values
    match = next(h for h in hits if h["value"] == "Trần Văn A")
    assert abs(match["confidence"] - 0.95) < 1e-9

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


# ---------------------------------------------------------------------------
# classify_page / segment_docs (document segmentation, #003)
# ---------------------------------------------------------------------------

def test_classify_page_contract():
    assert classify_page("Something HỢP ĐỒNG DỊCH VỤ something else on the cover") == \
        ("contract", "Hợp đồng dịch vụ")

def test_classify_page_bbnt():
    assert classify_page("BIÊN BẢN NGHIỆM THU công việc đã hoàn thành") == \
        ("bbnt", "Biên bản nghiệm thu")

def test_classify_page_bbnt_thanh_ly_synonym():
    # "thanh ly hop dong" is more specific than the generic "bien ban"
    # catch-all it's a substring-superset of, so it gets its own label --
    # real packets can contain both a "Biên bản nghiệm thu" AND a distinct
    # "Biên bản thanh lý hợp đồng" (sometimes combined into one title, as
    # below, wrapped across two short lines the way real OCR renders it,
    # with enough body lines below it that both title lines fall in the
    # top ~1/3 -- the real-world shape this pattern was found in).
    text = (
        "BIÊN BẢN\nNGHIỆM THU VÀ THANH LÝ HỢP ĐỒNG\n"
        "Được lập vào ngày 01/01/2026\ngiữa hai bên như sau\n"
        "Bên A và Bên B đồng ý\nký kết văn bản này"
    )
    assert classify_page(text) == ("bbnt", "Biên bản thanh lý hợp đồng")

def test_classify_page_commitment():
    assert classify_page("BẢN CAM KẾT không chịu thuế thu nhập cá nhân") == \
        ("commitment", "Bản cam kết")

def test_classify_page_phu_luc():
    assert classify_page("PHỤ LỤC đánh giá kết quả công việc") == ("pit", "Phụ lục")

def test_classify_page_tra_cuu():
    assert classify_page("BẢNG THÔNG TIN TRA CỨU người nộp thuế TNCN") == \
        ("pit", "Tra cứu thuế")

def test_classify_page_id_front():
    assert classify_page("CĂN CƯỚC CÔNG DÂN Số: 048091001309") == ("id_front", "CCCD")

def test_classify_page_body_text_returns_none():
    assert classify_page("Nội dung công việc thực hiện trong tháng theo bảng chấm công") is None

def test_classify_page_rejects_long_prose_mentioning_doc_name_in_passing():
    # Real false-positive found verifying against an actual packet: a
    # continuation page's body prose merely *references* the document's own
    # name mid-sentence ("...theo quy định tại Điều 2 của Biên Bản này, Hợp
    # Đồng sẽ được thanh lý hoàn toàn...") -- far too long a line to be a
    # title, so it must NOT classify (and so must stay a continuation page
    # of whatever document is already open, not start a false new one).
    text = (
        "Theo quy định tại Điều 2 của Biên Bản này, Hợp Đồng sẽ được thanh lý "
        "hoàn toàn và không bên nào còn nghĩa vụ gì thêm đối với bên còn lại"
    )
    assert classify_page(text) is None

def test_segment_docs_groups_consecutive_pages_by_title():
    docs = segment_docs([
        "HỢP ĐỒNG DỊCH VỤ..", "..body..", "..body..",
        "BIÊN BẢN NGHIỆM THU..", "..body..",
        "BẢN CAM KẾT..",
        "BẢNG THÔNG TIN TRA CỨU..",
    ])
    assert len(docs) == 4
    assert [d["pages"] for d in docs] == [[0, 1, 2], [3, 4], [5], [6]]
    assert [d["kind"] for d in docs] == ["contract", "bbnt", "commitment", "pit"]
    assert [d["label"] for d in docs] == [
        "Hợp đồng dịch vụ", "Biên bản nghiệm thu", "Bản cam kết", "Tra cứu thuế",
    ]

def test_segment_docs_merges_boilerplate_repeat_of_current_doc_title():
    # Real-packet regression: a 2nd page of the SAME "Biên bản nghiệm thu"
    # document that merely closes with boilerplate repeating the doc's own
    # name ("...biên bản này được lập thành 02 bản...") must NOT be treated
    # as a second document. Unlike the cover page, the phrase only appears
    # deep in the body (outside the top ~1/3) -- that's exactly the "weak"
    # signal that shouldn't be trusted to start a new same-kind/-label doc.
    # A later, genuinely different document (also only detectable outside
    # its own top ~1/3, e.g. a tax-lookup screenshot with banner chrome
    # above the results title) must still start its own new document.
    filler = [f"dòng nội dung công việc số {i}" for i in range(5)]
    pages = [
        "BIÊN BẢN NGHIỆM THU\n" + "\n".join(filler),
        "\n".join(
            ["Nội dung tiếp theo", "không có tiêu đề", "vẫn không có"] + filler +
            ["Biên bản này được lập thành 02 bản có giá trị như nhau"]
        ),
        "\n".join(
            ["Không liên quan", "chưa có tiêu đề", "vẫn chưa"] + filler +
            ["Bảng thông tin tra cứu người nộp thuế TNCN"]
        ),
    ]
    docs = segment_docs(pages)
    assert len(docs) == 2
    assert docs[0]["kind"] == "bbnt" and docs[0]["pages"] == [0, 1]
    assert docs[1]["kind"] == "pit" and docs[1]["pages"] == [2]


def test_segment_docs_first_page_unclassified_defaults_to_contract():
    docs = segment_docs([
        "Nội dung công việc thực hiện trong tháng theo bảng chấm công",
        "..body continues, no title on this page either..",
    ])
    assert len(docs) == 1
    assert docs[0]["kind"] == "contract"
    assert docs[0]["pages"] == [0, 1]


if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
