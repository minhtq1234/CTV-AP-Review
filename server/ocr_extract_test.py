from ocr_extract import (
    scale_words, group_lines, union_bbox, norm, find_in_lines, PATTERNS,
    extract_fields, build_manifest, find_name, FIELD_SPECS,
    classify_page, segment_docs, locate_field, _upright_rotation,
    ocr_words,
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


# ---------------------------------------------------------------------------
# locate_field (#004) -- one hit per anchor line, readable value OR a
# located-but-unread ("cần xem") hit, never neither and never dropped.
# ---------------------------------------------------------------------------

def test_locate_field_returns_value_when_pattern_matches():
    spec = {"anchors": ["ngay sinh"], "patterns": [PATTERNS["DATE"]]}
    lines = [[W("Ngày", 10, 50, 30, 18), W("sinh", 45, 50, 25, 18), W(":", 70, 50, 10, 18),
              W("24/04/1991", 85, 50, 90, 18, conf=88)]]
    hits = locate_field(lines, spec)
    assert len(hits) == 1
    assert hits[0]["value"] == "24/04/1991"
    assert abs(hits[0]["confidence"] - 0.88) < 1e-6
    assert hits[0]["bbox"]["width"] > 0

def test_locate_field_locates_unread_region_when_label_present_but_value_unreadable():
    # Handwritten date OCR'd as illegible (low-confidence) tokens: label is
    # there, nothing after it matches the DATE pattern -> "cần xem", pointing
    # at the VALUE slot -- geometrically right after the label's own right
    # edge (#005 follow-up), not at the whole line and not at nothing. No
    # next label on this line -> the bounded default-width slot, not a run
    # to end-of-line.
    spec = {"anchors": ["ngay sinh"], "patterns": [PATTERNS["DATE"]]}
    lines = [[W("Ngày", 10, 50, 30, 18), W("sinh", 45, 50, 25, 18), W(":", 70, 50, 10, 18),
              W("~~~~", 85, 50, 90, 18, conf=35)]]
    hits = locate_field(lines, spec)
    assert len(hits) == 1
    assert hits[0]["value"] == ""
    assert hits[0]["confidence"] == 0.0
    assert hits[0]["bbox"]["width"] > 0 and hits[0]["bbox"]["height"] > 0
    assert hits[0]["bbox"]["x"] == 74  # "sinh" right edge (45+25=70) + the small pad

def test_locate_field_falls_back_to_default_width_when_nothing_follows_on_line():
    # No next label at all on the line -> bounded default-width slot
    # starting right at the label's own right edge (+ pad), not a
    # zero-width box and not the label's own text re-highlighted.
    spec = {"anchors": ["ngay sinh"], "patterns": [PATTERNS["DATE"]]}
    lines = [[W("Ngày", 10, 50, 30, 18), W("sinh", 45, 50, 25, 18)]]
    hits = locate_field(lines, spec)
    assert len(hits) == 1
    assert hits[0]["value"] == ""
    assert hits[0]["confidence"] == 0.0
    assert hits[0]["bbox"]["x"] == 74
    assert hits[0]["bbox"]["width"] > 0

def test_locate_field_no_hit_when_label_absent():
    spec = {"anchors": ["ngay sinh"], "patterns": [PATTERNS["DATE"]]}
    lines = [[W("random", 10, 50, 40, 18, conf=90)]]
    assert locate_field(lines, spec) == []


# ---------------------------------------------------------------------------
# #005: on a multi-field line, the unread region must stop at the NEXT
# field's label -- not latch onto a stray token, not run to end-of-line.
# ---------------------------------------------------------------------------

def test_locate_field_unread_region_stops_before_next_label_cccd_then_ngay_cap():
    # Real-packet pattern: "Căn cước/Hộ chiếu số : <handwritten CCCD>  Ngày
    # cấp: 30/11/2022  Nơi cấp: ..." -- the cccd region must be the SLOT
    # between its own label's right edge and "Ngày cấp:", not the tiny "30"
    # token and not a box spanning all the way to "Nơi cấp".
    cccd_spec = next(s for s in FIELD_SPECS if s["key"] == "cccd")
    line = [
        W("Căn", 10, 700, 40, 30), W("cước", 55, 700, 50, 30),
        W("số", 110, 700, 30, 30), W(":", 145, 700, 10, 30),
        W("scribble1", 160, 700, 90, 30, conf=30), W("scribble2", 255, 700, 90, 30, conf=30),
        W("Ngày", 355, 700, 45, 30), W("cấp:", 405, 700, 45, 30),
        W("30", 460, 700, 25, 30), W("/11/2022", 490, 700, 90, 30),
        W("Nơi", 600, 700, 40, 30), W("cấp:", 645, 700, 45, 30), W("...", 695, 700, 40, 30),
    ]
    hits = locate_field([line], cccd_spec)
    assert len(hits) == 1
    h = hits[0]
    assert h["value"] == ""  # handwritten -- no CCCD pattern matched
    label_right = 55 + 50  # right edge of "cước", the anchor's last matched word
    assert h["bbox"]["x"] == label_right + 4  # starts at the label's own right edge (+ pad)
    end = h["bbox"]["x"] + h["bbox"]["width"]
    assert end == 355  # ends exactly at "Ngày" -- not the "30", not "Nơi"

def test_locate_field_unread_region_stops_before_next_label_dob_then_quoc_tich():
    # Real-packet pattern: "Ngày sinh : <handwritten DOB>  Quốc tịch: Việt
    # Nam" -- the ngaysinh region must stop before "Quốc tịch:", not spill
    # into the nationality text (the original #005 bug: 524px-wide box).
    ns_spec = next(s for s in FIELD_SPECS if s["key"] == "ngaysinh")
    line = [
        W("Ngày", 10, 656, 45, 30), W("sinh", 60, 656, 45, 30), W(":", 110, 656, 10, 30),
        W("scribbleDOB", 130, 656, 120, 30, conf=25),
        W("Quốc", 320, 656, 50, 30), W("tịch:", 375, 656, 55, 30),
        W("Việt", 440, 656, 45, 30), W("Nam", 490, 656, 40, 30),
    ]
    hits = locate_field([line], ns_spec)
    assert len(hits) == 1
    h = hits[0]
    assert h["value"] == ""
    label_right = 60 + 45  # right edge of "sinh", the anchor's last matched word
    assert h["bbox"]["x"] == label_right + 4
    end = h["bbox"]["x"] + h["bbox"]["width"]
    assert end == 320  # ends exactly at "Quốc" -- not "Việt Nam" too

def test_locate_field_unread_region_covers_gap_when_value_has_no_ocr_tokens():
    # #005 follow-up (caught live): the handwritten CCCD OCR'd to ZERO word
    # tokens at all (illegible enough that Tesseract found nothing there) --
    # the region must still be geometrically bounded to the gap between this
    # label's own right edge and the NEXT label's left edge. Computing the
    # region from "the next word token after the label" breaks here: with
    # zero value tokens, that next token literally IS "Ngày" (the next
    # field's own label), landing the box there instead of on the CCCD slot.
    cccd_spec = next(s for s in FIELD_SPECS if s["key"] == "cccd")
    line = [
        W("Căn", 10, 700, 40, 30), W("cước", 55, 700, 50, 30),
        W("số", 110, 700, 30, 30), W(":", 145, 700, 10, 30),
        # <-- no words at all here: the handwritten CCCD OCR'd to nothing -->
        W("Ngày", 355, 700, 45, 30), W("cấp:", 405, 700, 45, 30),
        W("30", 460, 700, 25, 30), W("/11/2022", 490, 700, 90, 30),
    ]
    hits = locate_field([line], cccd_spec)
    assert len(hits) == 1
    h = hits[0]
    assert h["value"] == ""
    label_right = 55 + 50
    assert h["bbox"]["x"] == label_right + 4  # starts at the label's right edge, NOT at "Ngày"
    end = h["bbox"]["x"] + h["bbox"]["width"]
    assert end == 355  # ends at "Ngày" -- covers the empty gap, doesn't land on the next label

def test_locate_field_works_with_real_mst_spec():
    mst_spec = next(s for s in FIELD_SPECS if s["key"] == "mst")
    digs = [W(d, 120 + i * 15, 50, 12, 18, conf=93) for i, d in enumerate("048091001309")]
    lines = [[W("MSTTNCN", 10, 50, 70, 18), W(":", 85, 50, 10, 18)] + digs]
    hits = locate_field(lines, mst_spec)
    assert len(hits) == 1 and hits[0]["value"] == "048091001309"

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
            # test_mst_field_ignores_bare_company_label. It must remain tax
            # evidence even when its digits happen to equal the CCCD below.
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

    # CCCD evidence comes only from an identity-card/passport label. The
    # matching MSTTNCN values remain separate tax evidence.
    assert by_key["cccd"]["expected"] == "048091001309"
    assert len(by_key["cccd"]["sources"]) == 1
    assert by_key["cccd"]["sources"][0]["docId"] == "bbnt"
    assert by_key["cccd"]["sources"][0]["value"] == "048091001309"

    # phi has no OCR hit anywhere -> single empty/low-confidence fallback source,
    # so it reads as an exception in the reviewer rather than silently vanishing.
    assert by_key["phi"]["expected"] == "10.000.000"
    assert len(by_key["phi"]["sources"]) == 1
    assert by_key["phi"]["sources"][0]["value"] == ""
    assert by_key["phi"]["sources"][0]["confidence"] == 0.0


def test_extract_fields_keeps_cccd_separate_from_same_value_msttncn():
    # The tax ID can equal the CCCD numerically, but a tax label is not CCCD
    # evidence and must not replace the lower-confidence identity-card hit.
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
    assert abs(only["confidence"] - 0.80) < 1e-6


def test_extract_fields_emits_unread_source_for_doc_with_label_but_no_readable_value():
    # #004: Ngày sinh appears on both the contract (handwritten -> illegible)
    # and the biên bản (typed -> readable). Both documents must get a
    # navigable source: the biên bản's read + verdictable, the contract's as
    # "cần xem" (empty value, region-after-label bbox, zero confidence) --
    # not silently dropped the way the old find_in_lines-only path did.
    words_by_doc = {
        "contract": {0: [
            W("Ngày", 10, 50, 30, 18), W("sinh", 45, 50, 25, 18), W(":", 70, 50, 10, 18),
            W("scribble", 85, 50, 90, 18, conf=35),
        ]},
        "bbnt": {0: [
            W("Ngày", 10, 40, 30, 18), W("sinh", 45, 40, 25, 18), W(":", 70, 40, 10, 18),
            W("24/04/1991", 85, 40, 90, 18, conf=88),
        ]},
    }
    fields = extract_fields(words_by_doc, {"ngaysinh": "24/04/1991"})
    by_key = {f["key"]: f for f in fields}
    ns = by_key["ngaysinh"]
    assert len(ns["sources"]) == 2
    by_doc = {s["docId"]: s for s in ns["sources"]}
    assert by_doc["bbnt"]["value"] == "24/04/1991"
    assert by_doc["bbnt"]["confidence"] > 0
    assert by_doc["contract"]["value"] == ""
    assert by_doc["contract"]["confidence"] == 0.0
    assert by_doc["contract"]["bbox"]["width"] > 0 and by_doc["contract"]["bbox"]["height"] > 0


def test_extract_fields_label_in_no_document_still_emits_single_cần_xem_source():
    # If a field's label appears in NO document at all, it must still show
    # up as one navigable-but-empty "cần xem" exception -- never silently
    # vanish from the manifest.
    words_by_doc = {"contract": {0: [W("random", 10, 50, 40, 18)]}}
    fields = extract_fields(words_by_doc, {"tk": "19001234567"})
    by_key = {f["key"]: f for f in fields}
    assert len(by_key["tk"]["sources"]) == 1
    assert by_key["tk"]["sources"][0]["value"] == ""
    assert by_key["tk"]["sources"][0]["confidence"] == 0.0


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

# ---------------------------------------------------------------------------
# #008: more name label variants, plus a scoped "cần xem" fallback when a
# labeled name occurrence is present but unreadable -- without flooding on
# ordinary prose mentions of the anchor phrase.
# ---------------------------------------------------------------------------

def test_find_name_matches_ten_toi_la_label():
    # Bản cam kết's own name label: "Tên tôi là : Trần Văn A".
    lines = [[
        W("Tên", 10, 50, 30, 18), W("tôi", 45, 50, 30, 18), W("là", 80, 50, 25, 18), W(":", 108, 50, 10, 18),
        W("Trần", 130, 50, 35, 18), W("Văn", 170, 50, 30, 18), W("A", 205, 50, 15, 18),
    ]]
    hits = find_name(lines, anchors=["ten toi la"])
    assert len(hits) == 1
    assert hits[0]["value"] == "Trần Văn A"

def test_find_name_matches_garbled_ten_label_missing_leading_letter():
    # Real-packet OCR artifact found verifying #008 on an actual scan:
    # Tesseract dropped the leading "T" of "Tên", reading the printed label
    # "Tên tôi là:" as "ên tối là:" -- the "en toi la" anchor variant still
    # catches it (still gated by the same labeled-context guard). The name
    # value itself was ALSO garbled ("lrần Ung Hy" -- doesn't start
    # uppercase), so this correctly falls to the "cần xem" unread branch
    # rather than reporting garbled text as if it were a confident read.
    hoten_spec = next(s for s in FIELD_SPECS if s["key"] == "hoten")
    lines = [[
        W("ên", 10, 50, 20, 18), W("tối", 40, 50, 30, 18), W("là:", 80, 50, 30, 18),
        W("lrần", 120, 50, 40, 18, conf=40), W("Ung", 165, 50, 35, 18, conf=40), W("Hy", 205, 50, 25, 18, conf=40),
    ]]
    hits = find_name(lines, anchors=hoten_spec["anchors"])
    assert len(hits) == 1
    assert hits[0]["value"] == ""  # garbled value doesn't pass the name-shape check
    assert hits[0]["confidence"] == 0.0

def test_find_name_locates_unread_value_on_labeled_line_without_flooding():
    # ALL-CAPS labeled context ("BÊN CUNG ỨNG DỊCH VỤ") but the handwritten
    # name OCR'd as illegible, non-name-shaped tokens -- must still produce
    # exactly ONE navigable "cần xem" source at the geometric value slot
    # (#008), reusing #005's label-right-edge -> next-label logic, instead of
    # silently dropping this document's name entirely.
    line = [
        W("BÊN", 10, 160, 30, 18), W("CUNG", 45, 160, 40, 18), W("ỨNG", 90, 160, 35, 18),
        W("DỊCH", 130, 160, 35, 18), W("VỤ", 170, 160, 25, 18),
        W("scribble1", 210, 160, 60, 18, conf=30), W("scribble2", 275, 160, 60, 18, conf=30),
    ]
    hits = find_name([line], anchors=["ben cung ung dich vu"])
    assert len(hits) == 1
    h = hits[0]
    assert h["value"] == ""
    assert h["confidence"] == 0.0
    label_right = 170 + 25  # right edge of "VỤ", the anchor's last matched word
    assert h["bbox"]["x"] == label_right + 4
    assert h["bbox"]["width"] > 0 and h["bbox"]["height"] > 0

def test_find_name_prose_mention_still_produces_no_source():
    # Guard against flooding (#008 must not regress this): a mixed-case,
    # non-labeled prose mention -- no colon, not ALL CAPS -- must produce NO
    # source at all, not even "cần xem". The labeled-context guard rejects it
    # before the unread fallback is ever considered (same guarantee as
    # test_find_name_rejects_prose_anchor_mid_sentence, restated here as the
    # explicit #008 regression check).
    lines = [[
        W("Bên", 10, 50, 25, 18), W("Cung", 40, 50, 35, 18), W("Ứng", 80, 50, 30, 18),
        W("Dịch", 115, 50, 30, 18), W("Vụ", 150, 50, 20, 18),
        W("đồng", 180, 50, 35, 18), W("ý", 220, 50, 15, 18), W("rằng", 240, 50, 30, 18),
    ]]
    assert find_name(lines, anchors=["ben cung ung dich vu"]) == []

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
    # #010: Phụ lục is its own "appendix" kind, not "pit" (it no longer
    # shares a kind with Tra cứu thuế).
    assert classify_page("PHỤ LỤC đánh giá kết quả công việc") == ("appendix", "Phụ lục")

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

# ---------------------------------------------------------------------------
# #009: cam-kết/tra-cứu detected via distinctive markers ANYWHERE on the
# page, when their title isn't a clean heading-shaped line -- without
# loosening the #003 guard for the ambiguous "biên bản"/"hợp đồng" titles.
# ---------------------------------------------------------------------------

def test_classify_page_tra_cuu_marker_anywhere_on_noisy_screenshot_page():
    # Real bug (#009): a tax-portal screenshot's identifying text is often
    # buried in banner/UI-chrome noise, not a clean short heading line --
    # this line is 17 words long, far past _TITLE_MAX_WORDS, so the existing
    # heading-shaped-line check alone would miss it entirely.
    text = (
        "some banner chrome misc noise here that is not a clean heading\n"
        "more noise from the browser toolbar rendering artifacts\n"
        "Thông tin về người nộp thuế TNCN hiển thị bên dưới đây cho quý khách tra cứu\n"
        "MST 0123456789 tên người nộp thuế ABC"
    )
    assert classify_page(text) == ("pit", "Tra cứu thuế")

def test_classify_page_cam_ket_marker_anywhere_via_form_number():
    # Real bug (#009): the cam-kết page's own "BẢN CAM KẾT" title sometimes
    # isn't picked up cleanly (OCR title-band noise); its printed form-number
    # header ("Mẫu số: 08/CK-TNCN") is a reliable, distinctive fallback.
    text = (
        "Mẫu số: 08/CK-TNCN\n"
        "(Ban hành kèm theo Thông tư số 60/2021/TT-BTC)\n"
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM"
    )
    assert classify_page(text) == ("commitment", "Bản cam kết")

def test_classify_page_still_rejects_long_prose_mentioning_bien_ban_after_009_fix():
    # #009 regression guard: relaxing tra-cứu/cam-kết detection must NOT
    # loosen the #003 guard for the ambiguous, frequently-repeated "biên
    # bản"/"hợp đồng" titles -- this long prose mention must still classify
    # to None (same text as test_classify_page_rejects_long_prose_mentioning_
    # doc_name_in_passing, re-asserted here as the explicit #009 check).
    text = (
        "Theo quy định tại Điều 2 của Biên Bản này, Hợp Đồng sẽ được thanh lý "
        "hoàn toàn và không bên nào còn nghĩa vụ gì thêm đối với bên còn lại"
    )
    assert classify_page(text) is None

def test_segment_docs_detects_cam_ket_and_tra_cuu_via_relaxed_full_page_markers():
    # Reproduces the real bug end-to-end: a packet whose cam-kết and
    # tra-cứu pages have no clean heading-shaped title line still segments
    # into 4 documents (not folding into the preceding Biên bản), while a
    # contract page's mid-prose mention of "Biên Bản"/"Hợp Đồng" still
    # doesn't start a false new document (#003 guard intact).
    pages = [
        "HỢP ĐỒNG DỊCH VỤ..",
        "Theo quy định tại Điều 2 của Biên Bản này, Hợp Đồng sẽ được thanh lý "
        "hoàn toàn và không bên nào còn nghĩa vụ gì thêm đối với bên còn lại",
        "BIÊN BẢN THANH LÝ HỢP ĐỒNG..",
        "Nội dung công việc thực hiện trong tháng theo bảng chấm công",
        # cam-kết page: no clean "BẢN CAM KẾT" heading, only its form-number header
        "Mẫu số: 08/CK-TNCN\n(Ban hành kèm theo Thông tư số 60/2021/TT-BTC)\n"
        "CỘNG HÒA XÃ HỘI CHỦ NGHĨA VIỆT NAM",
        # tax-lookup screenshot: identifying text buried in a long line, no short heading
        "một số dòng banner giao diện trình duyệt không liên quan ở phía trên đây\n"
        "Thông tin về người nộp thuế TNCN được hiển thị chi tiết ở bên dưới cho quý khách tra cứu",
    ]
    docs = segment_docs(pages)
    assert [d["kind"] for d in docs] == ["contract", "bbnt", "commitment", "pit"]
    assert [d["pages"] for d in docs] == [[0, 1], [2, 3], [4], [5]]


# ---------------------------------------------------------------------------
# #010: rotation-aware OCR -- pure upright-angle decision logic.
# ---------------------------------------------------------------------------

def test_upright_rotation_converts_osd_clockwise_angle_to_ccw_pil_angle():
    # Real rotated page found in production: OSD reports rotate=270 (rotate
    # 270° clockwise to fix) with confidence 9.94 -- verified against the
    # actual page that the correct PIL angle to apply is +90 CCW (reads
    # upright: img.rotate(90, expand=True)).
    assert _upright_rotation(270, 9.94) == 90
    assert _upright_rotation(90, 8.0) == 270
    assert _upright_rotation(180, 8.0) == 180

def test_upright_rotation_leaves_upright_pages_unrotated():
    # rotate=0 (OSD found nothing to fix) -> never rotate, regardless of
    # confidence -- real portrait pages report a wide range of confidences
    # (6-20 observed) alongside rotate=0.
    assert _upright_rotation(0, 15.36) == 0
    assert _upright_rotation(0, 0.0) == 0

def test_upright_rotation_never_rotates_on_low_confidence():
    # A low-confidence guess must NOT be acted on -- a wrongly-rotated
    # portrait page would be worse than the (already correct) status quo.
    assert _upright_rotation(90, 0.5) == 0
    assert _upright_rotation(270, 1.49) == 0

def test_upright_rotation_boundary_at_min_conf_threshold():
    assert _upright_rotation(90, 1.5) == 270    # exactly at the threshold -> acts
    assert _upright_rotation(90, 1.4999) == 0   # just under -> doesn't


# ---------------------------------------------------------------------------
# #010: Phụ lục (SOW/KPI appendix) classified as its own "appendix" kind,
# via the same relaxed full-page-marker mechanism #009 introduced (its
# title band is often still noisy even once the page OCRs upright).
# ---------------------------------------------------------------------------

def test_classify_page_appendix_via_sow_kpi_markers():
    text = (
        "một bảng nội dung công việc bị nhiễu không có tiêu đề gọn gàng nào cả\n"
        "PHỤ LỤC ĐÁNH GIÁ CHẤT LƯỢNG DỊCH VỤ CTV sản xuất nội dung SOW KPI theo tháng"
    )
    assert classify_page(text) == ("appendix", "Phụ lục")

def test_segment_docs_splits_out_appendix_from_bien_ban():
    # End-to-end reproduction of the real bug: a Phụ lục (now upright, but
    # with a noisy/garbled title band) still starts its own document, not
    # folding into the preceding Biên bản.
    pages = [
        "BIÊN BẢN THANH LÝ HỢP ĐỒNG..",
        "Nội dung công việc thực hiện trong tháng theo bảng chấm công",
        "một dòng nhiễu không liên quan ở phía trên đây không có tiêu đề\n"
        "PHỤ LỤC ĐÁNH GIÁ CHẤT LƯỢNG DỊCH VỤ CTV theo các chỉ tiêu SOW KPI đã thống nhất",
    ]
    docs = segment_docs(pages)
    assert [d["kind"] for d in docs] == ["bbnt", "appendix"]
    assert [d["pages"] for d in docs] == [[0, 1], [2]]


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


class TestTheContractTitleSurvivesOcr:
    """The July contract's first page really reads:

        Tài liệu Bảo mật
        VNG.HDK.CTV
        ĐÔNG
        HỢP DỊCH VỤ
        Số:

    Tesseract hoists `ĐỒNG` out of `HỢP ĐỒNG DỊCH VỤ` onto its own line, so the
    `hop dong dich vu` keyword never matches and every contract first page went
    unclassified. That is what put the splitter's packet boundaries three pages
    into each packet.
    """

    REAL_PAGE = "\n".join([
        "Tài liệu Bảo mật",
        "VỰNG HDKCTW",
        "ĐÔNG",
        "HỢP DỊCH VỤ",
        "Số:",
        "Đồng Đồng”)",
    ])

    def test_the_real_page_classifies_as_a_contract(self):
        assert classify_page(self.REAL_PAGE) == ("contract", "Hợp đồng dịch vụ")

    def test_the_intact_title_still_classifies(self):
        assert classify_page("HỢP ĐỒNG DỊCH VỤ\nSố: 01") \
            == ("contract", "Hợp đồng dịch vụ")

    def test_the_words_may_arrive_in_any_order(self):
        for title in ("ĐỒNG HỢP DỊCH VỤ", "DỊCH VỤ HỢP ĐỒNG", "HỢP DỊCH VỤ"):
            assert classify_page(f"{title}\nSố: 01") \
                == ("contract", "Hợp đồng dịch vụ"), title

    def test_a_liquidation_record_is_still_a_bbnt_not_a_contract(self):
        # "Biên bản thanh lý hợp đồng dịch vụ" contains every contract token.
        # The specific titles must keep winning.
        assert classify_page("BIÊN BẢN THANH LÝ HỢP ĐỒNG DỊCH VỤ")[0] == "bbnt"

    def test_an_acceptance_record_is_still_a_bbnt(self):
        assert classify_page("BIÊN BẢN NGHIỆM THU HỢP ĐỒNG DỊCH VỤ")[0] == "bbnt"

    def test_an_appendix_is_still_an_appendix(self):
        assert classify_page("PHỤ LỤC HỢP ĐỒNG DỊCH VỤ")[0] == "appendix"

    def test_body_prose_mentioning_the_words_is_not_a_title(self):
        prose = ("Hai bên đã thống nhất các điều khoản của hợp đồng dịch vụ "
                 "này và cam kết thực hiện đầy đủ nghĩa vụ của mình theo quy "
                 "định của pháp luật hiện hành có liên quan.")
        assert classify_page(prose) is None

    def test_a_mid_contract_page_is_still_a_continuation(self):
        """Page 12 of the real submission — the page the splitter mistook for a
        packet start. It must not classify, or it would start a document."""
        page = "\n".join([
            "Tài liệu Bảo mật",
            "ỰNG.HDK.CTV",
            "quyền Đồng",
            "Các và nghĩa khác theo định của Hợp và pháp luật liên",
            "vụ quy quan.",
            "ĐIÊU ĐIỀU KHOẢN",
        ])
        assert classify_page(page) is None


class TestTheTokenRuleStaysTitleShaped:
    """A token set is far looser than a phrase, so it needs a tighter shape
    test. These are real mid-contract lines from pages 11 and 19 of the July
    submission — nine words each, which slipped under the ten-word heading cap
    and split one contract into three."""

    PROSE = (
        "Trả cho Bên Cung Dịch Vụ theo định tại Hợp",
        "VNG được dứt Hợp này với Bên Cung Dịch vụ",
        "2 = tiền phí dịch Ứng Đồng; Trả cho Bên Cung Dịch Vụ theo định tại Hợp",
    )

    def test_mid_contract_prose_is_not_a_title(self):
        for line in self.PROSE:
            assert classify_page(f"Tài liệu Bảo mật\n{line}\nvụ quy") is None, line

    def test_the_real_mangled_titles_still_classify(self):
        for title in ("HỢP DỊCH VỤ", "ĐÔNG HỢP DỊCH VỤ", "HỢP ĐỒNG DỊCH VỤ"):
            assert classify_page(f"Tài liệu Bảo mật\n{title}\nSố:")[0] \
                == "contract", title

    def test_the_real_page_eleven_stays_a_continuation(self):
        page = "\n".join([
            "Tài liệu Bảo mật",
            "VNG.HDK.CTWƯ",
            "ĐIÊU QUYÈN VÀ NGHĨA CỦA",
            "3. VỤ VNG",
            "cấp Ứng cần thiết để",
            "Cung cho Bên Cung Dịch Vụ các thông tin, tài liệu thực hiện Dịch",
            "vụ;",
            "2 = tiền phí dịch Ứng Đồng;",
            "Trả cho Bên Cung Dịch Vụ theo định tại Hợp",
            "vụ quy",
        ])
        assert classify_page(page) is None


class TestOcrWordsBandCrop:
    """`band_frac` OCRs only the top fraction of a page. The boundary-snapping
    pass only needs to know whether a document *starts* here, and its title is
    at the top — measured at 355ms/page against 786ms for the whole page."""

    def test_the_default_is_the_whole_page(self):
        import inspect
        assert inspect.signature(ocr_words).parameters["band_frac"].default == 1.0

    def test_a_fraction_outside_the_range_is_refused(self):
        import pytest as _pytest
        for bad in (0.0, -0.5, 1.5):
            with _pytest.raises(ValueError):
                ocr_words("x.pdf", 0, band_frac=bad)


class TestADocumentIsWhatItSaysItIs:
    """A heading naming the document's own class beats a heading that merely
    cites another document. Page 45 of the PUBGm submission is a BBNT whose
    title OCR scrambled, and whose next line cites the contract:

        BIÊN BÁN NGHIỆM VÀ LÝ ĐÒNG
        THU THANH HỢP
        Căn cứ Hợp Đồng Dịch Vụ số đã ký

    The citation matched `hop dong dich vu` and the page classified as a
    contract — a false packet start, which put a two-page packet in the split.
    """

    #: Verbatim, all eleven lines — the citation has to land inside the top
    #: third for the bug to reproduce, which a shortened fixture hides.
    REAL_PAGE_45 = "\n".join([
        "BIÊN BÁN NGHIỆM VÀ LÝ ĐÒNG",
        "THU THANH HỢP",
        "Căn cứ Hợp Đồng Dịch Vụ số đã ký",
        "-_ ngày I1 tháng 06 năm 2026 (“Hợp",
        ".....................",
        "Đồng\");",
        "Căn cứ thực tế thực hiện Hợp Đồng.",
        "-_",
        "Hôm nay, ngày 23 tháng 06 năm 2026, chúng tôi gồm:",
        "CÔNG TY CÔ PHẢN TẬP ĐOÀN",
        "VNG",
    ])

    def test_the_real_page_is_a_bbnt_not_a_contract(self):
        assert classify_page(self.REAL_PAGE_45)[0] == "bbnt"

    def test_a_contract_citing_itself_is_still_a_contract(self):
        page = "\n".join([
            "Tài liệu Bảo mật",
            "VNG.HDK.CTV",
            "HỢP ĐỒNG DỊCH VỤ",
            "Số:",
        ])
        assert classify_page(page)[0] == "contract"

    def test_a_commitment_citing_the_contract_is_still_a_commitment(self):
        page = "BẢN CAM KẾT\nTheo Hợp Đồng Dịch Vụ số 01"
        assert classify_page(page)[0] == "commitment"

    def test_an_appendix_citing_the_contract_is_still_an_appendix(self):
        page = "PHỤ LỤC 01\nCăn cứ Hợp Đồng Dịch Vụ đã ký"
        assert classify_page(page)[0] == "appendix"

    def test_the_real_pubgm_contract_pages_are_unaffected(self):
        for title in ("HỢP ĐỎNG DỊCH VỤ", "HỢP ĐÔNG DỊCH VỤ", "HỢP ĐÒNG DỊCH VỤ"):
            page = f"Tài liệu Bảo mật\nVNG.HDK.CTV\n{title}\nSố:"
            assert classify_page(page)[0] == "contract", title
