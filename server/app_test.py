import json
import os
import time

from fastapi.testclient import TestClient
import app as appmod
import pipeline as pl
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

def _fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
    cb("done", 1, 1, "")
    return {
        "summary": {"found": 1, "roster_n": 1, "matched": 1, "auto_merged": 0},
        "packets": [{
            "index": 0,
            "name": "P0",
            "pages": [8, 15],
            "confidence": "green",
            "flags": [],
            "labels": [],
        }],
        "cccdWorkbook": (
            {
                "status": "ready",
                "summary": {"candidates": 1, "attached": 1, "unresolved": 0},
                "mappings": [{"candidateId": "private-candidate"}],
            }
            if cccd_xlsx_path else None
        ),
    }

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
    r = c.put(f"/api/cases/{cid}/packets/0/review", json={"done": True, "items": {}})
    assert r.status_code == 200
    data = r.json()
    assert data["packet"]["review"]["done"] is True
    assert data["progress"]["done"] == 1
    assert c.get(f"/api/cases/{cid}").json()["status"] == "done"
    # delete
    assert c.delete(f"/api/cases/{cid}").status_code == 200
    assert c.get("/api/cases").json() == []


def test_cccd_requires_roster_before_case_creation(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    response = TestClient(app).post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "cccd": ("cards.xlsx", b"xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "cccd-requires-roster"
    assert appmod.store.list() == []
    assert list(tmp_path.iterdir()) == []


def test_invalid_cccd_extension_creates_no_case(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    response = TestClient(app).post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "roster": ("roster.xlsx", b"roster", "application/octet-stream"),
        "cccd": ("cards.xls", b"old", "application/octet-stream"),
    })
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "invalid-cccd-workbook"
    assert appmod.store.list() == []


def test_oversized_cccd_creates_no_case(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    monkeypatch.setattr(appmod, "MAX_CCCD_WORKBOOK_BYTES", 3)
    response = TestClient(app).post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "roster": ("roster.xlsx", b"roster", "application/octet-stream"),
        "cccd": ("cards.xlsx", b"four", "application/octet-stream"),
    })
    assert response.status_code == 413
    assert response.json()["detail"]["code"] == "cccd-workbook-too-large"
    assert appmod.store.list() == []


def test_cccd_upload_is_saved_passed_and_detail_is_redacted(tmp_path, monkeypatch):
    seen = {}

    def fake(pdf, roster, out_dir, cb, cccd_xlsx_path=None):
        seen["cccd"] = cccd_xlsx_path
        return _fake_pipeline(pdf, roster, out_dir, cb, cccd_xlsx_path)

    monkeypatch.setattr(appmod, "run_pipeline", fake)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    client = TestClient(app)
    response = client.post("/api/cases", files={
        "pdf": ("input.pdf", b"%PDF-1.4", "application/pdf"),
        "roster": ("roster.xlsx", b"roster", "application/octet-stream"),
        "cccd": ("cards.xlsx", b"xlsx", "application/octet-stream"),
    })
    cid = response.json()["case_id"]
    for _ in range(100):
        detail = client.get(f"/api/cases/{cid}").json()
        if detail["status"] != "processing":
            break
        time.sleep(0.02)

    assert os.path.basename(seen["cccd"]) == "cccd.xlsx"
    assert os.path.isfile(os.path.join(appmod.store.case_dir(cid), "cccd.xlsx"))
    assert os.path.isfile(os.path.join(appmod.store.case_dir(cid), "roster.xlsx"))
    assert detail["cccdName"] == "cards.xlsx"
    assert detail["cccdSummary"] == {
        "status": "ready",
        "candidates": 1,
        "attached": 1,
        "unresolved": 0,
    }
    assert "cccdWorkbook" not in detail
    assert "private-candidate" not in json.dumps(detail)


