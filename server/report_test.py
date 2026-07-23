from report import build_report

CASE = {
    "name": "FA.pdf",
    "packets": [
        {"index": 0, "name": "Lê Thị Mai Anh", "matchedBy": "cccd",
         "ocrIdentity": {"cccd": "079", "name": "Lê Thị Mai Anh"},
         "rosterIdentity": {"cccd": "079", "name": "Lê Thị Mai Anh"},
         "review": {"done": True, "fields": {
             "cccd": {"seen": True, "flag": {"reason": "sai", "note": "lệch 1 số"}}}}},
        {"index": 1, "name": "Trần Minh Khoa", "matchedBy": "name",   # weak match, no field flag
         "ocrIdentity": {"cccd": "111", "name": "Trần Minh Khoa"},
         "rosterIdentity": {"cccd": "222", "name": "Trần Minh Khoa"},
         "review": {"done": True, "fields": {}}},
        {"index": 2, "name": "OK Person", "matchedBy": "cccd",       # clean -> excluded
         "ocrIdentity": {"cccd": "333", "name": "OK Person"},
         "rosterIdentity": {"cccd": "333", "name": "OK Person"},
         "review": {"done": True, "fields": {"cccd": {"seen": True, "flag": None}}}},
    ],
}
MANIFESTS = {
    0: {"fields": [{"key": "cccd", "label": "Số CCCD", "expected": "079198004321",
                    "sources": [{"docId": "contract", "page": 0, "value": "079198004327"}]}],
        "docs": [{"id": "contract", "label": "Hợp đồng dịch vụ"}]},
    1: {"fields": [], "docs": []},
}

def test_only_needs_resubmit_packets_are_grouped():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    names = [g["name"] for g in r["groups"]]
    assert names == ["Lê Thị Mai Anh", "Trần Minh Khoa"]   # index 2 (clean) excluded

def test_field_flag_item_resolves_label_doc_and_values():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    item = r["groups"][0]["items"][0]
    assert item["fieldLabel"] == "Số CCCD"
    assert item["document"] == "Hợp đồng dịch vụ"
    assert item["page"] == 1                     # 1-based for humans
    assert item["rosterValue"] == "079198004321"
    assert item["docValue"] == "079198004327"
    assert item["reason"] == "sai" and item["note"] == "lệch 1 số"

def test_weak_match_becomes_identity_issue():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    khoa = r["groups"][1]
    assert khoa["identityIssue"] is True
    assert khoa["matchedBy"] == "name"

def test_markdown_and_csv_render():
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    assert "Lê Thị Mai Anh" in r["markdown"] and "Số CCCD" in r["markdown"]
    assert "khớp theo tên" in r["markdown"].lower()
    lines = r["csv"].splitlines()
    assert lines[0].startswith("CTV,CCCD,Trường,")
    assert any("Số CCCD" in ln for ln in lines[1:])
