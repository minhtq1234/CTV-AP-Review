from fastapi.testclient import TestClient
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

def _fake_pipeline(pdf, roster, out_dir, cb):
    cb("done", 1, 1, "")
    return {"summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{"index": 0, "name": "P0", "pages": [8, 15],
                         "confidence": "green", "flags": [], "labels": []}]}

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

if __name__ == "__main__":
    # minimal manual runner (monkeypatch/tmp_path tests need pytest; run those with: python3 -m pytest server/app_test.py)
    test_rewrite_manifest_urls_points_pages_at_api(); print("  ok rewrite")
    test_post_requires_pdf(); print("  ok requires-pdf")
    test_page_endpoint_rejects_traversal(); print("  ok traversal")
    test_get_unknown_case_404(); print("  ok get-unknown-404")
    test_review_unknown_case_404(); print("  ok review-unknown-404")
    print("BASIC OK (run monkeypatch tests via pytest)")
