from fastapi.testclient import TestClient
import io
import pathlib
import json
import os
import time

import openpyxl

import app as appmod
from app import app, rewrite_manifest_urls

def test_rewrite_manifest_urls_points_pages_at_api():
    m = {"docs": [{"pages": [{"src": "/abs/whatever/pg0.png", "width": 10, "height": 20}]}]}
    out = rewrite_manifest_urls(m, "/api/cases/C/packets/0")
    assert out["docs"][0]["pages"][0]["src"] == "/api/cases/C/packets/0/page/pg0.png"

def test_post_requires_pdf():
    assert TestClient(app).post("/api/cases").status_code == 422

def test_page_endpoint_rejects_traversal():
    c = TestClient(app)
    assert c.get("/api/cases/nope/packets/0/page/..%2f..%2fetc%2fpasswd").status_code in (400, 404)


def test_page_endpoint_serves_attached_jpeg(tmp_path, monkeypatch):
    client, cid = _ready_case(monkeypatch, tmp_path)
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True, exist_ok=True)
    (packet_dir / "cccd-front.jpg").write_bytes(b"\xff\xd8\xff\xd9")

    response = client.get(
        f"/api/cases/{cid}/packets/0/page/cccd-front.jpg",
    )

    assert response.status_code == 200

def _fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
    cb("done", 1, 1, "")
    return {"summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{"index": 0, "name": "P0", "pages": [8, 15],
                         "confidence": "green", "flags": [], "labels": []}],
            "cccdWorkbook": None}


def _roster_bytes():
    content = io.BytesIO()
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.append(["Họ và tên", "Số CCCD", "Gross"])
    worksheet.append(["Synthetic A", "000000000001", 8000000])
    workbook.save(content)
    workbook.close()
    return content.getvalue()

def _ready_case(monkeypatch, tmp_path):
    """Mirror the app's real flow: monkeypatch the pipeline to a fake that
    returns one packet, POST a case, and poll until it leaves `processing`."""
    monkeypatch.setattr(appmod, "run_pipeline", _fake_pipeline)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    c = TestClient(app)
    r = c.post("/api/cases", files={"pdf": ("feb.pdf", b"%PDF-1.4 x", "application/pdf")})
    cid = r.json()["case_id"]; assert r.status_code == 200
    import time
    for _ in range(100):
        d = c.get(f"/api/cases/{cid}").json()
        if d["status"] in ("ready", "in_review", "done", "error"): break
        time.sleep(0.02)
    assert d["status"] == "ready" and len(d["packets"]) == 1
    return c, cid

