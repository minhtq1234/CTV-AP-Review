# Stage B — FastAPI backend (job + progress, serves pages/manifests) — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal:** A local FastAPI service that accepts an uploaded scanned PDF (+ optional roster), runs split → OCR/extract on a background thread with progress, and serves the per-packet `CtvFolder` manifests + rendered page PNGs the frontend consumes.

**Architecture:** Thin web layer (`app.py`) over an injectable pipeline (`pipeline.py`, reusing `splitter/detect_packets.py` + `server/ocr_extract.py`) and an in-memory job store (`jobs.py`). The web layer + job store + URL rewriting are unit-tested with a FAKE pipeline (no real PDF/OCR); the real pipeline is verified by running uvicorn against the real file. Binds `127.0.0.1`; job data in a per-job temp dir; nothing committed.

**Tech Stack:** Python 3, FastAPI, uvicorn, python-multipart, PyMuPDF, pytesseract. Tests via `fastapi.testclient.TestClient`, run with `python3 server/app_test.py`.

---

## File Structure
- Create `server/jobs.py` — `JobStore` (in-memory registry) + `start_job(...)` (threaded runner, injectable `run`).
- Create `server/pipeline.py` — `run_pipeline(pdf_path, roster_path, job_dir, progress_cb) -> dict` orchestrating split + per-packet OCR; writes manifests + page PNGs under `job_dir/packets/{i}/`.
- Create `server/app.py` — FastAPI app, endpoints, CORS, static file serving with a manifest URL-rewrite; `rewrite_manifest_urls(...)` pure helper.
- Create `server/app_test.py` — TestClient tests with a fake pipeline.
- Modify `server/README.md` — how to run the server + endpoints + PII note.

**PII:** uploads + outputs live under a per-job temp dir (`tempfile.mkdtemp`); never committed. Only `server/*.py` + README are committable.

---

## Task B1: Job store + threaded runner (`jobs.py`)

- [ ] **Step 1 — failing test** `server/jobs_test.py`:
```python
import time
from jobs import JobStore, start_job

def test_job_lifecycle_success():
    store = JobStore()
    jid = store.create(job_dir="/tmp/x")
    assert store.get(jid)["status"] == "queued"
    def fake_run(pdf, roster, job_dir, cb):
        cb("ocr", 1, 2, "packet 1"); cb("ocr", 2, 2, "packet 2")
        return {"summary": {"found": 2}, "packets": []}
    start_job(store, jid, pdf="/tmp/a.pdf", roster=None, run=fake_run)
    for _ in range(100):
        if store.get(jid)["status"] in ("done", "error"): break
        time.sleep(0.02)
    j = store.get(jid)
    assert j["status"] == "done"
    assert j["result"]["summary"]["found"] == 2
    assert j["progress"]["done"] == 2 and j["progress"]["total"] == 2

def test_job_lifecycle_error():
    store = JobStore(); jid = store.create(job_dir="/tmp/x")
    def boom(*a, **k): raise RuntimeError("nope")
    start_job(store, jid, pdf="/tmp/a.pdf", roster=None, run=boom)
    for _ in range(100):
        if store.get(jid)["status"] in ("done", "error"): break
        time.sleep(0.02)
    j = store.get(jid)
    assert j["status"] == "error" and "nope" in j["error"]

if __name__ == "__main__":
    for n,f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
```
- [ ] **Step 2** run → fail (no module).
- [ ] **Step 3 — implement** `jobs.py`:
  - `JobStore`: dict `{id: {id,status,progress,result,error,dir}}`; `create(job_dir)` → uuid4 hex id, status `queued`, progress `{stage:"queued",done:0,total:0,detail:""}`; `get(id)`; `update(id, **fields)`; `set_progress(id, stage, done, total, detail)`.
  - `start_job(store, job_id, pdf, roster, run)`: set status `processing`; spawn a `threading.Thread` target that calls `run(pdf, roster, job_dir, cb)` where `cb` = a closure calling `store.set_progress`; on success `update(status="done", result=...)`; on exception `update(status="error", error=str(e))`. Thread `daemon=True`. Return immediately.
- [ ] **Step 4** run → PASS.
- [ ] **Step 5** commit `feat(server): in-memory job store + threaded runner`.

## Task B2: URL rewrite + app skeleton + validation (`app.py`)

