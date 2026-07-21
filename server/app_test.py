from fastapi.testclient import TestClient
import app as appmod
from app import app, rewrite_manifest_urls

def test_rewrite_manifest_urls_points_pages_at_api():
    m = {"docs": [{"pages": [{"src": "/abs/whatever/pg0.png", "width": 10, "height": 20}]}]}
    out = rewrite_manifest_urls(m, "/api/jobs/J/packets/0")
    assert out["docs"][0]["pages"][0]["src"] == "/api/jobs/J/packets/0/page/pg0.png"

def test_post_job_requires_pdf():
    c = TestClient(app)
    assert c.post("/api/jobs").status_code == 422

def test_post_job_then_poll_with_fake_pipeline(monkeypatch):
    # inject a fake pipeline so no real PDF/OCR is needed
    def fake_run(pdf, roster, job_dir, cb):
        cb("done", 1, 1, ""); return {"summary": {"found": 1}, "packets": [{"index":0,"name":"X","pages":[0,7]}]}
    monkeypatch.setattr(appmod, "run_pipeline", fake_run)
    c = TestClient(app)
    r = c.post("/api/jobs", files={"pdf": ("a.pdf", b"%PDF-1.4 fake", "application/pdf")})
    assert r.status_code == 200
    jid = r.json()["job_id"]
    import time
    for _ in range(100):
        s = c.get(f"/api/jobs/{jid}").json()
        if s["status"] in ("done","error"): break
        time.sleep(0.02)
    assert s["status"] == "done" and s["result"]["summary"]["found"] == 1

def test_page_endpoint_rejects_traversal():
    c = TestClient(app)
    assert c.get("/api/jobs/nope/packets/0/page/..%2f..%2fetc%2fpasswd").status_code in (400, 404)

if __name__ == "__main__":
    # minimal manual runner (monkeypatch tests need pytest; run those with: python3 -m pytest server/app_test.py)
    test_rewrite_manifest_urls_points_pages_at_api(); print("  ok rewrite")
    test_post_job_requires_pdf(); print("  ok requires-pdf")
    test_page_endpoint_rejects_traversal(); print("  ok traversal")
    print("BASIC OK (run monkeypatch tests via pytest)")