def test_case_create_list_detail_review(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    assert c.get("/api/cases").json()[0]["id"] == cid
    # review persists + flips status
    r = c.put(f"/api/cases/{cid}/packets/0/review", json={"done": True, "fields": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["packet"]["review"]["done"] is True
    assert data["progress"]["done"] == 1
    assert c.get(f"/api/cases/{cid}").json()["status"] == "done"
    # delete
    assert c.delete(f"/api/cases/{cid}").status_code == 200
    assert c.get("/api/cases").json() == []

def test_case_and_review_responses_derive_field_count_without_persisting(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text(json.dumps({
        "fields": [{"key": "synthetic-a"}, {"key": "synthetic-b"}],
    }), encoding="utf-8")

    detail = c.get(f"/api/cases/{cid}").json()
    assert detail["packets"][0]["reviewFieldCount"] == 2

    updated = c.put(
        f"/api/cases/{cid}/packets/0/review",
        json={"done": False, "fields": {}, "rejection": None},
    ).json()
    assert updated["packet"]["reviewFieldCount"] == 2
    assert "reviewFieldCount" not in appmod.store.get(cid)["packets"][0]

def test_case_response_uses_zero_field_count_when_manifest_is_missing(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    detail = c.get(f"/api/cases/{cid}").json()
    assert detail["packets"][0]["reviewFieldCount"] == 0

def test_case_response_uses_zero_field_count_for_non_object_manifest(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    packet_dir = tmp_path / cid / "packets" / "0"
    packet_dir.mkdir(parents=True)
    (packet_dir / "manifest.json").write_text("[]", encoding="utf-8")

    detail = c.get(f"/api/cases/{cid}")
    assert detail.status_code == 200
    assert detail.json()["packets"][0]["reviewFieldCount"] == 0

def test_get_unknown_case_404():
    assert TestClient(app).get("/api/cases/nope").status_code == 404

def test_review_unknown_case_404():
    body = {"done": True, "fields": {}}
    assert TestClient(app).put("/api/cases/nope/packets/0/review", json=body).status_code == 404

def test_put_review_persists_and_updates_status(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    body = {"done": True, "fields": {"cccd": {"seen": True,
            "flag": {"reason": "sai", "note": "x"}}}}
    r = c.put(f"/api/cases/{cid}/packets/0/review", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["packet"]["review"]["done"] is True
    assert data["progress"]["done"] >= 1

def test_put_review_defaults_rejection_to_null(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    r = c.put(f"/api/cases/{cid}/packets/0/review",
              json={"done": False, "fields": {}})
    assert r.status_code == 200
    assert r.json()["packet"]["review"]["rejection"] is None

def test_put_review_validates_and_roundtrips_multiple_rejection_reasons(
        tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    url = f"/api/cases/{cid}/packets/0/review"
    assert c.put(url, json={
        "done": False, "fields": {},
        "rejection": {"reasons": [], "note": ""},
    }).status_code == 422
    assert c.put(url, json={
        "done": False, "fields": {},
        "rejection": {"reasons": ["not_a_reason"], "note": ""},
    }).status_code == 422

    r = c.put(url, json={
        "done": False,
        "fields": {"name": {"seen": True, "flag": None}},
        "rejection": {
            "reasons": ["missing_signature", "missing_documents"],
            "note": "  bổ sung  ",
        },
    })
    assert r.status_code == 200
    assert r.json()["packet"]["review"] == {
        "done": True,
        "fields": {"name": {"seen": True, "flag": None}},
        "rejection": {
            "reasons": ["missing_documents", "missing_signature"],
            "note": "bổ sung",
        },
        # criteria-cell decisions live here; none recorded on this packet
        "overrides": {},
    }

def test_report_endpoint_generates_and_persists(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    c.put(f"/api/cases/{cid}/packets/0/review",
          json={"done": True, "fields": {"cccd": {"seen": True,
                "flag": {"reason": "sai", "note": "x"}}}})
    r = c.post(f"/api/cases/{cid}/report")
    assert r.status_code == 200
    assert "markdown" in r.json()
    md = c.get(f"/api/cases/{cid}/report.md")
    assert md.status_code == 200 and "Báo cáo" in md.text
    csv = c.get(f"/api/cases/{cid}/report.csv")
    assert csv.status_code == 200 and csv.text.startswith("CTV,CCCD,")

def test_report_404_before_generation(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    assert c.get(f"/api/cases/{cid}/report.md").status_code == 404
    assert c.get(f"/api/cases/{cid}/report.csv").status_code == 404


def test_cccd_without_roster_returns_422_and_creates_no_case(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))

    response = TestClient(app).post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "cccd": (
                "cards.xlsx",
                b"synthetic-not-read",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "cccd-requires-roster"
    assert list(tmp_path.iterdir()) == []


def test_invalid_cccd_extension_is_rejected_before_case_creation(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))

    response = TestClient(app).post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "roster": (
                "roster.xlsx",
                _roster_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "cccd": ("cards.xls", b"synthetic", "application/octet-stream"),
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid-cccd-workbook"
    assert list(tmp_path.iterdir()) == []


def test_a_combined_workbook_alone_is_also_used_as_the_card_source(
    tmp_path,
    monkeypatch,
):
    """One file, one upload. The combined template is both the bảng kê and the
    card source, and a reviewer who selects it once should not have to know to
    select it again in the CCCD field -- doing that silently ingested no cards at
    all, so every packet reported CCCD/Passport missing."""
    from test_fixtures import combined_workbook

    built = str(tmp_path / "combined.xlsx")
    combined_workbook.build(built)
    combined_bytes = pathlib.Path(built).read_bytes()

    seen = {}

    def fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
        seen["cccd"] = cccd_xlsx_path
        seen["roster"] = roster
        cb("done", 1, 1, "")
        return {
            "summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{"index": 0, "name": "P0", "pages": [0, 1],
                         "confidence": "green", "flags": [], "labels": []}],
        }

    monkeypatch.setattr(appmod, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path / "store")))
    client = TestClient(app)
    response = client.post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "roster": (
                "combined.xlsx",
                combined_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 200
    cid = response.json()["case_id"]
    for _ in range(100):
        detail = client.get(f"/api/cases/{cid}").json()
        if detail["status"] != "processing":
            break
        time.sleep(.02)

    # Same stored file in both roles -- not a second 18 MB copy.
    assert seen["cccd"] == seen["roster"]
    assert seen["cccd"] is not None


def test_a_plain_roster_alone_is_not_treated_as_a_card_source(
    tmp_path,
    monkeypatch,
):
    """The older single-sheet bảng kê holds no card images, so nothing changes
    for it -- the card stage stays off rather than walking a workbook that has
    nothing in it."""
    seen = {}

    def fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
        seen["cccd"] = cccd_xlsx_path
        cb("done", 1, 1, "")
        return {
            "summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{"index": 0, "name": "P0", "pages": [0, 1],
                         "confidence": "green", "flags": [], "labels": []}],
        }

    monkeypatch.setattr(appmod, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    client = TestClient(app)
    response = client.post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "roster": (
                "roster.xlsx",
                _roster_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )

    assert response.status_code == 200
    cid = response.json()["case_id"]
    for _ in range(100):
        detail = client.get(f"/api/cases/{cid}").json()
        if detail["status"] != "processing":
            break
        time.sleep(.02)

    assert seen["cccd"] is None


def test_valid_cccd_upload_is_saved_passed_to_pipeline_and_redacted(
    tmp_path,
    monkeypatch,
):
    seen = {}
    workbook = {
        "status": "ready",
        "summary": {"candidates": 3, "attached": 2, "unresolved": 1},
        "mappings": [{
            "candidateId": "card-private",
            "ocrIdentity": {"cccd": "000000000001"},
        }],
    }

    def fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
        seen["cccd"] = cccd_xlsx_path
        seen["cccd_exists"] = os.path.isfile(cccd_xlsx_path)
        cb("done", 1, 1, "")
        return {
            "summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{
                "index": 0,
                "name": "P0",
                "pages": [0, 1],
                "confidence": "green",
                "flags": [],
                "labels": [],
            }],
            "cccdWorkbook": workbook,
        }

    monkeypatch.setattr(appmod, "run_pipeline", fake_pipeline)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    client = TestClient(app)
    response = client.post(
        "/api/cases",
        files={
            "pdf": ("packet.pdf", b"%PDF-1.4 synthetic", "application/pdf"),
            "roster": (
                "roster.xlsx",
                _roster_bytes(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
            "cccd": (
                "cards.xlsx",
                b"synthetic-workbook",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ),
        },
    )
    assert response.status_code == 200
    cid = response.json()["case_id"]
    for _ in range(100):
        detail = client.get(f"/api/cases/{cid}").json()
        if detail["status"] != "processing":
            break
        time.sleep(.02)

    assert detail["status"] == "ready"
    assert seen["cccd_exists"] is True
    assert os.path.basename(seen["cccd"]) == "cccd.xlsx"
    assert detail["cccdName"] == "cards.xlsx"
    assert detail["cccdSummary"] == {
        "status": "ready",
        "candidates": 3,
        "attached": 2,
        "unresolved": 1,
    }
    assert "cccdWorkbook" not in detail
    assert "card-private" not in json.dumps(detail)

if __name__ == "__main__":
    # minimal manual runner (monkeypatch/tmp_path tests need pytest; run those with: python3 -m pytest server/app_test.py)
    test_rewrite_manifest_urls_points_pages_at_api(); print("  ok rewrite")
    test_post_requires_pdf(); print("  ok requires-pdf")
    test_page_endpoint_rejects_traversal(); print("  ok traversal")
    test_get_unknown_case_404(); print("  ok get-unknown-404")
    test_review_unknown_case_404(); print("  ok review-unknown-404")
    print("BASIC OK (run monkeypatch tests via pytest)")


def _bang_ke_bytes(people=((1, "079303009457", 10_000_000, 1_000_000, 9_000_000),)):
    """A roster shaped like Acc's real one, as an actual workbook."""
    content = io.BytesIO()
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.append(["THANH TOÁN DỊCH VỤ CTV"])
    sheet.append(["STT", "Họ và Tên", "Số CCCD", "MST", "Ngày Tháng Năm Sinh",
                  "Giới Tính", "Số TK", "Ngân Hàng", "Thời gian làm việc",
                  "Phí dịch vụ", "Chi Phí\n(+ PIT)", "", "", "", "Note"])
    # "Gross (1)" must sit under "Chi Phí (+ PIT)" at index 10, as it does on
    # the real bảng kê -- the money columns are named on the second header row.
    sheet.append([""] * 10 + ["Gross (1)", "Bản cam kết", "Thuế PIT (2)",
                              "Thực Nhận\n(3 = 1-2)"])
    for stt, cccd, gross, pit, net in people:
        sheet.append([stt, f"Người {stt}", cccd, cccd, "03/09/2003", "Nam",
                      "0081001142415", "Bank", "01/07 - 25/07/2026", gross,
                      gross, "không", pit, net, ""])
    workbook.save(content)
    workbook.close()
    return content.getvalue()


def _fake_pipeline_matched(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
    """As `_fake_pipeline`, but the packet matched a roster row — which is what
    the criteria matrix needs in order to have a reference column."""
    cb("done", 1, 1, "")
    return {"summary": {"found": 1, "roster_n": 1, "matched": 1,
                        "auto_merged": 0},
            "packets": [{"index": 0, "name": "Người 1", "pages": [8, 15],
                         "confidence": "green", "flags": [], "labels": [],
                         "matchedBy": "cccd",
                         "rosterIdentity": {"cccd": "079303009457",
                                            "name": "Người 1"}}],
            "cccdWorkbook": None}


def _case_with_roster(monkeypatch, tmp_path, roster_bytes):
    monkeypatch.setattr(appmod, "run_pipeline", _fake_pipeline_matched)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    c = TestClient(app)
    r = c.post(
        "/api/cases",
        files={"pdf": ("jul.pdf", b"%PDF-1.4 x", "application/pdf"),
               "roster": ("bangke.xlsx", roster_bytes,
                          "application/vnd.openxmlformats-officedocument."
                          "spreadsheetml.sheet")},
    )
    assert r.status_code == 200, r.text
    cid = r.json()["case_id"]
    for _ in range(100):
        d = c.get(f"/api/cases/{cid}").json()
        if d["status"] in ("ready", "in_review", "done", "error"):
            break
        time.sleep(0.02)
    assert d["status"] == "ready", d
    return c, cid


class TestSummaryEndpoint:
    def test_unknown_case_is_not_found(self):
        assert TestClient(app).get("/api/cases/nope/summary").status_code == 404

    def test_it_returns_the_five_roster_level_criteria(self, tmp_path, monkeypatch):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())

        body = c.get(f"/api/cases/{cid}/summary").json()

        assert [x["stt"] for x in body["criteria"]] == [20, 26, 30, 31, 32]
        assert body["people"] == 1
        assert body["rosterName"] == "bangke.xlsx"

    def test_every_criterion_carries_accs_instruction(self, tmp_path, monkeypatch):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())

        body = c.get(f"/api/cases/{cid}/summary").json()

        for item in body["criteria"]:
            assert len(item["how"]) > 40, item["stt"]
            assert item["message"]

    def test_the_duplicate_check_reads_the_real_roster(self, tmp_path, monkeypatch):
        twins = ((1, "079303009457", 10_000_000, 1_000_000, 9_000_000),
                 (2, "079303009457", 5_000_000, 500_000, 4_500_000))
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes(twins))

        body = c.get(f"/api/cases/{cid}/summary").json()
        thirty = next(x for x in body["criteria"] if x["stt"] == 30)

        assert thirty["status"] == "no"
        assert any("dòng 1+2" in d for d in thirty["detail"])

    def test_a_case_with_no_roster_is_pending_not_clean(self, tmp_path, monkeypatch):
        c, cid = _ready_case(monkeypatch, tmp_path)

        body = c.get(f"/api/cases/{cid}/summary").json()

        assert body["counts"]["ok"] == 0
        assert "rosterRows" in body["missing"]
        assert body["rosterName"] is None

    def test_the_purchase_listing_total_is_used_when_the_case_has_one(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        appmod.store.set_purchase_total(cid, {"gross": 10_000_000})

        body = c.get(f"/api/cases/{cid}/summary").json()
        twenty = next(x for x in body["criteria"] if x["stt"] == 20)

        assert twenty["status"] == "ok"
        assert "purchaseTotal" not in body["missing"]


def _write_manifest(tmp_path, cid, index, name_in_contract="Người 1"):
    """A packet manifest on disk, as the pipeline would have written it."""
    packet_dir = tmp_path / cid / "packets" / str(index)
    packet_dir.mkdir(parents=True, exist_ok=True)
    manifest = {
        "id": "p", "name": "Người 1", "product": "",
        "docs": [{"id": "contract-0", "kind": "contract",
                  "label": "Hợp đồng dịch vụ", "pages": []}],
        "fields": [{"key": "hoten", "expected": "Người 1", "sources": [
            {"docId": "contract-0", "page": 0, "value": name_in_contract,
             "confidence": 0.95,
             "bbox": {"x": 1, "y": 2, "width": 3, "height": 4}},
        ]}],
    }
    with open(packet_dir / "manifest.json", "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)


class TestCriteriaEndpoint:
    def test_unknown_case_is_not_found(self):
        assert TestClient(app).get(
            "/api/cases/nope/packets/0/criteria",
        ).status_code == 404

    def test_unknown_packet_is_not_found(self, tmp_path, monkeypatch):
        c, cid = _ready_case(monkeypatch, tmp_path)
        assert c.get(f"/api/cases/{cid}/packets/99/criteria").status_code == 404

    def test_it_returns_the_matrix_for_a_packet(self, tmp_path, monkeypatch):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0)

        body = c.get(f"/api/cases/{cid}/packets/0/criteria").json()

        assert len(body["criteria"]) == 25
        assert body["documents"][0] == "Excel"
        assert sum(body["counts"].values()) == 25

    def test_it_reads_the_roster_row_the_packet_matched(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0)

        body = c.get(f"/api/cases/{cid}/packets/0/criteria").json()
        name = next(x for x in body["criteria"] if x["stt"] == 1)
        excel = next(x for x in name["cells"] if x["document"] == "Excel")

        assert body["matchedRoster"] is True
        assert excel["value"] == "Người 1"

    def test_a_packet_matching_nobody_still_returns_a_matrix(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _ready_case(monkeypatch, tmp_path)
        _write_manifest(tmp_path, cid, 0)

        body = c.get(f"/api/cases/{cid}/packets/0/criteria").json()

        assert body["matchedRoster"] is False
        assert body["counts"]["ok"] == 0
        assert len(body["criteria"]) == 25

    def test_a_packet_with_no_manifest_yet_is_not_found(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _ready_case(monkeypatch, tmp_path)
        assert c.get(f"/api/cases/{cid}/packets/0/criteria").status_code == 404

    def test_the_findings_carry_both_values(self, tmp_path, monkeypatch):
        """A document naming a different CTV must state what it says and what
        the bảng kê says."""
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0, name_in_contract="Ai Đó Khác")

        body = c.get(f"/api/cases/{cid}/packets/0/criteria").json()
        name = next(x for x in body["criteria"] if x["stt"] == 1)
        contract = next(x for x in name["cells"] if x["document"] == "Hợp đồng")

        assert contract["status"] == "no"
        assert contract["value"] == "Ai Đó Khác"
        assert "Người 1" in contract["note"]


class TestTheReportCarriesTheEngineFindings:
    def test_the_report_includes_the_roster_level_section(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0, name_in_contract="Ai Đó Khác")

        body = c.post(f"/api/cases/{cid}/report").json()

        assert [x["stt"] for x in body["summary"]["criteria"]] == [20, 26, 30, 31, 32]

    def test_an_engine_finding_reaches_the_report_with_no_human_flag(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0, name_in_contract="Ai Đó Khác")

        body = c.post(f"/api/cases/{cid}/report").json()

        assert len(body["groups"]) == 1
        names = [c_["label"] for c_ in body["groups"][0]["criteria"]]
        assert "Họ và tên" in names
        assert "Ai Đó Khác" in body["markdown"]

    def test_a_case_with_no_roster_still_reports(self, tmp_path, monkeypatch):
        c, cid = _ready_case(monkeypatch, tmp_path)

        body = c.post(f"/api/cases/{cid}/report").json()

        assert "summary" not in body
        assert "markdown" in body

    def test_the_markdown_download_carries_the_findings(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0, name_in_contract="Ai Đó Khác")
        c.post(f"/api/cases/{cid}/report")

        text = c.get(f"/api/cases/{cid}/report.md").text

        assert "Kiểm tra toàn bảng kê" in text
        assert "Ai Đó Khác" in text


class TestRecordingADecisionOverHttp:
    """The backend loop end to end: a decision goes in over HTTP, is persisted
    with its audit record, and comes back out of GET /criteria."""

    def _decide(self, client, cid, **body):
        return client.put(f"/api/cases/{cid}/packets/0/criteria/21:Hợp đồng",
                          json={"toStatus": "ok",
                                "reason": "đã xem chữ ký, đúng CTV", **body})

    def _ready(self, monkeypatch, tmp_path):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0)
        return c, cid

    def test_a_decision_changes_the_cell(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        before = c.get(f"/api/cases/{cid}/packets/0/criteria").json()
        assert next(x for x in before["criteria"]
                    if x["stt"] == 21)["status"] == "rv"

        assert self._decide(c, cid).status_code == 200

        after = c.get(f"/api/cases/{cid}/packets/0/criteria").json()
        row = next(x for x in after["criteria"] if x["stt"] == 21)
        assert row["status"] == "ok"

    def test_the_cell_keeps_what_the_engine_computed(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        self._decide(c, cid)

        after = c.get(f"/api/cases/{cid}/packets/0/criteria").json()
        cell = next(x for x in next(r for r in after["criteria"]
                                    if r["stt"] == 21)["cells"]
                    if x["document"] == "Hợp đồng")

        assert cell["status"] == "ok"
        assert cell["computedStatus"] == "rv"

    def test_the_reason_reaches_the_cell_note(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        self._decide(c, cid)

        after = c.get(f"/api/cases/{cid}/packets/0/criteria").json()
        cell = next(x for x in next(r for r in after["criteria"]
                                    if r["stt"] == 21)["cells"]
                    if x["document"] == "Hợp đồng")

        assert "đã xem chữ ký, đúng CTV" in cell["note"]

    def test_the_engine_records_what_it_thought(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)

        body = self._decide(c, cid).json()

        assert body["override"]["fromStatus"] == "rv"
        assert body["override"]["toStatus"] == "ok"

    def test_it_is_stamped_with_a_time(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        body = self._decide(c, cid).json()
        assert body["override"]["at"]

    def test_the_author_is_empty_until_there_is_auth(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        assert self._decide(c, cid).json()["override"]["by"] == ""

    def test_deciding_again_appends_to_the_audit_trail(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        self._decide(c, cid)
        body = self._decide(c, cid, toStatus="no",
                            reason="xem lại, thiếu ký").json()

        assert len(body["history"]) == 2
        assert body["history"][0]["toStatus"] == "ok"
        assert body["history"][1]["toStatus"] == "no"

    def test_a_decision_needs_no_reason(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)

        r = c.put(f"/api/cases/{cid}/packets/0/criteria/21:Hợp đồng",
                  json={"toStatus": "ok"})

        assert r.status_code == 200
        assert r.json()["override"]["reason"] == ""

    def test_the_note_closes_cleanly_with_no_reason(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        c.put(f"/api/cases/{cid}/packets/0/criteria/21:Hợp đồng",
              json={"toStatus": "ok"})

        after = c.get(f"/api/cases/{cid}/packets/0/criteria").json()
        note = next(x for x in next(r for r in after["criteria"]
                                    if r["stt"] == 21)["cells"]
                    if x["document"] == "Hợp đồng")["note"]

        assert note.rstrip().endswith('"Đạt".')
        assert ": ." not in note

    def test_an_unknown_status_is_refused(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        assert self._decide(c, cid, toStatus="maybe").status_code == 422

    def test_na_is_refused(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        assert self._decide(c, cid, toStatus="na").status_code == 422

    def test_a_document_outside_the_criterion_is_refused(
        self, tmp_path, monkeypatch,
    ):
        c, cid = self._ready(monkeypatch, tmp_path)
        r = c.put(f"/api/cases/{cid}/packets/0/criteria/21:Excel",
                  json={"toStatus": "ok", "reason": "x"})
        assert r.status_code == 422

    def test_a_roster_level_criterion_is_refused(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        r = c.put(f"/api/cases/{cid}/packets/0/criteria/20:Excel",
                  json={"toStatus": "ok", "reason": "x"})
        assert r.status_code == 422

    def test_a_malformed_key_is_refused(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        for key in ("nonsense", "21", ":Excel", "aa:Excel"):
            r = c.put(f"/api/cases/{cid}/packets/0/criteria/{key}",
                      json={"toStatus": "ok", "reason": "x"})
            assert r.status_code == 422, key

    def test_an_unknown_case_or_packet_is_not_found(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        assert c.put("/api/cases/nope/packets/0/criteria/21:Hợp đồng",
                     json={"toStatus": "ok", "reason": "x"}).status_code == 404
        assert c.put(f"/api/cases/{cid}/packets/9/criteria/21:Hợp đồng",
                     json={"toStatus": "ok", "reason": "x"}).status_code == 404

    def test_the_decision_survives_a_store_reload(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path)
        self._decide(c, cid)

        monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
        after = c.get(f"/api/cases/{cid}/packets/0/criteria").json()

        assert next(x for x in after["criteria"] if x["stt"] == 21)["status"] == "ok"

    def test_the_report_reflects_the_decision(self, tmp_path, monkeypatch):
        """A recorded decision that never reaches the report is the failure the
        whole checkpoint is about."""
        c, cid = self._ready(monkeypatch, tmp_path)
        c.put(f"/api/cases/{cid}/packets/0/criteria/23:BBNT",
              json={"toStatus": "no", "reason": "BBNT thiếu chữ ký CTV"})

        body = c.post(f"/api/cases/{cid}/report").json()
        found = [x for g in body["groups"] for x in g.get("criteria", [])
                 if x["stt"] == 23]

        assert found, "the reviewer's finding is missing from the report"
        assert "BBNT thiếu chữ ký CTV" in body["markdown"]


class TestCandidatesAreReportedSeparately:
    """Acc's rule: `cần gửi lại` counts what a person decided; the engine's own
    findings are candidates, surfaced separately so the two never contradict."""

    def _ready(self, monkeypatch, tmp_path, **kw):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0, **kw)
        return c, cid

    def test_a_packet_the_engine_flags_is_a_candidate_not_a_resubmit(
        self, tmp_path, monkeypatch,
    ):
        c, cid = self._ready(monkeypatch, tmp_path,
                             name_in_contract="Ai Đó Khác")

        body = c.get(f"/api/cases/{cid}").json()

        assert body["progress"]["flagged"] == 0
        assert body["progress"]["candidates"] == 1

    def test_the_packet_carries_its_own_finding_count(
        self, tmp_path, monkeypatch,
    ):
        c, cid = self._ready(monkeypatch, tmp_path,
                             name_in_contract="Ai Đó Khác")

        packet = c.get(f"/api/cases/{cid}").json()["packets"][0]

        assert packet["findingCount"] >= 1

    def test_a_decision_moves_it_into_the_resubmit_count(
        self, tmp_path, monkeypatch,
    ):
        c, cid = self._ready(monkeypatch, tmp_path)
        c.put(f"/api/cases/{cid}/packets/0/criteria/23:BBNT",
              json={"toStatus": "no"})

        body = c.get(f"/api/cases/{cid}").json()

        assert body["progress"]["flagged"] == 1

    def test_clearing_a_cell_does_not_count_as_resubmit(
        self, tmp_path, monkeypatch,
    ):
        c, cid = self._ready(monkeypatch, tmp_path)
        c.put(f"/api/cases/{cid}/packets/0/criteria/21:Hợp đồng",
              json={"toStatus": "ok"})

        body = c.get(f"/api/cases/{cid}").json()

        assert body["progress"]["flagged"] == 0

    def test_a_case_with_no_roster_reports_no_candidates(
        self, tmp_path, monkeypatch,
    ):
        c, cid = _ready_case(monkeypatch, tmp_path)

        body = c.get(f"/api/cases/{cid}").json()

        assert body["progress"]["candidates"] == 0
        assert body["packets"][0]["findingCount"] == 0

    def test_findings_and_resubmits_are_independent(self, tmp_path, monkeypatch):
        """This packet holds only a contract, so the engine legitimately finds
        15 absent documents — and none of them is a resubmission, because nobody
        has decided anything. That independence is the whole point of the split."""
        c, cid = self._ready(monkeypatch, tmp_path)

        body = c.get(f"/api/cases/{cid}").json()

        assert body["packets"][0]["findingCount"] > 0
        assert body["progress"]["candidates"] == 1
        assert body["progress"]["flagged"] == 0

    def test_the_list_endpoint_carries_it_too(self, tmp_path, monkeypatch):
        c, cid = self._ready(monkeypatch, tmp_path,
                             name_in_contract="Ai Đó Khác")

        row = next(x for x in c.get("/api/cases").json() if x["id"] == cid)

        assert "candidates" in row["progress"]


class TestACandidateStopsBeingOneOnceDecided:
    """A candidate is a finding *nobody has decided on*. Counting a decided one
    in both places would make the two numbers move together, which defeats
    separating them."""

    def _ready(self, monkeypatch, tmp_path, **kw):
        c, cid = _case_with_roster(monkeypatch, tmp_path, _bang_ke_bytes())
        _write_manifest(tmp_path, cid, 0, **kw)
        return c, cid

    def _counts(self, c, cid):
        body = c.get(f"/api/cases/{cid}").json()
        return body["progress"], body["packets"][0]["findingCount"]

    def test_confirming_the_engine_moves_a_finding_across(
        self, tmp_path, monkeypatch,
    ):
        """The reviewer agrees with a computed `no`. That is a conclusion, so it
        becomes a resubmission and stops being a candidate."""
        c, cid = self._ready(monkeypatch, tmp_path,
                             name_in_contract="Ai Đó Khác")
        before, findings_before = self._counts(c, cid)
        assert before["flagged"] == 0

        r = c.put(f"/api/cases/{cid}/packets/0/criteria/01:Hợp đồng",
                  json={"toStatus": "no"})
        assert r.status_code == 200
        assert r.json()["override"]["fromStatus"] == "no"   # a confirmation

        after, findings_after = self._counts(c, cid)
        assert after["flagged"] == 1
        assert findings_after == findings_before - 1

    def test_clearing_a_finding_also_removes_it_as_a_candidate(
        self, tmp_path, monkeypatch,
    ):
        c, cid = self._ready(monkeypatch, tmp_path,
                             name_in_contract="Ai Đó Khác")
        _, findings_before = self._counts(c, cid)

        c.put(f"/api/cases/{cid}/packets/0/criteria/01:Hợp đồng",
              json={"toStatus": "ok"})

        after, findings_after = self._counts(c, cid)
        assert after["flagged"] == 0          # cleared, not sent back
        assert findings_after == findings_before - 1

    def test_a_packet_stays_a_candidate_while_findings_remain(
        self, tmp_path, monkeypatch,
    ):
        c, cid = self._ready(monkeypatch, tmp_path,
                             name_in_contract="Ai Đó Khác")
        c.put(f"/api/cases/{cid}/packets/0/criteria/01:Hợp đồng",
              json={"toStatus": "no"})

        after, findings = self._counts(c, cid)

        assert findings > 0
        assert after["candidates"] == 1

    def test_the_two_counts_do_not_move_together(self, tmp_path, monkeypatch):
        """The point of the split: deciding something raises one and lowers the
        other, rather than raising both."""
        c, cid = self._ready(monkeypatch, tmp_path,
                             name_in_contract="Ai Đó Khác")
        before, findings_before = self._counts(c, cid)

        c.put(f"/api/cases/{cid}/packets/0/criteria/01:Hợp đồng",
              json={"toStatus": "no"})
        after, findings_after = self._counts(c, cid)

        assert after["flagged"] > before["flagged"]
        assert findings_after < findings_before
