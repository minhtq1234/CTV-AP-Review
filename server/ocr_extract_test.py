import inspect

import ocr_extract as oe
from ocr_extract import (
    scale_words, group_lines, union_bbox, norm, find_in_lines, PATTERNS,
    extract_fields, build_manifest, find_name, FIELD_SPECS,
    classify_page, segment_docs, locate_field, _upright_rotation,
    ocr_words,
    ocr_packet,
    _looks_like_heading, _FULL_PAGE_MARKERS,
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
# Per-spec lookahead. Default 1 keeps a value tied to its own label's line;
# `phi` widens to 3 because its anchor matches a section HEADING, not the
# clause -- see the `phi` entry in FIELD_SPECS for the measurement.
# ---------------------------------------------------------------------------

def _money_lines(gap_lines):
    """A heading line that carries the anchor, `gap_lines` junk lines, then the fee."""
    lines = [[W("ĐIỀU", 10, 50, 40, 18), W("2.", 55, 50, 20, 18),
              W("PHÍ", 80, 50, 30, 18), W("DỊCH", 115, 50, 35, 18),
              W("VỤ", 155, 50, 25, 18), W("VÀ", 185, 50, 20, 18),
              W("THANH", 210, 50, 50, 18), W("TOÁN", 265, 50, 45, 18)]]
    for i in range(gap_lines):
        lines.append([W("IÍ", 10, 80 + i * 30, 15, 18, conf=20)])
    lines.append([W("2.1.", 10, 80 + gap_lines * 30, 30, 18),
                  W("Phí", 45, 80 + gap_lines * 30, 25, 18),
                  W("dịch", 75, 80 + gap_lines * 30, 30, 18),
                  W("8.888.889", 110, 80 + gap_lines * 30, 90, 18, conf=84),
                  W("đồng.", 205, 80 + gap_lines * 30, 45, 18)])
    return lines

def test_locate_field_default_lookahead_is_one_line():
    # No `lookahead` key -> unchanged behaviour: a value two lines down is NOT
    # pulled in, so a value stays tied to its own label.
    spec = {"anchors": ["phi dich vu"], "patterns": [PATTERNS["MONEY"]]}
    hits = locate_field(_money_lines(1), spec)
    assert len(hits) == 1
    assert hits[0]["value"] == ""

def test_locate_field_default_lookahead_still_reads_the_immediately_next_line():
    spec = {"anchors": ["phi dich vu"], "patterns": [PATTERNS["MONEY"]]}
    hits = locate_field(_money_lines(0), spec)
    assert hits[0]["value"] == "8.888.889"

def test_locate_field_widened_lookahead_reaches_a_value_three_lines_down():
    # The real July shape: heading anchors, OCR fragments intervene, fee below.
    spec = {"anchors": ["phi dich vu"], "patterns": [PATTERNS["MONEY"]], "lookahead": 3}
    for gap in (0, 1, 2):
        hits = locate_field(_money_lines(gap), spec)
        assert hits[0]["value"] == "8.888.889", f"gap={gap}"
        assert abs(hits[0]["confidence"] - 0.84) < 1e-6

def test_locate_field_lookahead_does_not_reach_past_its_window():
    # 3 junk lines puts the fee 4 lines down -- outside the window, so the hit
    # stays "cần xem" rather than silently scanning the rest of the page.
    spec = {"anchors": ["phi dich vu"], "patterns": [PATTERNS["MONEY"]], "lookahead": 3}
    hits = locate_field(_money_lines(3), spec)
    assert hits[0]["value"] == ""

def test_locate_field_lookahead_takes_the_nearest_match():
    # Two candidate values in the window: the closer one wins, so widening the
    # window never pulls a further value in ahead of a nearer one.
    spec = {"anchors": ["phi dich vu"], "patterns": [PATTERNS["MONEY"]], "lookahead": 3}
    lines = [
        [W("Phí", 10, 50, 25, 18), W("dịch", 40, 50, 30, 18), W("vụ:", 75, 50, 25, 18)],
        [W("1.000.000", 10, 80, 90, 18, conf=80)],
        [W("2.000.000", 10, 110, 90, 18, conf=90)],
    ]
    assert locate_field(lines, spec)[0]["value"] == "1.000.000"

def test_only_phi_widens_its_lookahead():
    # A broad pattern must not get slack: ACCOUNT is \d{6,16}, so three lines
    # of it would let `tk` capture a CCCD or MST from a neighbouring row --
    # the read count would stay high while the values silently went wrong.
    widened = {s["key"]: s.get("lookahead") for s in FIELD_SPECS if s.get("lookahead")}
    assert widened == {"phi": 3}


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
    # #012: was a single mixed-case line ("Something HỢP ĐỒNG DỊCH VỤ
    # something else on the cover") -- no real cover in this corpus ever
    # renders its title inline inside a lowercase sentence like that; every
    # real title is its own clean line, which is what `_looks_like_heading`
    # now requires. Reshaped to the two-line form real covers actually take
    # (title alone on its line, unrelated text on another) while keeping the
    # original intent: the title is found alongside other page content.
    assert classify_page("Something else on the cover\nHỢP ĐỒNG DỊCH VỤ") == \
        ("contract", "Hợp đồng dịch vụ")

def test_classify_page_bbnt():
    # #012: reshaped for the same reason as test_classify_page_contract --
    # the title now needs its own line, not to be embedded in lowercase
    # prose on the same line as the keyword.
    assert classify_page("BIÊN BẢN NGHIỆM THU\ncông việc đã hoàn thành") == \
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
    # #012: this mixed-case single line no longer matches via the
    # heading-shaped pass ("không chịu thuế thu nhập cá nhân" is ordinary
    # lowercase prose sharing the line) -- it still passes only because
    # "ban cam ket" is also one of `_FULL_PAGE_MARKERS`'s commitment
    # markers, which is case/shape-unrestricted by design (#009). Left as a
    # single line deliberately: it now doubles as coverage that the
    # unrestricted marker fallback still catches this text.
    assert classify_page("BẢN CAM KẾT không chịu thuế thu nhập cá nhân") == \
        ("commitment", "Bản cam kết")

def test_classify_page_phu_luc():
    # #010: Phụ lục is its own "appendix" kind, not "pit" (it no longer
    # shares a kind with Tra cứu thuế).
    # #012: reshaped to a two-line form (see test_classify_page_contract) --
    # the single mixed-case line this used to be has no full-page-marker
    # fallback for this exact wording ("đánh giá kết quả công việc" doesn't
    # match the marker's "đánh giá chất lượng dịch vụ"), so unlike
    # commitment/tra_cuu above this one is a genuine change in how the
    # title must be shaped, not just an incidental pass via the fallback.
    assert classify_page("PHỤ LỤC\nđánh giá kết quả công việc") == ("appendix", "Phụ lục")

def test_classify_page_tra_cuu():
    # #012: still passes, but now only via `_FULL_PAGE_MARKERS`'s
    # "bang thong tin tra cuu" (case/shape-unrestricted, #009) rather than
    # the heading-shaped pass -- same situation as test_classify_page_commitment.
    assert classify_page("BẢNG THÔNG TIN TRA CỨU người nộp thuế TNCN") == \
        ("pit", "Tra cứu thuế")

def test_classify_page_id_front():
    # #012: reshaped to a two-line form (see test_classify_page_contract) --
    # id_front has no `_FULL_PAGE_MARKERS` entry at all, so unlike
    # commitment/tra_cuu above there is no fallback and the title must be on
    # its own heading-shaped line, exactly as a real CCCD page's "Số:" field
    # already sits on its own line below the heading elsewhere in this file
    # (e.g. "HỢP ĐỒNG DỊCH VỤ\nSố: 01" in TestTheContractTitleSurvivesOcr).
    assert classify_page("CĂN CƯỚC CÔNG DÂN\nSố: 048091001309") == ("id_front", "CCCD")

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


# ---------------------------------------------------------------------------
# #012: a `_title_candidates` string additionally has to look like a printed
# heading (`_looks_like_heading`, i.e. full caps), not just be short. Found
# by measuring real packets: `_TITLE_MAX_WORDS`'s 10-word cap alone let a
# short OCR-line-wrapped fragment of ordinary contract prose pass as a
# "title" purely because a numbered clause happened to wrap onto a short
# line. Real, page-structure counts across the two production cases this was
# measured against (68ddc1f0, 41 packets; f5e7be63, 32 packets): 23/41 and
# 3/32 packets carried a spurious duplicate document from exactly this gap
# before the fix, 0/41 and 0/32 after, with zero packets losing a genuine
# document.
# ---------------------------------------------------------------------------

def test_looks_like_heading_rejects_real_ocr_prose_fragments():
    # Both fragments below are copied verbatim from real Tesseract output
    # (July case `68ddc1f0`) that mis-started a document before this fix --
    # not invented text. Both are short enough to pass `_TITLE_MAX_WORDS`
    # and both contain a document keyword ("nghiệm thu", "biên bản") as an
    # ordinary defined-term mention, not a title.
    assert not _looks_like_heading("của Hợp Đồng và được VNG ý nghiệm thu. Trong")  # packet 35, p1
    assert not _looks_like_heading("quy 2 của Biên Bản này, Hợp sẽ")                # packet 9, p5

def test_looks_like_heading_accepts_real_titles():
    # Real titles from the same case, including OCR noise (mangled diacritics,
    # a trailing colon, digits) that must not defeat the check.
    for title in ("HỢP ĐÒNG DỊCH VỤ", "NGHIỆM THU VÀ THANH LÝ HỢP ĐỎNG",
                  "BẲNG THÔNG TIN TRA CỨU:", "PHỤ LỤC ĐÁNH GIÁ CHÁT LƯỢNG DỊCH VỤ"):
        assert _looks_like_heading(title), title

def test_classify_page_rejects_short_prose_fragment_mentioning_nghiem_thu():
    # Real bug: this exact fragment (packet 35, p1 -- the contract's own
    # Điều 2 payment clause, conditioned on VNG's acceptance of the work)
    # used to classify as a fresh "Biên bản nghiệm thu", truncating the
    # contract to its cover page alone.
    assert classify_page("của Hợp Đồng và được VNG ý nghiệm thu. Trong") is None

def test_classify_page_rejects_short_prose_fragment_mentioning_bien_ban():
    # Real bug: this fragment (packet 9, p5 -- a contract general-terms
    # clause self-referencing "Biên Bản này") used to hit the generic
    # "bien ban" catch-all and split one real 2-page BBNT into two documents,
    # because the catch-all always emits the "Biên bản nghiệm thu" label --
    # which never matches whichever bbnt label is actually open, so
    # `segment_docs`'s same-label continuation guard never engages.
    assert classify_page("quy 2 của Biên Bản này, Hợp sẽ") is None

def test_classify_page_still_accepts_all_caps_titles_at_the_shape_boundary():
    # The gate must not just reject prose -- real titles, including ones
    # OCR already mangles, still have to classify.
    assert classify_page("HỢP ĐÒNG DỊCH VỤ") == ("contract", "Hợp đồng dịch vụ")
    assert classify_page("NGHIỆM THU VÀ THANH LÝ HỢP ĐỎNG") == \
        ("bbnt", "Biên bản thanh lý hợp đồng")

def test_segment_docs_does_not_split_contract_on_its_own_nghiem_thu_clause():
    # End-to-end reproduction of the real bug (packet 35 shape): a 4-page
    # contract whose 2nd page contains the real "nghiệm thu" prose fragment
    # above must stay one document, not fork a spurious "bbnt" at page 1.
    pages = [
        "HỢP ĐÒNG DỊCH VỤ",
        "của Hợp Đồng và được VNG ý nghiệm thu. Trong",
        "..body continues..",
        "..body continues..",
        "NGHIỆM THU VÀ THANH LÝ HỢP ĐỎNG",
        "..body continues..",
    ]
    docs = segment_docs(pages)
    assert [d["kind"] for d in docs] == ["contract", "bbnt"]
    assert [d["pages"] for d in docs] == [[0, 1, 2, 3], [4, 5]]

def test_full_page_markers_no_longer_carry_the_generic_boilerplate_phrases():
    # Pins #012's marker trim: "co quan thue" (pit) and "phu luc" (appendix)
    # are gone -- both are ordinary contract boilerplate ("...trích nộp cho
    # Cơ quan Thuế...", "...cụ thể tại Phụ lục đính kèm.") that a real
    # `_FULL_PAGE_MARKERS` pass (unrestricted by line shape/case) would
    # otherwise match on the contract body itself. The other markers in each
    # group -- kept because every genuine case in the July/February audit
    # was still caught by at least one of them -- must still be present.
    by_kind = {kind: markers for markers, kind, _ in _FULL_PAGE_MARKERS}
    assert "co quan thue" not in by_kind["pit"]
    assert "phu luc" not in by_kind["appendix"]
    assert {"bang thong tin tra cuu", "thong tin ve nguoi nop thue", "gdt.gov.vn"} <= set(by_kind["pit"])
    assert {"danh gia chat luong dich vu", "sow", "kpi"} <= set(by_kind["appendix"])


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


class TestALabelAndItsValueOnOneVisualRow:
    """`group_lines` clusters by the first word's y, so a wide row with slight
    vertical jitter splits into fragments — and the fragment holding the value
    can sort *before* the one holding the label. Page 251 of the July
    submission is exactly this: the CCCD row came out as six lines, with the
    number two lines above its own label.

        line 44  y=1785..1829  x=814   '060203014847 Ngày'
        line 45  y=1794..1800  x=556   ','
        line 46  y=1804..1841  x=391   'CCCD sô :'

    `locate_field` only looked one line forward, so the packet's CCCD was never
    read and it matched no roster row at all.
    """

    def _row(self):
        def w(text, x, y, h):
            return {"text": text, "x": x, "y": y, "w": len(text) * 18,
                    "h": h, "conf": 95.0}
        return [
            [w("Nơicấp:", 1696, 1759, 50), w("QLNHC", 1810, 1759, 50)],
            [w("câp:", 1275, 1774, 50), w("15/04/2022", 1350, 1774, 50)],
            [w("060203014847", 814, 1785, 44), w("Ngày", 1000, 1785, 44)],
            [w(",", 556, 1794, 6)],
            [w("CCCD", 391, 1804, 37), w("sô", 470, 1804, 37),
             w(":", 500, 1804, 37)],
            [w("TTIXH", 1914, 1819, 35)],
        ]

    SPEC = {"key": "cccd", "anchors": ["cccd so"],
            "patterns": [r"\d(?:\s*\d){8,12}", r"\d{10,13}"]}

    def test_the_value_is_found_though_it_sorted_above_the_label(self):
        hits = locate_field(self._row(), self.SPEC)

        assert len(hits) == 1
        assert hits[0]["value"] == "060203014847"
        assert hits[0]["confidence"] > 0

    def test_it_marks_where_the_value_is_not_where_the_label_is(self):
        hits = locate_field(self._row(), self.SPEC)
        assert hits[0]["bbox"]["x"] == 814

    def test_a_value_on_the_label_s_own_line_still_wins(self):
        def w(text, x):
            return {"text": text, "x": x, "y": 100, "w": len(text) * 18,
                    "h": 40, "conf": 95.0}
        lines = [[w("CCCD", 100), w("sô:", 180), w("079203031329", 260)],
                 [w("060203014847", 260)]]

        hits = locate_field(lines, self.SPEC)

        assert hits[0]["value"] == "079203031329"

    def test_a_row_far_above_is_not_borrowed_from(self):
        def w(text, x, y):
            return {"text": text, "x": x, "y": y, "w": len(text) * 18,
                    "h": 40, "conf": 95.0}
        lines = [[w("060203014847", 800, 100)],          # a different row
                 [w("CCCD", 391, 900), w("sô:", 470, 900)]]

        hits = locate_field(lines, self.SPEC)

        assert hits[0]["value"] == ""                     # located, unread
        assert hits[0]["confidence"] == 0.0

    def test_the_next_line_lookahead_still_works(self):
        def w(text, x, y):
            return {"text": text, "x": x, "y": y, "w": len(text) * 18,
                    "h": 40, "conf": 95.0}
        lines = [[w("CCCD", 391, 100), w("sô:", 470, 100)],
                 [w("060203014847", 391, 160)]]          # the row below

        hits = locate_field(lines, self.SPEC)

        assert hits[0]["value"] == "060203014847"


class TestTheIdentityCarriesTheMst:
    """`match_roster` tries the personal MST between the CCCD and the name, so
    `ocr_packet` has to hand it over. On the July packet that matched nothing the
    number reads at 0.95 under `mst` while the CCCD label was lost to line
    grouping."""

    def test_the_identity_keys(self):
        import inspect
        source = inspect.getsource(ocr_packet)
        assert '"mst": _best_value(by_key["mst"])' in source

    def test_best_value_takes_the_most_confident_read(self):
        field = {"sources": [
            {"value": "", "confidence": 0.0},
            {"value": "060203014847", "confidence": 0.95},
            {"value": "999999999999", "confidence": 0.4},
        ]}
        from ocr_extract import _best_value
        assert _best_value(field) == "060203014847"


# ---------------------------------------------------------------------------
# #011: two-column party blocks -- which of a signature/contact block's two
# "Họ và tên:" names is the CTV's (the one the roster names) and which is
# VNG's own signatory. Every coordinate below is MEASURED off the real July
# batch page named in the test, in display space (150 dpi, 1241px wide), so a
# failure here is a failure against the actual scans.
# ---------------------------------------------------------------------------

HOTEN_ANCHORS = next(s for s in FIELD_SPECS if s["key"] == "hoten")["anchors"]


def _vng_and_ctv_header_row(y=616):
    """The block's own column header, exactly as abs page 82 OCRs it: the left
    (VNG) header survives ONLY as the bare logo word 'VNG' at x=232..278 --
    "BÊN SỬ DỤNG DỊCH VỤ" is gone, on this page and on abs 247/275 too -- with
    'Bên Cung Ứng Dịch Vụ' (x=660..884) right of a 382px word-free band. That
    is why the party divide is derived from the ONE header that survives plus
    the band, and not from finding both headers.
    """
    return [
        W("VNG", 232, y, 46, 16, conf=92),
        W("Bên", 660, y + 6, 36, 16), W("Cung", 704, y + 7, 51, 20),
        W("Ứng", 761, y + 3, 40, 26), W("Dịch", 808, y + 8, 44, 20),
        W("Vụ", 858, y + 10, 26, 20),
    ]


def _email_and_phone_rows(y=725):
    """The two rows below the names on all three failing pages -- email and
    phone -- both split across the same two columns. `_MIN_COLUMN_ROWS` needs
    two such rows before a header row counts as a real two-column block, so a
    single OCR-thinned prose line can't masquerade as one.
    """
    return [
        [W("Email:", 230, y, 58, 16), W("anhtlh@)vng.com.vn", 296, y, 210, 21, conf=70),
         W("Email:", 659, y, 58, 17), W("kienphatnhan(@)gmail.com", 725, y, 236, 22, conf=60)],
        [W("Số", 230, y + 52, 26, 16), W("điện", 262, y + 52, 40, 16),
         W("thoại:", 308, y + 52, 52, 20), W("0902428933", 370, y + 52, 120, 18),
         W("Số", 659, y + 52, 26, 16), W("điện", 691, y + 52, 40, 16),
         W("thoại:", 737, y + 52, 52, 20), W("0905209809", 799, y + 52, 120, 18)],
    ]


def _p82_name_lines():
    """abs page 82's two name lines. `group_lines` keeps them apart (it
    baselines on the first word's y) but they are ONE visual row: y-spans
    671..694 and 680..701 overlap by 14 of the shorter's 21px.
    """
    return [
        [W("Họ", 231, 675, 25, 18, conf=95), W("và", 263, 675, 20, 16), W("tên:", 290, 676, 30, 16),
         W("Trần", 330, 671, 40, 20, conf=96), W("Lê", 378, 677, 22, 16, conf=96),
         W("Hoài", 407, 677, 42, 16, conf=96), W("Anh", 456, 678, 38, 16, conf=96)],
        [W("Họ", 659, 682, 26, 19), W("và", 692, 682, 20, 16), W("tên:", 720, 682, 32, 16),
         W("Nhan", 758, 683, 48, 16, conf=96), W("Kiến", 813, 680, 44, 20, conf=96),
         W("Phát", 862, 684, 40, 16, conf=96)],
    ]


def test_find_name_prefers_ctv_column_over_vng_signatory():
    # abs page 82 (packet 9's contract; roster name 'Nhan Kiến Phát'). Both
    # columns print "Họ và tên:" and both read at 0.96, so confidence cannot
    # tell the parties apart -- VNG's 'Trần Lê Hoài Anh' used to win and the
    # packet was reported as a name mismatch, i.e. "cần gửi lại" on valid
    # paperwork. The page's own column header is the evidence that decides.
    lines = [_vng_and_ctv_header_row(), *_p82_name_lines(), *_email_and_phone_rows()]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert len(hits) == 1
    assert hits[0]["value"] == "Nhan Kiến Phát"
    assert hits[0]["rank"] == 1               # party-certain: the page said so
    assert hits[0]["bbox"]["x"] == 758        # the loupe points at the CTV's own words
    # VNG's signatory is not evidence about the CTV: it is not a source at all.
    assert all("Trần" not in h["value"] for h in hits)


def test_find_name_ignores_vng_column_name_at_higher_confidence():
    # abs page 247 (packet 31; roster name 'Phan Tấn Tài'). Measured minimum
    # word confidences: VNG's 'Trịnh Đức Minh' 0.94, the CTV's 'Phan Tắn Tài'
    # 0.85 -- so the CORRECT read is the LESS legible one. Confidence is
    # legibility, not correctness; if anyone reintroduces a confidence gate to
    # choose between the parties, this test fails.
    lines = [
        [W("Bên", 642, 626, 36, 16), W("Cung", 686, 625, 50, 20), W("Ứng", 742, 620, 40, 24),
         W("Dịch", 790, 624, 44, 20), W("Vụ", 840, 624, 26, 20)],
        [W("VNG", 236, 630, 48, 16, conf=92)],
        [W("Họ", 643, 686, 26, 18), W("và", 676, 684, 20, 16), W("tên:", 703, 684, 32, 16),
         W("Phan", 742, 684, 44, 16, conf=93), W("Tắn", 792, 678, 34, 20, conf=85),
         W("Tài", 833, 682, 28, 16, conf=97)],
        [W("Họ", 238, 690, 25, 18, conf=55), W("và", 271, 689, 19, 16), W("tên:", 297, 690, 32, 15),
         W("Trịnh", 336, 688, 50, 20, conf=96), W("Đức", 393, 688, 38, 16, conf=94),
         W("Minh", 437, 687, 47, 16, conf=96)],
        [W("Email:", 238, 740, 58, 16), W("minhtd4)vng.com.vn", 304, 738, 202, 21, conf=70),
         W("Email:", 644, 734, 58, 17), W("taiwan1903w(0gmail.com", 710, 732, 236, 22, conf=12)],
        [W("Số", 238, 792, 26, 16), W("điện", 270, 792, 40, 16), W("thoại:", 316, 792, 52, 20),
         W("0912260033", 378, 792, 120, 18), W("Số", 644, 792, 26, 16),
         W("điện", 676, 792, 40, 16), W("thoại:", 722, 792, 52, 20),
         W("0328615668", 784, 792, 120, 18)],
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert len(hits) == 1
    # 'Tắn' is what OCR reads (the roster has 'Tấn'); compare_values folds
    # accents to a FUZZY -> "cần xem", which is a cleared false `no`, not a
    # match. What this test pins is which PARTY's words get published.
    assert hits[0]["value"] == "Phan Tắn Tài"
    assert abs(hits[0]["confidence"] - 0.85) < 1e-9
    assert all("Trịnh" not in h["value"] for h in hits)


def test_find_name_merged_columns_publish_the_ctv_column_not_the_splice():
    # abs page 275 (packet 35; roster name 'Hoàng Nguyễn Hải Đăng'). Here
    # `group_lines` interleaved the two columns: one fragment holds 'Trần'
    # (x=338) 'Tiến' (x=430) and the RIGHT column's 'và tên:' + name, the
    # other holds the left 'Họ và tên:', 'Văn' (x=387) and the right column's
    # 'Họ' (x=670). The old read was the splice 'Họ và tên: Văn Họ' -- one
    # party's middle name token plus the first word of the OTHER column's
    # label -- published at 0.96 as if it were a name.
    # The header row carries two low-confidence specks ('+}' at 43 beside the
    # header, '|' at 26 past its end); dropping them is what lets the row
    # qualify at all.
    lines = [
        [W("+}", 646, 634, 24, 39, conf=43), W("Bên", 668, 633, 36, 16),
         W("Cung", 712, 633, 51, 20), W("Ứng", 770, 627, 40, 25),
         W("Dịch", 816, 632, 44, 20), W("Vụ", 866, 630, 28, 20)],
        [W("VNG", 236, 637, 50, 25, conf=91), W("|", 1087, 640, 16, 19, conf=26)],
        [W("Trần", 338, 692, 42, 21, conf=96), W("Tiến", 430, 692, 40, 20, conf=96),
         W("và", 702, 692, 21, 16), W("tên:", 730, 692, 31, 16),
         W("Hoàng", 770, 690, 61, 20, conf=96), W("Nguyễn", 837, 684, 75, 26, conf=96),
         W("Hải", 920, 688, 32, 17, conf=96), W("Đăng", 958, 688, 50, 20, conf=90)],
        [W("Họ", 240, 699, 25, 18, conf=94), W("và", 273, 698, 20, 16),
         W("tên:", 300, 698, 30, 15), W("Văn", 387, 696, 38, 16, conf=96),
         W("Họ", 670, 693, 26, 18, conf=96)],
        [W("Email:", 240, 747, 58, 16), W("tientv(0)vng.com.vn", 306, 747, 178, 20, conf=40),
         W("Email:", 670, 742, 58, 17), W("đdanghnh(2gmail.com", 737, 739, 202, 22, conf=28)],
        [W("Số", 240, 800, 26, 16), W("điện", 272, 800, 40, 16), W("thoại:", 318, 800, 52, 20),
         W("0909924678", 380, 800, 120, 18), W("Số", 670, 800, 26, 16),
         W("điện", 702, 800, 40, 16), W("thoại:", 748, 800, 52, 20),
         W("0933179569", 810, 800, 120, 18)],
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    # The spliced value must never be published: `_person_verdict` would make
    # it an outright MISMATCH -> `no` -> "cần gửi lại".
    assert all("Văn Họ" not in h["value"] for h in hits)
    readable = [h for h in hits if h["value"]]
    # The CTV's own name exists only on the REASSEMBLED row (its label's words
    # are spread across both fragments), and the divide places it in the CTV's
    # column, so it is read rather than downgraded to "cần xem".
    assert [h["value"] for h in readable] == ["Hoàng Nguyễn Hải Đăng"]
    assert readable[0]["bbox"]["x"] == 770


def test_find_name_without_party_headers_keeps_current_behaviour():
    # The same two name lines with NO column header above them: there is no
    # party evidence on the page, so nothing is classified and both names are
    # still returned exactly as before, the higher-confidence one winning in
    # `_best_hit`. A deliberate no-fix -- not a bug for a later reader to
    # "tidy up" by guessing from column position, which is how VNG's name
    # would get published on a parties-swapped page.
    lines = _p82_name_lines()
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert sorted(h["value"] for h in hits) == ["Nhan Kiến Phát", "Trần Lê Hoài Anh"]
    assert all(h["rank"] == 0 for h in hits)


def test_find_name_single_column_ho_va_ten_unaffected():
    # The common non-signature page (a cam kết / contact block with one
    # column): one "Họ và tên:", no header row, unchanged single readable hit.
    lines = [[
        W("Họ", 231, 300, 25, 18), W("và", 263, 300, 20, 16), W("tên:", 290, 300, 30, 16),
        W("Trần", 330, 300, 40, 20), W("Văn", 378, 300, 38, 16), W("A", 424, 300, 15, 16),
    ]]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert len(hits) == 1 and hits[0]["value"] == "Trần Văn A"


def test_find_name_ignores_a_name_above_the_detected_block():
    # A left-aligned single-column "Họ và tên: <the CTV>" ABOVE the block (the
    # party-B contact block does appear on its own higher up on some contract
    # pages) must not be classified -- and so not dropped -- by a divide that
    # only describes the rows inside the block. The block's y-range is what
    # scopes it.
    lines = [
        [W("Họ", 231, 300, 25, 18), W("và", 263, 300, 20, 16), W("tên:", 290, 300, 30, 16),
         W("Nhan", 330, 300, 48, 16, conf=91), W("Kiến", 385, 300, 44, 20, conf=91),
         W("Phát", 434, 300, 40, 16, conf=91)],
        _vng_and_ctv_header_row(), *_p82_name_lines(), *_email_and_phone_rows(),
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    values = sorted(h["value"] for h in hits)
    assert values == ["Nhan Kiến Phát"]      # deduped: same value, one source
    assert all("Trần" not in h["value"] for h in hits)


def test_find_name_row_reassembly_completes_a_split_name():
    # abs page 85 (packet 9's biên bản). `_row_words` reassembles
    # 'BÊN CUNG ỨNG DỊCH VỤ : Nhan Kiến Phát' from two `group_lines`
    # fragments: the standalone ':' (x=512, y=684) and 'Phát' (x=648) sort into
    # a DIFFERENT fragment than the label and 'Nhan Kiến'. Reading the line
    # alone gave 'Nhan Kiến', and `compare_values._person_verdict` makes a
    # differing token count an outright MISMATCH -- so packet 9 stayed `no`
    # even once its contract page read the right party.
    lines = [
        [W("BÊN", 196, 671, 46, 22, conf=88), W("CUNG", 251, 676, 67, 16, conf=93),
         W("ỨNG", 326, 672, 52, 22, conf=91), W("DỊCH", 385, 678, 60, 20, conf=95),
         W("VỤ", 453, 678, 32, 21, conf=83),
         W("Nhan", 534, 679, 52, 16, conf=96), W("Kiến", 594, 674, 47, 22, conf=96)],
        [W(":", 512, 684, 2, 10, conf=91), W("Phát", 648, 680, 46, 16, conf=96)],
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert len(hits) == 1
    assert hits[0]["value"] == "Nhan Kiến Phát"


def test_find_name_row_reassembly_only_extends_a_prefix():
    # The extension is a STRICT prefix extension or nothing: here the row
    # holds a different value beside the label (a second, unlabeled fragment
    # that does not continue the read), so the line's own value survives
    # untouched rather than being replaced by whatever else shares the row.
    lines = [
        [W("BÊN", 196, 671, 46, 22), W("CUNG", 251, 671, 67, 16), W("ỨNG", 326, 671, 52, 22),
         W("DỊCH", 385, 671, 60, 20), W("VỤ", 453, 671, 32, 21),
         W("Nhan", 534, 671, 52, 16), W("Kiến", 594, 671, 47, 22)],
        [W("Phạm", 300, 676, 50, 16), W("Thị", 360, 676, 30, 16)],
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert [h["value"] for h in hits] == ["Nhan Kiến"]


def test_find_name_extension_never_swallows_a_neighbouring_label():
    # `_looks_like_person_name` is shape-only, so a stray capitalised token
    # from the next column's LABEL would pass it and turn a correct 3-token
    # read into a 4-token one -- the same hard MISMATCH the truncation causes,
    # in the other direction. 'Họ' opens "họ và tên", so the extension stops.
    lines = [
        [W("BÊN", 196, 671, 46, 22), W("CUNG", 251, 671, 67, 16), W("ỨNG", 326, 671, 52, 22),
         W("DỊCH", 385, 671, 60, 20), W("VỤ", 453, 671, 32, 21),
         W("Trần", 534, 671, 42, 16), W("Văn", 584, 671, 38, 16), W("Tiến", 630, 671, 40, 16)],
        [W("Họ", 700, 676, 26, 18)],
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert [h["value"] for h in hits] == ["Trần Văn Tiến"]


def test_party_column_blocks_needs_a_header_and_two_two_column_rows():
    from ocr_extract import _party_column_blocks
    header = _vng_and_ctv_header_row()
    names = _p82_name_lines()
    # header + both name lines (ONE visual row) + email + phone -> a block,
    # its gutter between the two columns' measured x-spans.
    blocks = _party_column_blocks([header, *names, *_email_and_phone_rows()])
    assert len(blocks) == 1
    assert 494 < blocks[0]["gutter"] < 659
    # only ONE two-column row below the header -> not a block
    assert _party_column_blocks([header, *names]) == []
    # no header at all -> nothing to classify with
    assert _party_column_blocks([*names, *_email_and_phone_rows()]) == []
    # a full-width row right under the header closes the block before it can
    # collect its two rows (this is what stops a block creeping down the page)
    wide = [[W("Điều", 230, 660, 44, 18), W("2.", 280, 660, 24, 18),
             W("Phí", 320, 660, 34, 18), W("dịch", 360, 660, 40, 18),
             W("vụ", 406, 660, 26, 18), W("và", 438, 660, 24, 18),
             W("thanh", 468, 660, 60, 18), W("toán", 534, 660, 48, 18),
             W("theo", 588, 660, 46, 18), W("quy", 640, 660, 40, 18),
             W("định", 686, 660, 44, 18), W("của", 736, 660, 40, 18),
             W("pháp", 782, 660, 50, 18), W("luật", 838, 660, 40, 18)]]
    assert _party_column_blocks([header, *wide, *names, *_email_and_phone_rows()]) == []


def test_party_header_row_ignores_low_confidence_specks():
    # abs page 275's header row only qualifies once the two illegible marks
    # around it are dropped: '+}' (conf 43) sits INSIDE the gutter and would
    # defeat the gap, and '|' (conf 26) sits past the header's end and would
    # defeat the "the CTV header run ends the row" test.
    from ocr_extract import _party_header_band
    row = [
        W("VNG", 236, 637, 50, 25, conf=91), W("+}", 646, 634, 24, 39, conf=43),
        W("Bên", 668, 633, 36, 16), W("Cung", 712, 633, 51, 20),
        W("Ứng", 770, 627, 40, 25), W("Dịch", 816, 632, 44, 20),
        W("Vụ", 866, 630, 28, 20), W("|", 1087, 640, 16, 19, conf=26),
    ]
    assert _party_header_band(row, min_gutter=56) == (286, 668)
    # the same marks at LABEL confidence are real content, and the row is then
    # not a two-column header at all
    legible = [dict(w, conf=90) for w in row]
    assert _party_header_band(legible, min_gutter=56) is None


def test_party_of_classifies_against_the_gutter():
    from ocr_extract import _party_of
    blocks = [{"y0": 616, "y1": 823, "gutter": 576}]
    assert _party_of({"x": 330, "y": 671, "width": 164, "height": 23}, blocks) == "a"
    assert _party_of({"x": 758, "y": 680, "width": 144, "height": 20}, blocks) == "b"
    # abs page 275's splice, which crosses the divide -> neither party's
    assert _party_of({"x": 387, "y": 693, "width": 309, "height": 19}, blocks) == "straddle"
    # a wide value that still starts clear of the gutter is the CTV's
    assert _party_of({"x": 600, "y": 680, "width": 400, "height": 20}, blocks) == "b"
    # outside the block's rows there is no party evidence
    assert _party_of({"x": 330, "y": 300, "width": 164, "height": 23}, blocks) is None


def test_best_hit_ranks_party_evidence_above_confidence():
    from ocr_extract import _best_hit
    ctv = (1, {"value": "Nhan Kiến Phát", "bbox": {}, "confidence": 0.60, "rank": 1})
    vng = (0, {"value": "Trần Lê Hoài Anh", "bbox": {}, "confidence": 0.95, "rank": 0})
    assert _best_hit([vng, ctv])[1]["value"] == "Nhan Kiến Phát"
    # a readable hit still beats an unread one regardless of rank
    unread = (2, {"value": "", "bbox": {}, "confidence": 0.0, "rank": 1})
    assert _best_hit([unread, vng])[1]["value"] == "Trần Lê Hoài Anh"


def test_party_certainty_has_one_level_so_confidence_breaks_the_tie():
    # The column divide and a party-specific anchor phrase are EQUAL evidence:
    # both say "these words are the CTV's", and between two such reads only
    # confidence is left to choose. Measured on the July batch: ranking the
    # column above the phrase moved packets 22 and 28 from a match to a
    # "cần xem" (their contract page 1 reads the same name a diacritic worse
    # than the party-labeled block on page 0) and fixed nothing extra.
    from ocr_extract import _best_hit
    from_column = (1, {"value": "Lê Định Lương Thiện", "bbox": {}, "confidence": 0.91, "rank": 1})
    from_anchor = (0, {"value": "Lê Đinh Lương Thiện", "bbox": {}, "confidence": 0.93, "rank": 1})
    assert _best_hit([from_column, from_anchor])[1]["value"] == "Lê Đinh Lương Thiện"


def test_best_hit_is_unchanged_for_hits_without_a_rank():
    # `locate_field`'s hits (the five pattern fields) carry no "rank", so the
    # key degenerates to the confidence-only one it replaced -- including the
    # tie, where `max` returns the FIRST maximal element either way.
    from ocr_extract import _best_hit
    hits = [
        (0, {"value": "079189016370", "bbox": {}, "confidence": 0.91}),
        (1, {"value": "079189016371", "bbox": {}, "confidence": 0.95}),
        (2, {"value": "079189016372", "bbox": {}, "confidence": 0.95}),
    ]
    assert _best_hit(hits) == max(hits, key=lambda ph: ph[1]["confidence"])
    assert _best_hit(hits)[1]["value"] == "079189016371"


def test_dedupe_and_cap_keeps_the_party_confirmed_hit():
    # #011's ordering is (rank, confidence) DESCENDING: a rank-0 hit must not
    # consume one of the three cap slots ahead of the party-confirmed one,
    # even when it reads more crisply.
    from ocr_extract import _dedupe_and_cap
    hits = [
        {"value": "A A", "bbox": {}, "confidence": 0.99, "rank": 0},
        {"value": "B B", "bbox": {}, "confidence": 0.98, "rank": 0},
        {"value": "C C", "bbox": {}, "confidence": 0.97, "rank": 0},
        {"value": "Nhan Kiến Phát", "bbox": {}, "confidence": 0.60, "rank": 1},
    ]
    kept = _dedupe_and_cap(hits)
    assert kept[0]["value"] == "Nhan Kiến Phát"
    assert len(kept) == 3


def test_extract_fields_hoten_source_is_the_ctv_column():
    # End to end: one document, one page with abs page 82's layout -> exactly
    # one `hoten` source, the CTV's name, and no "rank" key on the emitted
    # source (the manifest shape is untouched -- `extract_fields` builds each
    # source dict explicitly).
    words = [w for line in [_vng_and_ctv_header_row(), *_p82_name_lines(),
                            *_email_and_phone_rows()] for w in line]
    fields = extract_fields({"contract-0": {1: words}}, {"name": "Nhan Kiến Phát"})
    hoten = next(f for f in fields if f["key"] == "hoten")
    assert len(hoten["sources"]) == 1
    src = hoten["sources"][0]
    assert src["value"] == "Nhan Kiến Phát"
    assert src["page"] == 1
    assert set(src) == {"docId", "page", "value", "bbox", "confidence"}


def test_locate_field_still_associates_a_label_across_a_large_gap():
    # The party divide CLASSIFIES words; it never cuts a line, and
    # `group_lines` is untouched -- so the label-to-value association the
    # other five fields depend on is unaffected even when the gap between a
    # label and its value is gutter-sized ("CCCD số      :      079189016370"
    # measures ~120px on the real pages).
    cccd_spec = next(s for s in FIELD_SPECS if s["key"] == "cccd")
    lines = [[
        W("CCCD", 231, 500, 60, 18), W("số", 300, 500, 24, 18), W(":", 420, 500, 8, 18),
        W("079189016370", 540, 500, 150, 18, conf=93),
    ]]
    hits = locate_field(lines, cccd_spec)
    assert len(hits) == 1
    assert hits[0]["value"] == "079189016370"
    assert abs(hits[0]["confidence"] - 0.93) < 1e-9


def test_find_name_row_value_ignores_scanner_edge_specks():
    # abs page 170 (packet 20's contract). `group_lines` merged both columns
    # into one line here, and the same VISUAL row also carries two
    # scanner-edge specks in the right margin: 'ZZ' at conf 2 and 'NI' at conf
    # 1, x=1222..1240. Both are capitalised and alphabetic, so the shape check
    # accepts them, and the CTV's 'Trần Văn Ninh' came out as the 5-token
    # 'Trần Văn Ninh ZZ NI' at confidence 0.01 -- a differing token count,
    # which `compare_values._person_verdict` makes an outright MISMATCH. A
    # value assembled from a whole row must be legible end to end or not be
    # published at all; the label is still worth a "cần xem" chip.
    lines = [
        [W("VNG", 235, 634, 48, 16, conf=90),
         W("Bên", 640, 630, 36, 16), W("Cung", 682, 631, 51, 20),
         W("Ứng", 740, 626, 40, 25), W("Dịch", 787, 630, 44, 20),
         W("Vụ", 838, 630, 26, 20)],
        [W("Họ", 236, 694, 25, 18), W("và", 268, 693, 20, 15), W("tên:", 295, 693, 32, 15),
         W("Trịnh", 335, 692, 52, 20), W("Đức", 394, 692, 38, 16, conf=93),
         W("Minh", 440, 690, 50, 17),
         W("Họ", 640, 690, 26, 19, conf=95), W("và", 674, 690, 20, 16),
         W("tên:", 701, 690, 30, 16), W("Trần", 740, 685, 42, 20),
         W("Văn", 788, 690, 37, 15), W("Ninh", 830, 689, 44, 16)],
        [W("ZZ", 1222, 704, 18, 14, conf=2), W("NI", 1224, 676, 16, 18, conf=1)],
        *_email_and_phone_rows(),
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    assert all("ZZ" not in h["value"] for h in hits)
    assert [h["value"] for h in hits] == [""]      # located, not read: "cần xem"
    assert hits[0]["confidence"] == 0.0


def test_find_name_legible_row_value_is_published_from_the_same_shape():
    # The same merged-columns shape WITHOUT the specks: the CTV's name is
    # published, bounded at the next label so it can't run into VNG's column.
    # This is the pair that shows the speck rejection above is about
    # legibility, not about the merged row.
    lines = [
        [W("VNG", 235, 634, 48, 16, conf=90),
         W("Bên", 640, 630, 36, 16), W("Cung", 682, 631, 51, 20),
         W("Ứng", 740, 626, 40, 25), W("Dịch", 787, 630, 44, 20),
         W("Vụ", 838, 630, 26, 20)],
        [W("Họ", 236, 694, 25, 18), W("và", 268, 693, 20, 15), W("tên:", 295, 693, 32, 15),
         W("Trịnh", 335, 692, 52, 20), W("Đức", 394, 692, 38, 16), W("Minh", 440, 690, 50, 17),
         W("Họ", 640, 690, 26, 19), W("và", 674, 690, 20, 16), W("tên:", 701, 690, 30, 16),
         W("Trần", 740, 685, 42, 20), W("Văn", 788, 690, 37, 15), W("Ninh", 830, 689, 44, 16)],
        *_email_and_phone_rows(),
    ]
    hits = find_name(lines, anchors=HOTEN_ANCHORS)
    readable = [h for h in hits if h["value"]]
    assert [h["value"] for h in readable] == ["Trần Văn Ninh"]
    assert readable[0]["rank"] == 1
    # VNG's column is never published; the merged line's own 9-token read is
    # not name-shaped, so it stays the "cần xem" it has always been.
    assert all("Trịnh" not in h["value"] for h in hits)


def test_assemble_docs_records_where_each_party_signs():
    """Locating has to happen during the read: the saved manifest keeps only
    {src, width, height} per page, so nothing can be searched afterwards."""
    from ocr_extract import assemble_docs

    header = [
        {"text": t, "x": 600 + i * 70, "y": 900, "w": 60, "h": 20, "conf": 90}
        for i, t in enumerate(["BÊN", "CUNG", "ỨNG", "DỊCH", "VỤ"])
    ]
    pages = [
        {"src": "pg0.png", "width": 1000, "height": 1400},
        {"src": "pg1.png", "width": 1000, "height": 1400},
    ]
    segments = [{"kind": "contract", "label": "Hợp đồng", "pages": [0, 1]}]

    docs, _, _ = assemble_docs(
        segments, pages, {0: [], 1: header},
    )

    # The page is the index WITHIN the document, which is what a source means.
    assert docs[0]["anchors"]["ctv"]["page"] == 1
    assert docs[0]["anchors"]["ctv"]["bbox"]["height"] > 0


def test_assemble_docs_always_records_an_anchors_key():
    """A missing key and `no signature block on this document` are different
    answers, and the reader must not have to guess which it is looking at."""
    from ocr_extract import assemble_docs

    docs, _, _ = assemble_docs(
        [{"kind": "pit", "label": "Tra cứu thuế", "pages": [0]}],
        [{"src": "pg0.png", "width": 1000, "height": 1400}],
        {0: [{"text": "MST", "x": 10, "y": 10, "w": 40, "h": 12, "conf": 90}]},
    )

    assert docs[0]["anchors"] == {}


# --- semantic fields (Task 5) -------------------------------------------------

class TestSemanticFields:
    """`_semantic_fields` is where all of Task 5's logic lives.

    `ocr_packet` itself is exercised by source inspection here, as it already
    is for the page-reader hand-over above: running it needs a real PDF and
    real OCR, and the parts worth guarding are the request derivation, the
    text/words correspondence and the shape written to the manifest.
    """

    @staticmethod
    def _word(text, x, y):
        return {"text": text, "x": x, "y": y, "w": len(text) * 8, "h": 12,
                "conf": 90.0}

    def _doc(self, kind="contract", doc_id="d1", pages=1):
        return {"id": doc_id, "kind": kind, "label": kind,
                "pages": [{"src": f"p{i}.png", "width": 800, "height": 1000}
                          for i in range(pages)]}

    def _words(self):
        line1 = [self._word(t, 10 + i * 60, 10) for i, t in enumerate(
            ["Thời", "hạn", "thanh", "toán", "là", "15"])]
        line2 = [self._word(t, 10 + i * 60, 30) for i, t in enumerate(
            ["ngày", "kể", "từ", "ngày", "nghiệm", "thu"])]
        return {0: line1 + line2}

    def _reader(self, **fields):
        import semantic_read as sr
        return sr.FakeReader({
            key: sr.SemanticField(value=v, quote=q, page=p)
            for key, (v, q, p) in fields.items()
        })

    def test_a_value_reaches_the_manifest_with_its_quote_page_and_box(self):
        reader = self._reader(
            term=("15 ngày", "thanh toán là 15 ngày kể từ ngày", 0))
        fields = oe._semantic_fields(reader, [self._doc()], {"d1": self._words()})

        field = next(f for f in fields if f["key"] == "term")
        source = field["sources"][0]
        assert source["value"] == "15 ngày"
        assert source["provenance"] == "llm"
        assert source["quote"] == "thanh toán là 15 ngày kể từ ngày"
        assert source["page"] == 0
        assert source["bbox"] is not None
        assert source["confidence"] == 1.0

    def test_the_document_is_asked_only_for_what_its_criteria_declare(self):
        # Derived from the criteria, so adding a part to a criterion asks for
        # it and no second list can drift from the first.
        import criteria as cr
        reader = self._reader()
        oe._semantic_fields(reader, [self._doc()], {"d1": self._words()})

        assert len(reader.calls) == 1
        asked = set(reader.calls[0]["want"])
        assert asked == set(cr.semantic_parts_by_document()["Hợp đồng"])
        assert "term" in asked and "bank" in asked
        # #27 is deferred for want of reference data, so its parts are not sent.
        assert "legal_name" not in asked

    def test_a_document_no_criterion_reads_a_clause_from_is_not_sent(self):
        # Every field requested puts more contract text on the wire, which
        # ver3-scope §4 bounds deliberately.
        reader = self._reader(term=("x", "thanh toán là 15 ngày kể từ ngày", 0))
        fields = oe._semantic_fields(
            reader, [self._doc(kind="id_front", doc_id="d1")],
            {"d1": self._words()})
        assert fields == []
        assert reader.calls == []

    def test_a_document_with_no_words_is_not_sent(self):
        reader = self._reader(term=("x", "y", 0))
        assert oe._semantic_fields(reader, [self._doc()], {"d1": {}}) == []
        assert reader.calls == []

    def test_the_text_sent_is_rebuilt_from_the_words_that_will_be_searched(self):
        """The correspondence that makes the unlocatable rate mean anything.

        An OCR error then sits identically on both sides and cancels, so a
        quote that fails to locate is the model departing from the page rather
        than Tesseract having misread it.
        """
        seen = {}

        class Recording:
            def read(self, *, doc_kind, pages_text, want):
                seen["text"] = pages_text
                return {}

        oe._semantic_fields(Recording(), [self._doc()], {"d1": self._words()})
        assert "Thời hạn thanh toán là 15" in seen["text"][0]
        assert "ngày kể từ ngày nghiệm thu" in seen["text"][0]

    def test_an_unlocatable_quote_is_still_recorded_at_zero_confidence(self):
        # Kept, not dropped: the unlocatable rate is the gate the real adapter
        # is judged by, and discarding these would make it unmeasurable.
        reader = self._reader(
            term=("15 ngày", "hoàn toàn không có nội dung nào như thế", 0))
        fields = oe._semantic_fields(reader, [self._doc()], {"d1": self._words()})

        source = next(f for f in fields if f["key"] == "term")["sources"][0]
        assert source["bbox"] is None
        assert source["confidence"] == 0.0
        assert source["value"] == "15 ngày"

    def test_a_value_with_no_quote_never_reaches_the_manifest(self):
        reader = self._reader(term=("15 ngày", "", 0))
        assert oe._semantic_fields(
            reader, [self._doc()], {"d1": self._words()}) == []

    def test_a_reader_that_raises_costs_the_read_nothing(self):
        class Boom:
            def read(self, **kwargs):
                raise RuntimeError("timeout")

        assert oe._semantic_fields(
            Boom(), [self._doc()], {"d1": self._words()}) == []

    def test_one_key_read_from_two_documents_keeps_both_sources(self):
        reader = self._reader(term=("15 ngày", "thanh toán là 15 ngày kể từ ngày", 0))
        docs = [self._doc(doc_id="d1"), self._doc(kind="bbnt", doc_id="d2")]
        fields = oe._semantic_fields(
            reader, docs, {"d1": self._words(), "d2": self._words()})

        term = next(f for f in fields if f["key"] == "term")
        assert [s["docId"] for s in term["sources"]] == ["d1", "d2"]

    def test_ocr_packet_offers_the_reader_and_skips_it_when_absent(self):
        # Same convention as the page-reader hand-over test above: running
        # ocr_packet needs a real PDF and real OCR.
        source = inspect.getsource(oe.ocr_packet)
        assert "semantic_reader=None" in source
        assert "if semantic_reader is not None:" in source
        assert "_semantic_fields(semantic_reader" in source
