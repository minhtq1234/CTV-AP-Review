# Case Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** Persist each uploaded submission as a durable, resumable **case** (a batch of CTV packets), with a case-list landing, a case-detail view showing progress, and per-packet decisions saved to disk.

**Architecture:** A JSON-on-disk `CaseStore` under `server/data/cases/<id>/` replaces the in-memory `JobStore`; the pipeline writes packet manifests/pages into the (durable) case dir; new `/api/cases*` endpoints expose list/detail/decision/delete; the frontend upload flow becomes a small router: case-list → upload → processing → case-detail → packet review (decisions persist via the API).

**Tech Stack:** Python 3, FastAPI, PyMuPDF, pytesseract (reused). React 18 + TS + Vite. Backend tests: plain-assert + `fastapi.testclient`. Frontend pure logic: vitest. UI verified in-browser.

**Reference:** spec `docs/superpowers/specs/2026-07-13-case-management-design.md`. Read the existing `server/jobs.py`, `server/app.py`, `server/pipeline.py`, `src/upload/api.ts`, `src/components/UploadFlow.tsx` before editing.

---

## File Structure
- Create `server/cases.py` — `CaseStore` (persistent) + status recomputation. Replaces `jobs.py`'s role.
- Create `server/cases_test.py` — plain-assert unit tests (temp data dir).
- Modify `server/app.py` — `/api/cases*` endpoints over `CaseStore`; keep the threaded worker (reuse `start_job`-style runner, now writing into the case dir).
- Modify `server/app_test.py` — TestClient tests for the new endpoints with a fake pipeline.
- Modify `server/pipeline.py` — only if needed: accept the case dir as its output dir (it already takes `job_dir`; pass the case dir). No logic change expected.
- Modify `server/README.md` — new endpoints + data dir + PII note.
- Modify `.gitignore` — add `server/data`.
- Modify `src/upload/api.ts` (+ `api.test.ts`) — case endpoints + types + helpers.
- Create `src/components/CaseList.tsx`, `src/components/CaseDetail.tsx`.
- Modify `src/components/UploadFlow.tsx` — router over case-list/upload/processing/case-detail/review; persist decisions.
- Modify `src/styles.css` — case-list/detail/badge styles (reuse existing idiom).

**PII:** `server/data/` holds real uploads/OCR output → gitignored, never committed. Commit code only.

---

## Task B1: `CaseStore` — persistent case store + status logic

**Files:** Create `server/cases.py`, `server/cases_test.py`

- [ ] **Step 1: Write the failing test** (`server/cases_test.py`):

```python
import json, os, tempfile
from cases import CaseStore, case_status, progress_of

def _pkts(decisions):
    return [{"index": i, "name": f"P{i}", "pages": [i*8, i*8+7], "confidence": "green",
             "flags": [], "decision": d, "rejectReason": None, "reviewedAt": None}
            for i, d in enumerate(decisions)]

def test_case_status_transitions():
    assert case_status("processing", _pkts([])) == "processing"
    assert case_status("ready", _pkts(["pending","pending"])) == "ready"
    assert case_status("ready", _pkts(["approved","pending"])) == "in_review"
    assert case_status("ready", _pkts(["approved","rejected"])) == "done"

def test_progress_counts_decided_and_flagged():
    pk = _pkts(["approved","pending","pending"])
    pk[1]["confidence"] = "amber"
    assert progress_of(pk) == {"decided": 1, "total": 3, "flagged": 1}

def test_create_list_get_roundtrip_and_reload():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="Feb batch", pdf_name="feb.pdf", roster_name=None)
        assert s.get(cid)["status"] == "processing"
        s.set_result(cid, summary={"found": 2, "rosterN": 2, "autoMerged": 0},
                     packets=_pkts(["pending","pending"]))
        assert s.get(cid)["status"] == "ready"
        assert len(s.list()) == 1 and s.list()[0]["id"] == cid
        # reload from disk (simulate restart) — persistence survives
        s2 = CaseStore(d)
        assert s2.get(cid)["status"] == "ready"
        assert s2.get(cid)["summary"]["found"] == 2

def test_set_decision_updates_status_and_persists():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.set_result(cid, summary=None, packets=_pkts(["pending","pending"]))
        s.set_decision(cid, 0, "approved", None, now="2026-07-13T00:00:00")
        assert s.get(cid)["status"] == "in_review"
        assert s.get(cid)["packets"][0]["decision"] == "approved"
        s.set_decision(cid, 1, "rejected", "thiếu chữ ký", now="2026-07-13T00:01:00")
        assert s.get(cid)["status"] == "done"
        assert CaseStore(d).get(cid)["packets"][1]["rejectReason"] == "thiếu chữ ký"

def test_delete_removes_case():
    with tempfile.TemporaryDirectory() as d:
        s = CaseStore(d)
        cid = s.create(name="x", pdf_name="x.pdf", roster_name=None)
        s.delete(cid)
        assert s.get(cid) is None and s.list() == []

if __name__ == "__main__":
    for n, f in sorted(globals().items()):
        if n.startswith("test_") and callable(f): f(); print(f"  ok {n}")
    print("ALL OK")
```

