import pytest

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

def test_a1_prefers_mapped_cccd_front_and_stays_reviewer_controlled():
    fields = [{
        "key": "cccd",
        "label": "Số CCCD",
        "expected": "000000000001",
        "sources": [
            {
                "docId": "contract",
                "page": 0,
                "value": "000000000001",
                "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
                "confidence": .91,
            },
            {
                "docId": "cccd-excel-card-drawing-0001-front",
                "page": 0,
                "value": "000000000001",
                "bbox": {"x": 20, "y": 30, "width": 80, "height": 24},
                "confidence": .95,
            },
        ],
    }]
    docs = [
        *DOCS,
        {
            "id": "cccd-excel-card-drawing-0001-front",
            "kind": "id_front",
            "label": "CCCD (Excel) · Mặt trước",
            "pages": [],
        },
    ]

    a1 = _by_code(build_checklist(fields, MATCH, docs))["A1"]

    assert a1["evidenceDocId"] == "cccd-excel-card-drawing-0001-front"
    assert a1["source"]["bbox"]["x"] == 20
    assert a1["autostatus"] == "review"

def test_a1_without_mapped_cccd_keeps_existing_comparison():
    fields = [{
        "key": "cccd",
        "label": "Số CCCD",
        "expected": "000000000001",
        "sources": [{
            "docId": "contract",
            "page": 0,
            "value": "000000000001",
            "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
            "confidence": .91,
        }],
    }]

    a1 = _by_code(build_checklist(fields, MATCH, DOCS))["A1"]

    assert a1["evidenceDocId"] == "contract"
    assert a1["autostatus"] == "match"

@pytest.mark.parametrize("malformed_doc_id", [None, 42])
def test_a1_ignores_non_string_doc_ids_and_keeps_legacy_contract_routing(
    malformed_doc_id,
):
    fields = [{
        "key": "cccd",
        "label": "Số CCCD",
        "expected": "000000000001",
        "sources": [
            {
                "docId": malformed_doc_id,
                "page": 0,
                "value": "000000000001",
                "bbox": {"x": 1, "y": 1, "width": 2, "height": 2},
                "confidence": .91,
            },
            {
                "docId": "contract",
                "page": 0,
                "value": "000000000001",
                "bbox": {"x": 20, "y": 30, "width": 80, "height": 24},
                "confidence": .95,
            },
        ],
    }]

    a1 = _by_code(build_checklist(fields, MATCH, DOCS))["A1"]

    assert a1["evidenceDocId"] == "contract"
    assert a1["source"]["bbox"]["x"] == 20
    assert a1["autostatus"] == "match"

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

def test_c2_routes_to_thanh_ly_bbnt_when_two_bbnts():
    # C2 (chữ ký & giáp lai BBNT) opens the thanh-lý minutes when a packet has both,
    # not the nghiệm-thu. (Signature auto-focus itself was removed — no 'focus' key.)
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS_PAGED))
    assert c["C2"]["evidenceDocId"] == "bbnt-1"
    assert "focus" not in c["C2"]

def test_d3_carries_reference_asset_when_commitment_present():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["D3"]["referenceAsset"] == "/reference/mau-08-ck-tncn-2026.svg"

def test_no_reference_asset_on_other_checks():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["B3"].get("referenceAsset") is None

DOCS_WITH_APPENDIX = [
    {"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ"},
    {"id": "bbnt", "kind": "bbnt", "label": "Biên bản nghiệm thu"},
    {"id": "pluc", "kind": "appendix", "label": "Phụ lục"},
]

def test_c1_routes_to_appendix_when_present():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS_WITH_APPENDIX))
    assert c["C1"]["evidenceDocId"] == "pluc"
    assert c["C1"]["kind"] == "confirm" and c["C1"]["tier"] == "detail"

def test_c1_falls_back_to_bbnt_when_no_appendix():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["C1"]["evidenceDocId"] == "bbnt"