def test_real_pipeline_bridge_accepts_legacy_cccd_none(tmp_path, monkeypatch):
    def fake_ocr_packet(pdf_path, start, end, out_dir):
        os.makedirs(out_dir, exist_ok=True)
        return {
            "folder": {"docs": [], "fields": []},
            "identity": {"cccd": "", "name": ""},
        }

    monkeypatch.setattr(pl.dp, "load_page_bands", lambda path: ([None], [1.0], [0.001], 1))
    monkeypatch.setattr(pl.dp, "seed_scores", lambda bands: ([0.0], 0))
    monkeypatch.setattr(pl.dp, "derive_threshold", lambda scores: 0.5)
    monkeypatch.setattr(pl.dp, "covers_from_scores", lambda scores, threshold: [0])
    monkeypatch.setattr(pl.dp, "prune_excess_covers", lambda covers, scores, roster_n: (covers, []))
    monkeypatch.setattr(pl.dp, "packets_from_covers", lambda covers, n: [(0, 0)])
    monkeypatch.setattr(pl.oc, "ocr_packet", fake_ocr_packet)
    monkeypatch.setattr(appmod, "run_pipeline", pl.run_pipeline)
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))

    cid = appmod.store.create("input.pdf", "input.pdf", None, now="2026-07-28T00:00:00Z")
    appmod._run_case(cid, str(tmp_path / "input.pdf"), None)

    case = appmod.store.get(cid)
    assert case["status"] == "ready"
    assert case["error"] is None
    assert case["cccdWorkbook"] is None

def test_get_unknown_case_404():
    assert TestClient(app).get("/api/cases/nope").status_code == 404

def test_review_unknown_case_404():
    body = {"done": True, "items": {}}
    assert TestClient(app).put("/api/cases/nope/packets/0/review", json=body).status_code == 404

def test_put_review_persists_and_updates_status(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    body = {"done": True, "items": {"A2": {"seen": True,
            "flag": {"reason": "sai", "note": "x"}}}}
    r = c.put(f"/api/cases/{cid}/packets/0/review", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["packet"]["review"]["done"] is True
    assert data["packet"]["review"]["items"]["A2"]["flag"]["reason"] == "sai"
    assert data["progress"]["done"] >= 1

def test_report_endpoint_generates_and_persists(tmp_path, monkeypatch):
    c, cid = _ready_case(monkeypatch, tmp_path)
    c.put(f"/api/cases/{cid}/packets/0/review",
          json={"done": True, "items": {"A2": {"seen": True,
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

def test_get_manifest_backfills_checks_when_missing(tmp_path, monkeypatch):
    """Manifests OCR'd before the coded-checklist feature landed have no
    `checks` array on disk. `_ready_case`'s fake pipeline (unlike the real
    one) never writes a manifest.json at all, so we seed one ourselves --
    with `fields`/`docs` but deliberately no `checks` -- to stand in for a
    pre-existing on-disk manifest, then strip `checks` the same way a real
    migration would before writing it back. GET must build the checklist
    on the fly rather than serving (and the UI rendering) an empty one."""
    c, cid = _ready_case(monkeypatch, tmp_path)
    packet_dir = os.path.join(appmod.store.case_dir(cid), "packets", "0")
    os.makedirs(packet_dir, exist_ok=True)
    manifest_path = os.path.join(packet_dir, "manifest.json")
    manifest = {
        "id": "p0", "name": "Nguyễn Văn A", "product": "",
        "docs": [{"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ", "pages": []}],
        "fields": [{"key": "hoten", "expected": "Nguyễn Văn A", "sources": []}],
    }
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # Simulate a pre-v2 manifest: load it back and strip `checks` (a no-op
    # here since we never set it, but this is the shape a real migration --
    # or an old manifest that predates the field -- would take).
    with open(manifest_path, "r", encoding="utf-8") as f:
        on_disk = json.load(f)
    on_disk.pop("checks", None)
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(on_disk, f, ensure_ascii=False, indent=2)

    r = c.get(f"/api/cases/{cid}/packets/0/manifest.json")
    assert r.status_code == 200
    checks = r.json()["checks"]
    assert len(checks) > 0
    assert checks[0]["code"] == "G-DOC"

if __name__ == "__main__":
    # minimal manual runner (monkeypatch/tmp_path tests need pytest; run those with: python3 -m pytest server/app_test.py)
    test_rewrite_manifest_urls_points_pages_at_api(); print("  ok rewrite")
    test_post_requires_pdf(); print("  ok requires-pdf")
    test_page_endpoint_rejects_traversal(); print("  ok traversal")
    test_get_unknown_case_404(); print("  ok get-unknown-404")
    test_review_unknown_case_404(); print("  ok review-unknown-404")
    print("BASIC OK (run monkeypatch tests via pytest)")