- [ ] **Step 2: Run → fail** — `cd server && python3 cases_test.py` → `ModuleNotFoundError`.

- [ ] **Step 3: Implement `server/cases.py`:**
  - `case_status(base_status, packets)`: if `base_status` in `("processing","error")` → return it. Else if no packets → `"ready"`. Else count decided (`decision != "pending"`); `0 → "ready"`, all → `"done"`, some → `"in_review"`.
  - `progress_of(packets)` → `{"decided": <count decision!=pending>, "total": len, "flagged": <count confidence=="amber">}`.
  - `CaseStore(root)`: `self.root=root`; `os.makedirs(root, exist_ok=True)`; on init, scan `root/*/case.json` into `self._idx: dict[id, case]` (skip unreadable, don't crash).
    - `create(name, pdf_name, roster_name)`: id = `uuid4().hex`; case dict `{id, name, createdAt: None (caller/worker may stamp; store leaves None—the app passes an ISO string via create's optional `now` arg), status:"processing", pdfName, rosterName, summary:None, error:None, packets:[]}`. Make `create(self, name, pdf_name, roster_name, now=None)` and set `createdAt=now`. `mkdir root/<id>/`; write `case.json`; index it; return id.
    - `_path(cid)` → `root/<cid>/case.json`; `_write(case)` → dump JSON (ensure_ascii=False) + update index.
    - `get(cid)` → `self._idx.get(cid)` (a copy is fine; return the dict).
    - `list()` → cases sorted by `createdAt` desc (None last), each as a summary `{id,name,createdAt,status,pdfName,progress: progress_of(packets)}`.
    - `set_result(cid, summary, packets)`: set `summary`, `packets` (each ensured to have decision fields defaulting pending/None), recompute `status = case_status("ready", packets)`, write.
    - `set_error(cid, msg)`: `status="error"`, `error=msg`, write.
    - `set_decision(cid, index, decision, reject_reason, now)`: find packet by index, set `decision`, `rejectReason=reject_reason`, `reviewedAt=now`; recompute status via `case_status(<current base>, packets)` where base is `"ready"` unless processing/error; write; return the case.
    - `delete(cid)`: `shutil.rmtree(root/<cid>)`, drop from index.
  - `case_dir(cid)` → `root/<cid>` (used by the app to locate packet manifests/pages).

- [ ] **Step 4: Run → pass** — `ALL OK`.

- [ ] **Step 5: Commit** — `git add server/cases.py server/cases_test.py && git commit -m "feat(server): persistent CaseStore + status/progress logic"`

---

## Task B2: `/api/cases` endpoints

**Files:** Modify `server/app.py`, `server/app_test.py`, `.gitignore`

- [ ] **Step 1: Add `.gitignore` line** — append `server/data`.

- [ ] **Step 2: Write failing tests** (`server/app_test.py`, add; keep existing where still valid):

```python
from fastapi.testclient import TestClient
import app as appmod
from app import app

def _fake_pipeline(pdf, roster, out_dir, cb):
    cb("done", 1, 1, "")
    return {"summary": {"found": 1, "rosterN": 1, "autoMerged": 0},
            "packets": [{"index": 0, "name": "P0", "pages": [8, 15],
                         "confidence": "green", "flags": [], "labels": []}]}

def test_case_create_list_detail_decision(tmp_path, monkeypatch):
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
    assert c.get("/api/cases").json()[0]["id"] == cid
    # decision persists + flips status
    r = c.put(f"/api/cases/{cid}/packets/0/decision", json={"decision": "approved"})
    assert r.status_code == 200
    assert c.get(f"/api/cases/{cid}").json()["status"] == "done"
    # delete
    assert c.delete(f"/api/cases/{cid}").status_code == 200
    assert c.get("/api/cases").json() == []

def test_post_requires_pdf():
    assert TestClient(app).post("/api/cases").status_code == 422
```

- [ ] **Step 3: Run → fail.**

- [ ] **Step 4: Implement in `server/app.py`:**
  - `from cases import CaseStore`; module-level `store = CaseStore(os.path.join(os.path.dirname(__file__), "data", "cases"))`.
  - Reference `run_pipeline` via the module attr (monkeypatchable).
  - `POST /api/cases` (`pdf: UploadFile=File(...)`, `roster: UploadFile|None=File(None)`): create case (`now=datetime.now(timezone.utc).isoformat()`), save pdf→`case_dir/input.pdf`, roster→`case_dir/roster.xlsx`; spawn a daemon thread running `run_pipeline(pdf_path, roster_path, case_dir, cb)`; on success `store.set_result(...)`, on exception `store.set_error(...)`; `cb` updates a lightweight in-memory progress map keyed by cid (for the processing screen). Return `{case_id}`.
  - `GET /api/cases` → `store.list()`.
  - `GET /api/cases/{cid}` → the case dict + `progress` + (if processing) the live `{stage,done,total,detail}` from the progress map; 404 if unknown.
  - `PUT /api/cases/{cid}/packets/{i}/decision` (body `{decision, rejectReason?}`) → `store.set_decision(cid, i, decision, reject_reason, now=...)`; return `{packet, progress, status}`; 404 if unknown; 400 on bad `decision`.
  - `DELETE /api/cases/{cid}` → `store.delete(cid)`; 200.
  - `GET /api/cases/{cid}/packets/{i}/manifest.json` and `/page/{name}` → serve from `store.case_dir(cid)/packets/{i}/…` (reuse `rewrite_manifest_urls` with base `/api/cases/{cid}/packets/{i}`; keep the traversal guard). Remove the old `/api/jobs*` routes.

- [ ] **Step 5: Run → pass** — `python3 -m pytest app_test.py -q` (and the `__main__` subset).

- [ ] **Step 6: Commit** — `feat(server): /api/cases endpoints over CaseStore; drop /api/jobs`.

---

## Task B3: Real end-to-end backend run (verification)
- [ ] Start uvicorn; `POST /api/cases` with the real PDF + `03_roster_5loi.xlsx`; poll `GET /api/cases/{id}` → `ready`, 32 packets. `PUT …/packets/0/decision {approved}` → `GET` shows status `in_review`, packet 0 `approved`. **Restart uvicorn**; `GET /api/cases` still lists the case; packet 0 still `approved` (disk persistence). `DELETE` it. Report timings + that persistence survived restart. No job output committed.

---

## Task F1: Frontend API client (`src/upload/api.ts` + `api.test.ts`)

- [ ] **Step 1: Failing vitest** — add:
```ts
import { describe, it, expect } from 'vitest'
import { caseProgressLabel, decisionBadge } from './api'
describe('case helpers', () => {
  it('formats progress', () => {
    expect(caseProgressLabel({ decided: 12, total: 32, flagged: 3 }))
      .toMatch(/12\/32.*duyệt.*3.*cần xem/i)
  })
  it('maps decision to badge', () => {
    expect(decisionBadge('approved')).toMatch(/duyệt/i)
    expect(decisionBadge('rejected')).toMatch(/từ chối/i)
    expect(decisionBadge('pending')).toMatch(/chưa xem/i)
  })
})
```
- [ ] **Step 2: Run → fail.**
- [ ] **Step 3: Implement** — add types `CaseSummary`, `CaseDetail`, `PacketMeta`, `Decision`; functions `listCases()`, `getCase(id)`, `createCase(pdf,roster?)` (POST `/api/cases`), `setDecision(id,i,decision,reason?)` (PUT), `deleteCase(id)`; helpers `caseProgressLabel(p)` → `"12/32 đã duyệt · 3 cần xem"`, `decisionBadge(d)` → `{approved:'✓ Đã duyệt', rejected:'✗ Từ chối', pending:'Chưa xem'}[d]`. Keep `getCase` returning packet manifests via `…/packets/{i}/manifest.json` + `withAbsolutePageSrc`.
- [ ] **Step 4: Run → pass.** **Step 5: Commit** `feat(upload): case API client + helpers`.

## Task F2: Case-list + case-detail screens
- [ ] **Implement** `CaseList.tsx` (props `{cases, onOpen, onNew, onDelete}`) — rows with name, date, status pill, `caseProgressLabel`, open + delete buttons, a "+ Tải hồ sơ mới" button. `CaseDetail.tsx` (props `{detail, onOpenPacket, onBack}`) — case header with progress, the packet-card grid (reuse the SplitResultScreen card look) with each card showing `decisionBadge` + confidence dot. Add styles. **Commit** `feat(upload): case-list + case-detail screens`.

## Task F3: Router refactor of `UploadFlow` + persist decisions
- [ ] **Implement** — `UploadFlow` becomes screens `list | upload | processing | detail | review`:
  - `list`: `listCases()` on mount + after returning from a case; `onNew`→`upload`; `onOpen(id)`→ load `getCase`, `detail`; `onDelete`→`deleteCase`+refresh.
  - `upload`→`createCase`→`processing` (poll `getCase` until `ready`)→ on ready, `detail`.
  - `detail`: `CaseDetail`; `onOpenPacket(i)`→ fetch that packet manifest → `review`.
  - `review`: existing `FolderReview`; wire **Duyệt/Từ chối to `setDecision(caseId,i,…)`**, then return to `detail` (refreshed) or advance to next `pending` packet. Keep the loupe/keyboard intact.
  - Generalize the resume hook `?job=` → `?case=` (open that case's detail). Wire `App.tsx` "Tải hồ sơ" mode to render this router with `list` as default.
  - Backend-down handling stays (friendly message).
- [ ] `npx tsc -b` clean; `npx vitest run` green. **Commit** `feat(upload): case router + persisted decisions`.

## Task F4: Browser verification
- [ ] Backend (uvicorn) + dev server up. Upload the real PDF+roster → case appears in the list (processing→ready). Open it → case detail with 32 packets, all "Chưa xem". Open a packet → Duyệt → returns to detail, that card now "✓ Đã duyệt", progress `1/32`. **Reload the page** → decision persists. Open a second small upload → two cases listed. Delete one → gone. Screenshot the list + a detail with mixed decisions.

---

## Self-Review Notes
- **Spec coverage:** persistence/JSON-on-disk → B1 (`CaseStore` + reload test); case=submission + packets nested → B1 data; decisions persist + resume → B1 `set_decision`, F3 review wiring, B3/F4 restart checks; endpoints (list/detail/decision/delete/create) → B2; case-list landing + detail + badges → F2/F3; delete included; startup index rebuild → B1 init + B3 restart. PII → `.gitignore server/data` (B2), data dir only.
- **Placeholder scan:** none — every step has code or an exact command.
- **Type consistency:** `case`/`packet` dict keys (`id,name,createdAt,status,pdfName,rosterName,summary,error,packets`; `index,name,pages,confidence,flags,decision,rejectReason,reviewedAt`) identical across B1/B2/F1; `case_status`/`progress_of`/`set_result`/`set_decision`/`set_error`/`delete`/`case_dir` names consistent; frontend `Decision = 'pending'|'approved'|'rejected'` matches backend strings; endpoints `/api/cases…` consistent app↔client.
