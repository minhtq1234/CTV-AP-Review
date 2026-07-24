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