- [ ] **Step 1 — failing test** in `server/app_test.py`:
```python
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
```
(Note: the two `monkeypatch` tests need pytest — `python3 -m pytest server/app_test.py -q`. If pytest is unavailable, install it or rewrite those to set `appmod.run_pipeline` directly and restore in a `finally`. The `__main__` runner covers the pytest-free ones.)
- [ ] **Step 2** run → fail.
- [ ] **Step 3 — implement** `app.py`:
  - `app = FastAPI()`; CORS middleware allow origins `http://localhost:5173`,`5174`,`5175` (+127.0.0.1 variants), methods/headers `*`.
  - Module-level `store = JobStore()` and `from pipeline import run_pipeline` (referenced as `run_pipeline` at call time so tests can monkeypatch).
  - `POST /api/jobs` — params `pdf: UploadFile = File(...)`, `roster: UploadFile | None = File(None)`. `mkdtemp()`; save pdf → `job_dir/input.pdf`, roster (if any) → `job_dir/roster.xlsx`; `jid = store.create(job_dir)`; `start_job(store, jid, pdf_path, roster_path, run=run_pipeline)`; return `{"job_id": jid}`.
  - `GET /api/jobs/{jid}` → the job dict (status/progress/result/error) or 404.
  - `GET /api/jobs/{jid}/packets/{i}/manifest.json` → read `job_dir/packets/{i}/manifest.json`, `rewrite_manifest_urls(m, f"/api/jobs/{jid}/packets/{i}")`, return JSON; 404 if missing.
  - `GET /api/jobs/{jid}/packets/{i}/page/{name}` → validate `name` matches `^[A-Za-z0-9_.-]+\.png$` (else 400); `FileResponse(job_dir/packets/{i}/name)`; 404 if missing.
  - `rewrite_manifest_urls(manifest, base)` pure helper (basename swap).
- [ ] **Step 4** run `python3 server/app_test.py` (basic) + `python3 -m pytest server/app_test.py -q` (full) → pass.
- [ ] **Step 5** commit `feat(server): FastAPI app — jobs endpoints, manifest URL rewrite, CORS`.

## Task B3: Real pipeline (`pipeline.py`)

- [ ] **Step 1 — implement** `run_pipeline(pdf_path, roster_path, job_dir, progress_cb)` (no unit test; verified in B4):
  - `sys.path.insert(0, <repo>/splitter)`; `import detect_packets as dp`; `import ocr_extract as oc`.
  - `progress_cb("splitting", 0, 0, "")`. Run dp: `bands,aspects,inks,n = dp.load_page_bands(pdf_path)`; `scores,seed = dp.seed_scores(bands)`; `thr = dp.derive_threshold(scores)`; `covers = dp.covers_from_scores(scores,thr)`; roster names via `dp._roster_rows` + `dp.extract_roster_names` if roster given; prune (`dp.prune_excess_covers`) when roster present; `bounds = dp.packets_from_covers(kept, n)`; `packets = dp.reconcile(...)`; set labels as in `dp.main`.
  - Build a `roster_row` per packet from the roster rows (reuse the mapping from Stage A's A5 driver — name/cccd/mst/tk/ngaysinh/phi). Keep this mapping in `pipeline.py` as a documented helper `roster_row_for(rows, packet_index)`.
  - `progress_cb("ocr", 0, len(packets), "")`; for each packet i: `oc.ocr_packet(pdf_path, start, end, roster_row, job_dir/packets/{i}, name, product)` → writes manifest + PNGs; `progress_cb("ocr", i+1, len(packets), name)`.
  - Return `{"summary": {found, roster_n, matched, auto_merged}, "packets": [{index,name,pages:[start,end],n_pages,confidence,flags,labels}]}`.
- [ ] **Step 2** import check `cd server && python3 -c "import pipeline; print('ok')"`.
- [ ] **Step 3** commit `feat(server): pipeline — split + per-packet OCR with progress`.

## Task B4: Real end-to-end run (verification)
- [ ] Start the server: `cd server && python3 -m uvicorn app:app --host 127.0.0.1 --port 8000` (background).
- [ ] `POST` the real files with curl:
  `curl -s -F "pdf=@$HOME/Downloads/FA-PM260226080.pdf" -F "roster=@$HOME/Downloads/Chi phí Cộng tác viên/BẢNG KÊ THANH TOÁN CTV -THÁNG 2.2026.xlsx" http://127.0.0.1:8000/api/jobs` → capture `job_id`.
- [ ] Poll `GET /api/jobs/{id}` until `done`; confirm progress advanced through `splitting`→`ocr n/N`; `result.summary.found == 32`.
- [ ] Fetch `GET /api/jobs/{id}/packets/0/manifest.json` → valid CtvFolder with page srcs pointing at `/api/jobs/{id}/packets/0/page/*.png`; fetch one page PNG → 200 image. Confirm the amber packet is present with its `auto-merged` flag.
- [ ] Report the timing, the summary, and any errors. Do NOT commit any job output.

## Self-Review Notes
- Spec coverage: POST/GET job + progress (B1,B2), pipeline split+OCR (B3), manifest+page serving with rewrite (B2), CORS/localhost/temp-dir/PII (B2,B3), e2e on real file (B4).
- Type consistency: job dict `{id,status,progress:{stage,done,total,detail},result,error,dir}`; result `{summary,packets:[{index,name,pages,n_pages,confidence,flags,labels}]}`; `run_pipeline(pdf_path,roster_path,job_dir,progress_cb)` signature identical in jobs/app/pipeline and the fake in tests.
- Placeholder scan: endpoint specs + key code + concrete tests given; B3 orchestrates existing, verified functions.
