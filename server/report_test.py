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

def test_unread_source_value_falls_back_to_can_xem():
    # A flagged field whose (first) source has no readable OCR value should
    # show the "cần xem" placeholder instead of an empty string.
    case = {"name": "FA.pdf", "packets": [
        {"index": 0, "name": "Chưa Đọc Được", "matchedBy": "cccd",
         "ocrIdentity": {"cccd": "555", "name": "Chưa Đọc Được"},
         "rosterIdentity": {"cccd": "555", "name": "Chưa Đọc Được"},
         "review": {"done": True, "fields": {
             "cccd": {"seen": False, "flag": {"reason": "mo", "note": ""}}}}},
    ]}
    manifests = {0: {
        "fields": [{"key": "cccd", "label": "Số CCCD", "expected": "079198004444",
                    "sources": [{"docId": "contract", "page": 0, "value": ""}]}],
        "docs": [{"id": "contract", "label": "Hợp đồng dịch vụ"}],
    }}
    r = build_report(case, manifests, generated_at="2026-07-23T00:00:00Z")
    item = r["groups"][0]["items"][0]
    assert item["docValue"] == "cần xem"

def test_packet_rejection_is_structured_once_before_field_issue():
    case = {
        "name": "Synthetic batch",
        "packets": [{
            "index": 0,
            "name": "Synthetic Reviewer",
            "matchedBy": "cccd",
            "ocrIdentity": {"cccd": "000", "name": "Synthetic Reviewer"},
            "rosterIdentity": {"cccd": "000", "name": "Synthetic Reviewer"},
            "review": {
                "done": True,
                "rejection": {
                    "reasons": ["missing_documents", "missing_signature"],
                    "note": "Bổ sung bộ hồ sơ",
                },
                "fields": {
                    "cccd": {
                        "seen": True,
                        "flag": {"reason": "sai", "note": "kiểm tra lại"},
                    },
                },
            },
        }],
    }
    manifests = {
        0: {
            "fields": [{
                "key": "cccd",
                "label": "Số CCCD",
                "expected": "000",
                "sources": [{"docId": "contract", "page": 0, "value": "001"}],
            }],
            "docs": [{"id": "contract", "label": "Hợp đồng"}],
        },
    }
    report = build_report(case, manifests, generated_at="2026-07-27T00:00:00Z")
    group = report["groups"][0]
    assert group["packetRejection"] == {
        "reasons": ["missing_documents", "missing_signature"],
        "reasonLabels": ["Thiếu chứng từ", "Thiếu chữ ký"],
        "note": "Bổ sung bộ hồ sơ",
    }
    assert report["markdown"].index("Từ chối gói hồ sơ") < \
        report["markdown"].index("Số CCCD")
    assert report["markdown"].count("Từ chối gói hồ sơ") == 1
    rows = report["csv"].splitlines()
    assert "Từ chối gói hồ sơ" in rows[1]
    assert "Thiếu chứng từ; Thiếu chữ ký" in rows[1]
    assert sum("Từ chối gói hồ sơ" in row for row in rows) == 1

def test_packet_rejection_optional_note_is_omitted_from_markdown():
    case = {
        "name": "Synthetic batch",
        "packets": [{
            "index": 0, "name": "Synthetic Reviewer", "matchedBy": "cccd",
            "ocrIdentity": {"cccd": "", "name": ""},
            "rosterIdentity": None,
            "review": {
                "done": True,
                "fields": {},
                "rejection": {
                    "reasons": ["wrong_template"],
                    "note": "",
                },
            },
        }],
    }
    report = build_report(case, {}, generated_at="2026-07-27T00:00:00Z")
    assert len(report["groups"]) == 1
    assert "Chứng từ không đúng mẫu" in report["markdown"]
    assert "Ghi chú:" not in report["markdown"]


def test_boundary_warning_keeps_participant_resubmission_groups_unchanged():
    boundary_status = {
        "status": "review",
        "packetIndexes": [1],
        "reasons": ["length-out-of-range", "multiple-contract-starts"],
    }

    report = build_report(
        CASE,
        MANIFESTS,
        generated_at="2026-07-27T00:00:00Z",
        boundary_status=boundary_status,
    )

    assert [group["index"] for group in report["groups"]] == [0, 1]
    assert report["boundaryWarnings"] == [{
        "packetIndex": 1,
        "packetNumber": 2,
        "reasons": ["length-out-of-range", "multiple-contract-starts"],
    }]
    assert "Gói 2" in report["markdown"]
    assert "Cảnh báo ranh giới" in report["csv"]
