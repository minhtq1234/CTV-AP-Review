from fastapi.testclient import TestClient
import io
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
    worksheet.append(["Họ và tên", "Số CCCD"])
    worksheet.append(["Synthetic A", "000000000001"])
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
    assert seen["cccd"].endswith("/cccd.xlsx")
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


def _case_with_roster(monkeypatch, tmp_path, roster_bytes):
    monkeypatch.setattr(appmod, "run_pipeline", _fake_pipeline)
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
