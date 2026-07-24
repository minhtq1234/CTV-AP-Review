from checklist import build_checklist

FIELDS = [
  {"key": "hoten", "label": "Họ và tên", "expected": "Nguyễn Hoàng Phúc",
   "sources": [{"docId": "contract", "page": 0, "value": "Nguyễn Hoàng Phúc", "bbox": {"x":1,"y":1,"width":1,"height":1}, "confidence": 0.9}]},
  {"key": "mst", "label": "MST", "expected": "095204007694",
   "sources": [{"docId": "contract", "page": 0, "value": "8391246072", "bbox": {"x":1,"y":1,"width":1,"height":1}, "confidence": 0.9}]},
  {"key": "phi", "label": "Phí", "expected": "5.555.556", "sources": []},
]
DOCS = [{"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ"},
        {"id": "bbnt", "kind": "bbnt", "label": "Biên bản thanh lý"},
        {"id": "camket", "kind": "commitment", "label": "Bản cam kết"}]
MATCH = {"matchedBy": "cccd", "ocrIdentity": {"cccd": "079", "name": "X"}, "rosterIdentity": {"cccd": "079", "name": "X"}}

def _by_code(checks): return {c["code"]: c for c in checks}

def test_emits_gates_first_then_detail_in_order():
    checks = build_checklist(FIELDS, MATCH, DOCS)
    codes = [c["code"] for c in checks]
    assert codes[:4] == ["G-DOC", "D3", "B3", "C2"]
    assert "G-ID" not in codes
    assert set(codes[4:]) <= {"B1", "A1", "A2", "B2", "BANK", "INFO", "C1", "D1"}
    assert all(c["tier"] == "gate" for c in checks[:4])

def test_value_check_carries_reference_source_and_autostatus():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["B1"]["kind"] == "value" and c["B1"]["reference"] == "Nguyễn Hoàng Phúc"
    assert c["B1"]["source"]["value"] == "Nguyễn Hoàng Phúc" and c["B1"]["autostatus"] == "match"
    assert c["A2"]["autostatus"] == "mismatch"
    assert c["B2"]["autostatus"] == "review"

def test_confirm_kinds_and_routing():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert "G-ID" not in c
    assert c["B3"]["kind"] == "confirm" and c["B3"]["evidenceDocId"] == "contract"
    assert c["C2"]["evidenceDocId"] == "bbnt" and c["D3"]["evidenceDocId"] == "camket"
    assert c["G-DOC"]["evidenceDocId"] is None

def test_value_check_prefers_source_on_its_routed_doc():
    # hoten located on BOTH bbnt (readable) and contract (unread slot); B1 routes
    # to 'contract', so it must pick the contract source, not sources[0].
    fields = [{"key": "hoten", "label": "Họ và tên", "expected": "Nguyễn Hoàng Phúc",
               "sources": [
                   {"docId": "bbnt", "page": 2, "value": "Nguyễn Hoàng Phúc",
                    "bbox": {"x":1,"y":1,"width":1,"height":1}, "confidence": 0.9},
                   {"docId": "contract", "page": 0, "value": "",
                    "bbox": {"x":5,"y":5,"width":9,"height":3}, "confidence": 0.0},
               ]}]
    c = {x["code"]: x for x in build_checklist(fields, MATCH, DOCS)}
    assert c["B1"]["evidenceDocId"] == "contract"
    assert c["B1"]["source"]["docId"] == "contract"

def test_name_with_D_stroke_matches():
    fields = [{"key": "hoten", "label": "Họ và tên", "expected": "Đặng Văn Đức",
               "sources": [{"docId": "contract", "page": 0, "value": "ĐẶNG VĂN ĐỨC",
                            "bbox": {"x":1,"y":1,"width":1,"height":1}, "confidence": 0.9}]}]
    c = {x["code"]: x for x in build_checklist(fields, MATCH, DOCS)}
    assert c["B1"]["autostatus"] == "match"

