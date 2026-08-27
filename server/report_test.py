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


# ---------------------------------------------------------------------------
# The criteria engine's findings in the report.
#
# `build_report` reported only what a *human* had flagged: `_items_for` skips
# every field without one. So a submission could carry 199 findings the engine
# had already computed and the exported report would say nothing about any of
# them. Passing the roster in adds them, without disturbing the manual-flag path.
# ---------------------------------------------------------------------------

from roster_checks_test import GOOD, sheet   # noqa: E402  (the real roster shape)


def _packet(index, name, cccd, docs, fields, matched="cccd"):
    return {
        "index": index, "name": name, "matchedBy": matched,
        "ocrIdentity": {"cccd": cccd, "name": name},
        "rosterIdentity": {"cccd": cccd, "name": name},
        "review": {"done": False, "fields": {}, "rejection": None},
    }


def _manifest(docs, fields):
    return {
        "id": "p", "name": "", "product": "", "docs": docs,
        "fields": [{"key": k, "label": lbl, "group": "Danh tính",
                    "check": "compare", "kind": kind, "expected": exp,
                    "sources": srcs}
                   for k, lbl, kind, exp, srcs in fields],
    }


def _doc(doc_id, kind, label):
    return {"id": doc_id, "kind": kind, "label": label, "pages": []}


def _src(doc_id, value, conf=0.95):
    return {"docId": doc_id, "page": 0, "value": value, "confidence": conf,
            "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}}


#: One CTV whose contract names someone else — a real finding the engine
#: computes and no human has flagged.
ROSTER = sheet([GOOD])
DISAGREEING = {
    "name": "FA.pdf",
    "packets": [_packet(0, "Người 1", "079303009457", None, None)],
}
DISAGREEING_MANIFESTS = {
    0: _manifest(
        [_doc("contract-0", "contract", "Hợp đồng dịch vụ")],
        [("hoten", "Họ tên", "person", "Người 1",
          [_src("contract-0", "Ai Đó Khác")])],
    ),
}


class TestTheEngineFindingsReachTheReport:
    def test_without_a_roster_the_report_is_unchanged(self):
        """Existing callers pass no roster and must see exactly what they did."""
        plain = build_report(CASE, MANIFESTS, generated_at="t")
        assert [g["name"] for g in plain["groups"]] == ["Lê Thị Mai Anh",
                                                        "Trần Minh Khoa"]
        assert "criteria" not in plain

    def test_a_packet_with_only_engine_findings_is_reported(self):
        """No human has flagged anything here. The old report said nothing."""
        plain = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t")
        assert plain["groups"] == []

        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                            roster_rows=ROSTER)

        assert len(full["groups"]) == 1
        assert full["groups"][0]["criteria"]

    def test_a_finding_names_the_criterion_the_document_and_both_values(self):
        """Acc's rule: "phải nêu trường sai, giá trị tại từng chứng từ, chênh
        lệch và nội dung cần kiểm tra lại"."""
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                            roster_rows=ROSTER)
        finding = next(c for c in full["groups"][0]["criteria"] if c["stt"] == 1)

        assert finding["label"] == "Họ và tên"
        assert finding["status"] == "no"
        cell = next(c for c in finding["cells"] if c["document"] == "Hợp đồng")
        assert cell["value"] == "Ai Đó Khác"
        assert "Người 1" in cell["note"]

    def test_only_no_and_missing_are_listed_in_detail(self):
        """322 `rv` cells cannot go in a report as prose — they are counted."""
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                            roster_rows=ROSTER)
        group = full["groups"][0]

        assert {c["status"] for c in group["criteria"]} <= {"no", "missing"}
        assert group["criteriaCounts"]["rv"] > 0
        assert sum(group["criteriaCounts"].values()) == 25

    def test_the_roster_level_criteria_are_a_batch_section(self):
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                            roster_rows=ROSTER)

        assert [c["stt"] for c in full["summary"]["criteria"]] == [20, 26, 30, 31, 32]

    def test_the_markdown_states_the_findings(self):
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                            roster_rows=ROSTER)
        md = full["markdown"]

        assert "Họ và tên" in md
        assert "Ai Đó Khác" in md
        assert "Kiểm tra toàn bảng kê" in md

    def test_the_csv_carries_a_row_per_finding(self):
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                            roster_rows=ROSTER)
        lines = full["csv"].splitlines()

        assert any("Họ và tên" in ln and "Ai Đó Khác" in ln for ln in lines[1:])

    def test_a_clean_packet_is_still_excluded(self):
        clean = {
            "name": "FA.pdf",
            "packets": [_packet(0, "Người 1", "079303009457", None, None)],
        }
        manifests = {0: _manifest(
            [_doc("contract-0", "contract", "Hợp đồng dịch vụ"),
             _doc("bbnt-0", "bbnt", "BBNT"),
             _doc("appendix-0", "appendix", "Phụ lục"),
             _doc("pit-0", "pit", "Tra cứu thuế"),
             _doc("commitment-0", "commitment", "Cam kết"),
             _doc("id_front-0", "id_front", "CCCD"),
             _doc("id_back-0", "id_back", "CCCD sau")],
            [("hoten", "Họ tên", "person", "Người 1",
              [_src("contract-0", "Người 1"), _src("bbnt-0", "Người 1")])],
        )}

        full = build_report(clean, manifests, generated_at="t",
                            roster_rows=ROSTER)

        # every criterion is ok, rv or pending — nothing to send back
        assert full["groups"] == [] or not full["groups"][0]["criteria"]

    def test_the_purchase_total_reaches_the_batch_section(self):
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                            roster_rows=ROSTER,
                            purchase_total={"gross": 10_000_000})
        twenty = next(c for c in full["summary"]["criteria"] if c["stt"] == 20)

        assert twenty["status"] == "ok"