def test_contract_routed_checks_fall_back_to_first_doc():
    docs = [{"id": "only", "kind": "bbnt", "label": "x"}]  # no doc tagged 'contract'
    c = {x["code"]: x for x in build_checklist(FIELDS, MATCH, docs)}
    assert c["B3"]["evidenceDocId"] == "only"   # contract fallback -> first doc
    # B2 ("phi") has sources: [] in FIELDS, so src is None and the _VALUE loop's
    # fallback branch is exercised. B1 ("name") hardcodes sources[0].docId ==
    # "contract" in FIELDS, which always wins the `or` short-circuit regardless
    # of the fallback fix, so it can't discriminate this behavior.
    assert c["B2"]["evidenceDocId"] == "only"

DOCS_NO_COMMIT = [{"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ"},
                  {"id": "bbnt", "kind": "bbnt", "label": "Biên bản nghiệm thu"}]

def test_omits_commitment_routed_checks_when_no_commitment_doc():
    codes = [c["code"] for c in build_checklist(FIELDS, MATCH, DOCS_NO_COMMIT)]
    assert "D3" not in codes and "D1" not in codes
    assert codes[:3] == ["G-DOC", "B3", "C2"]      # D3 gate drops out of the gate run

def test_keeps_commitment_routed_checks_when_commitment_present():
    codes = [c["code"] for c in build_checklist(FIELDS, MATCH, DOCS)]  # DOCS has 'camket'
    assert "D3" in codes and "D1" in codes

def test_bbnt_routed_checks_omitted_when_no_bbnt():
    docs = [{"id": "contract", "kind": "contract", "label": "x"}]
    codes = [c["code"] for c in build_checklist(FIELDS, MATCH, docs)]
    assert "C2" not in codes   # C2 routes to bbnt; none present -> omitted
    assert "B3" in codes       # B3 routes to contract (present) -> kept

DOCS_PAGED = [
    {"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ",
     "pages": [{"src": "a", "width": 1000, "height": 1400},
               {"src": "b", "width": 1000, "height": 1400}]},
    {"id": "bbnt-0", "kind": "bbnt", "label": "Biên bản nghiệm thu",
     "pages": [{"src": "c", "width": 1000, "height": 1400}]},
    {"id": "bbnt-1", "kind": "bbnt", "label": "Biên bản thanh lý hợp đồng",
     "pages": [{"src": "d", "width": 1000, "height": 1400},
               {"src": "e", "width": 1000, "height": 1400}]},
    {"id": "camket", "kind": "commitment", "label": "Bản cam kết",
     "pages": [{"src": "f", "width": 1000, "height": 1400}]},
]

def test_signature_gates_focus_last_page_bottom_band():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS_PAGED))
    b3 = c["B3"]["focus"]
    assert b3 is not None
    assert b3["page"] == 1                       # contract's last page (0-based)
    assert b3["caption"] == "Khu vực chữ ký & con dấu"
    assert b3["bbox"]["y"] > 1400 * 0.5          # bottom band
    assert b3["bbox"]["y"] + b3["bbox"]["height"] <= 1400
    assert b3["bbox"]["width"] == 1000

def test_c2_focuses_thanh_ly_bbnt_when_two_bbnts():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS_PAGED))
    assert c["C2"]["evidenceDocId"] == "bbnt-1"   # the thanh lý one, not nghiệm thu
    assert c["C2"]["focus"]["page"] == 1          # its last page

def test_signature_focus_absent_when_doc_has_no_pages():
    # module-level DOCS has no 'pages' -> no focus computed, no crash
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["B3"].get("focus") in (None,)

def test_d3_carries_reference_asset_when_commitment_present():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["D3"]["referenceAsset"] == "/reference/mau-08-ck-tncn-2026.svg"

def test_no_reference_asset_on_other_checks():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["B3"].get("referenceAsset") is None