class TestAMissingDocumentIsOneFactNotFive:
    """On the real July case the engine's findings rendered as 175 lines saying
    40 things: `Hồ sơ thiếu CCCD/Passport` repeated under every criterion that
    spans that document. 135 of 175 lines were repeats.

    "You did not send this document" and "this document disagrees with the bảng
    kê" are different findings, and the CTV team acts differently on each: one
    is attach the file, the other is check the value.
    """

    def _packet_missing_everything(self):
        case = {"name": "FA.pdf",
                "packets": [_packet(0, "Người 1", "079303009457", None, None)]}
        manifests = {0: _manifest(
            [_doc("contract-0", "contract", "Hợp đồng dịch vụ")],
            [("hoten", "Họ tên", "person", "Người 1",
              [_src("contract-0", "Người 1")])],
        )}
        return build_report(case, manifests, generated_at="t",
                            roster_rows=ROSTER)

    def test_each_absent_document_is_reported_once(self):
        group = self._packet_missing_everything()["groups"][0]

        documents = [m["document"] for m in group["missingDocuments"]]
        assert len(documents) == len(set(documents))

    def test_it_names_which_criteria_the_absence_blocks(self):
        group = self._packet_missing_everything()["groups"][0]
        cccd = next(m for m in group["missingDocuments"]
                    if m["document"] == "CCCD/Passport")

        # #01 name, #02 CCCD, #03 dob, #04 gender all span the card
        assert set(cccd["criteria"]) >= {1, 2, 3, 4}
        assert len(cccd["criteria"]) > 1

    def test_the_criteria_list_keeps_only_real_disagreements(self):
        group = self._packet_missing_everything()["groups"][0]

        assert all(c["status"] == "no" for c in group["criteria"])

    def test_a_disagreement_is_still_reported_in_full(self):
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS,
                            generated_at="t", roster_rows=ROSTER)
        group = full["groups"][0]

        name = next(c for c in group["criteria"] if c["stt"] == 1)
        cell = next(c for c in name["cells"] if c["document"] == "Hợp đồng")
        assert cell["value"] == "Ai Đó Khác"
        assert "Người 1" in cell["note"]

    def test_the_markdown_lists_an_absence_once(self):
        md = self._packet_missing_everything()["markdown"]

        assert md.count("CCCD/Passport") == 1

    def test_the_markdown_says_what_the_absence_blocks(self):
        md = self._packet_missing_everything()["markdown"]

        assert "Thiếu chứng từ" in md
        assert "#01" in md or "#1" in md

    def test_the_csv_has_one_row_per_absent_document(self):
        report = self._packet_missing_everything()
        rows = [ln for ln in report["csv"].splitlines()
                if "CCCD/Passport" in ln]

        assert len(rows) == 1

    def test_a_packet_missing_nothing_has_no_such_section(self):
        full = build_report(DISAGREEING, DISAGREEING_MANIFESTS,
                            generated_at="t", roster_rows=ROSTER)
        group = full["groups"][0]

        # this packet has a contract only, so documents *are* missing
        assert isinstance(group["missingDocuments"], list)

    def test_without_a_roster_there_is_no_such_section(self):
        plain = build_report(CASE, MANIFESTS, generated_at="t")
        assert "missingDocuments" not in plain["groups"][0]


def test_a_read_value_is_separated_from_its_note():
    """`đọc được "X" Không khớp...` runs the value into the sentence."""
    full = build_report(DISAGREEING, DISAGREEING_MANIFESTS, generated_at="t",
                       roster_rows=ROSTER)
    line = next(ln for ln in full["markdown"].splitlines()
                if "Ai Đó Khác" in ln)
    assert 'đọc được "Ai Đó Khác" —' in line
