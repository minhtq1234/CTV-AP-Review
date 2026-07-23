# Review-to-Completeness + Resubmission Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace per-packet approve/reject with a review-to-completeness flow — the reviewer skims every field (auto seen-tracking, "Done" gated on all-seen), flags fields that don't reconcile with notes, sees the roster value pinned onto the document, and exports one server-generated consolidated resubmission report grouped by CTV. Also surface the roster↔packet match key so mis-matches are visible.

**Architecture:** Two phases. **Phase 1 (backend, Python/FastAPI)** changes the persisted per-packet shape from `decision/rejectReason/reviewedAt` to a `review {done, fields{key:{seen,flag}}}` object, persists the match key + both identities on packet meta, adds a pure `build_report` module, and swaps the decision endpoint for review + report endpoints. **Phase 2 (frontend, React/TS)** consumes the new API: seen-tracking + Done gate in the reviewer, per-field flag UI, the roster-value callout on the doc view, the match-key strip, and the report preview/download. Each phase is independently testable (backend has unit + endpoint tests; frontend builds on the live API).

**Tech Stack:** FastAPI + PyMuPDF/Tesseract pipeline (unchanged), `pytest` for backend; Vite + React 18 + TS, `vitest` for pure-logic tests, browser verification for UI. Spec: `docs/superpowers/specs/2026-07-23-review-completeness-and-resubmit-design.md`.

## Canonical shapes (used across every task — keep names identical)

**Persisted per-packet review state** (in `case.json` packet dicts, and TS mirror):
```jsonc
"review": {
  "done": false,
  "fields": {                          // only fields the reviewer has touched appear here
    "<fieldKey>": { "seen": true, "flag": null }   // flag: null | { "reason": "", "note": "" }
  }
}
```

**Match info on each packet meta** (populated by the pipeline):
```jsonc
"matchedBy": "cccd" | "name" | "unmatched" | "no-roster",
"ocrIdentity":    { "cccd": "", "name": "" },      // read from the documents
"rosterIdentity": { "cccd": "", "name": "" } | null // from the matched roster row
```
(These **replace** `decision` / `rejectReason` / `reviewedAt`.)

**A packet "needs resubmission"** when: it has ≥1 flagged field **OR** `matchedBy ∈ {"name","unmatched"}`.

**Derived packet status:** `untouched` (done=false, no seen fields) · `in_review` (done=false, ≥1 seen) · `clear` (done=true, not needs-resubmit) · `needs_resubmit` (done=true, needs-resubmit).

---

# Phase 1 — Backend

### Task 1: Review-state model + status/progress in `cases.py`

**Files:**
- Modify: `server/cases.py` (`case_status`, `progress_of`, `_ensure_packet_defaults`; add `needs_resubmit`, `set_review`; remove `set_decision`)
- Test: `server/cases_test.py`

- [ ] **Step 1: Write failing tests**

Add to `server/cases_test.py`:
```python
from cases import case_status, progress_of, needs_resubmit, CaseStore

def _pkt(index, done=False, flags=None, matched_by="cccd"):
    fields = {}
    for k in (flags or []):
        fields[k] = {"seen": True, "flag": {"reason": "sai", "note": ""}}
    return {"index": index, "confidence": "green", "matchedBy": matched_by,
            "review": {"done": done, "fields": fields}}

def test_needs_resubmit_on_field_flag():
    assert needs_resubmit(_pkt(0, flags=["cccd"])) is True
    assert needs_resubmit(_pkt(0)) is False

def test_needs_resubmit_on_weak_match():
    assert needs_resubmit(_pkt(0, matched_by="name")) is True
    assert needs_resubmit(_pkt(0, matched_by="unmatched")) is True
    assert needs_resubmit(_pkt(0, matched_by="cccd")) is False

def test_case_status_from_done_count():
    assert case_status("ready", []) == "ready"
    assert case_status("ready", [_pkt(0), _pkt(1)]) == "ready"
    assert case_status("ready", [_pkt(0, done=True), _pkt(1)]) == "in_review"
    assert case_status("ready", [_pkt(0, done=True), _pkt(1, done=True)]) == "done"
    assert case_status("processing", [_pkt(0, done=True)]) == "processing"

def test_progress_counts_done_and_flagged():
    pkts = [_pkt(0, done=True, flags=["cccd"]), _pkt(1, done=True), _pkt(2)]
    assert progress_of(pkts) == {"done": 2, "total": 3, "flagged": 1}
```

- [ ] **Step 2: Run to verify failure**

Run: `cd server && python -m pytest cases_test.py -q`
Expected: FAIL (`ImportError: cannot import name 'needs_resubmit'`).

- [ ] **Step 3: Implement**

In `server/cases.py`, replace `case_status`, `progress_of`, `_ensure_packet_defaults` and add `needs_resubmit`:
```python
def needs_resubmit(packet: dict) -> bool:
    """A packet needs resubmission if any field is flagged, or its roster
    match is weak (matched by name only, or unmatched)."""
    review = packet.get("review") or {"fields": {}}
    if any(f.get("flag") for f in review.get("fields", {}).values()):
        return True
    return packet.get("matchedBy") in ("name", "unmatched")


def case_status(base_status: str, packets: list[dict]) -> str:
    if base_status in ("processing", "error"):
        return base_status
    if not packets:
        return "ready"
    done = sum(1 for p in packets if (p.get("review") or {}).get("done"))
    if done == 0:
        return "ready"
    if done == len(packets):
        return "done"
    return "in_review"


def progress_of(packets: list[dict]) -> dict:
    """`{done, total, flagged}` — done = packets marked Done,
    flagged = packets needing resubmission."""
    return {
        "done": sum(1 for p in packets if (p.get("review") or {}).get("done")),
        "total": len(packets),
        "flagged": sum(1 for p in packets if needs_resubmit(p)),
    }


def _ensure_packet_defaults(packet: dict) -> dict:
    """Fill review/match defaults if the pipeline (or a fake test pipeline)
    didn't set them."""
    out = dict(packet)
    out.setdefault("review", {"done": False, "fields": {}})
    out.setdefault("matchedBy", "no-roster")
    out.setdefault("ocrIdentity", {"cccd": "", "name": ""})
    out.setdefault("rosterIdentity", None)
    return out
```
Then replace `set_decision` with `set_review`:
```python
    def set_review(self, cid: str, index: int, review: dict) -> dict | None:
        case = self._idx.get(cid)
        if case is None:
            return None
        for p in case["packets"]:
            if p["index"] == index:
                p["review"] = {
                    "done": bool(review.get("done", False)),
                    "fields": review.get("fields", {}) or {},
                }
                break
        else:
            return None
        base = case["status"] if case["status"] in ("processing", "error") else "ready"
        case["status"] = case_status(base, case["packets"])
        self._write(case)
        return case
```

- [ ] **Step 4: Run to verify pass**

Run: `cd server && python -m pytest cases_test.py -q`
Expected: PASS. (If old `set_decision` tests exist in this file, update them to `set_review` with the new shape now.)

- [ ] **Step 5: Commit**

```bash
git add server/cases.py server/cases_test.py
git commit -m "feat(cases): review-state model (done+field flags), match-aware progress"
```

### Task 2: Migrate old decision packets on load

**Files:**
- Modify: `server/cases.py` (`_load`)
- Test: `server/cases_test.py`

- [ ] **Step 1: Write failing test**

Add to `server/cases_test.py`:
```python
import json, os

def test_load_migrates_old_decision_packets(tmp_path):
    cid = "old"
    d = tmp_path / cid
    d.mkdir()
    old = {"id": cid, "name": "x", "createdAt": None, "status": "in_review",
           "pdfName": "x.pdf", "rosterName": None, "summary": None, "error": None,
           "packets": [{"index": 0, "confidence": "green",
                        "decision": "approved", "rejectReason": None, "reviewedAt": "t"}]}
    (d / "case.json").write_text(json.dumps(old), encoding="utf-8")
    store = CaseStore(str(tmp_path))
    p = store.get(cid)["packets"][0]
    assert p["review"] == {"done": False, "fields": {}}
    assert "decision" not in p and "rejectReason" not in p and "reviewedAt" not in p
    assert p["matchedBy"] == "no-roster"
```

- [ ] **Step 2: Run to verify failure**

Run: `cd server && python -m pytest cases_test.py::test_load_migrates_old_decision_packets -q`
Expected: FAIL (`KeyError: 'review'` / assertion on leftover `decision`).

- [ ] **Step 3: Implement**

In `server/cases.py` `_load`, in the `else:` branch (non-processing cases), migrate before indexing:
```python
            else:
                changed = False
                for p in case.get("packets", []):
                    if "review" not in p:
                        p["review"] = {"done": False, "fields": {}}
                        for k in ("decision", "rejectReason", "reviewedAt"):
                            p.pop(k, None)
                        p.setdefault("matchedBy", "no-roster")
                        p.setdefault("ocrIdentity", {"cccd": "", "name": ""})
                        p.setdefault("rosterIdentity", None)
                        changed = True
                if changed:
                    self._write(case)   # persist the migration
                else:
                    self._idx[cid] = case
```
(Note: `_write` also indexes, so only index directly when nothing changed.)

- [ ] **Step 4: Run to verify pass**

Run: `cd server && python -m pytest cases_test.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/cases.py server/cases_test.py
git commit -m "feat(cases): migrate legacy decision packets to review state on load"
```

### Task 3: Persist match key + identities on packet meta

**Files:**
- Modify: `server/pipeline.py` (the `packets_out.append({...})` block, ~line 273)
- Test: `server/pipeline_test.py`

- [ ] **Step 1: Write failing test**

Add to `server/pipeline_test.py` (follow the file's existing `run_pipeline`/fake-OCR harness; assert on the returned `packets`):
```python
def test_packet_meta_carries_match_key_and_identities(tmp_path, monkeypatch):
    # Reuse this file's existing helper that runs run_pipeline with a fake
    # ocr_packet + a 2-row roster where packet 0's OCR'd CCCD matches row 0.
    result = run_fake_pipeline(tmp_path, monkeypatch)   # existing helper in this file
    p0 = result["packets"][0]
    assert p0["matchedBy"] in ("cccd", "name", "unmatched", "no-roster")
    assert set(p0["ocrIdentity"]) == {"cccd", "name"}
    assert p0["rosterIdentity"] is None or set(p0["rosterIdentity"]) == {"cccd", "name"}
```
If no such helper exists, adapt the nearest existing pipeline test to also assert these three keys are present on each packet.

- [ ] **Step 2: Run to verify failure**

Run: `cd server && python -m pytest pipeline_test.py -q`
Expected: FAIL (`KeyError: 'matchedBy'`).

- [ ] **Step 3: Implement**

In `server/pipeline.py`, the `run_pipeline` loop already computes `identity` and `row, how = match_roster(...)` (or `row, how = None, "no-roster"`). Extend the appended packet dict:
```python
        packets_out.append({
            "index": p.index,
            "name": p.name,
            "pages": [p.start, p.end],
            "n_pages": p.n_pages,
            "confidence": p.confidence,
            "flags": p.flags,
            "labels": p.labels,
            "matchedBy": how,
            "ocrIdentity": {"cccd": identity.get("cccd", ""), "name": identity.get("name", "")},
            "rosterIdentity": (
                {"cccd": row.get("cccd", ""), "name": row.get("name", "")}
                if row is not None else None
            ),
        })
```

- [ ] **Step 4: Run to verify pass**

Run: `cd server && python -m pytest pipeline_test.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/pipeline.py server/pipeline_test.py
git commit -m "feat(pipeline): persist matchedBy + ocr/roster identities on packet meta"
```

### Task 4: Consolidated report builder (pure)

**Files:**
- Create: `server/report.py`
- Test: `server/report_test.py`

The builder is pure: it takes a `case` dict and a `manifests` map (packet index → CtvFolder manifest dict, already on disk) plus a `generated_at` string, and returns `{groups, markdown, csv}`. The app layer reads the manifests and passes them.

- [ ] **Step 1: Write failing tests**

Create `server/report_test.py`:
```python
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
```

- [ ] **Step 2: Run to verify failure**

Run: `cd server && python -m pytest report_test.py -q`
Expected: FAIL (`ModuleNotFoundError: No module named 'report'`).

- [ ] **Step 3: Implement**

Create `server/report.py`:
```python
"""Pure builder for the consolidated resubmission report. Given a case dict,
a {packet_index: manifest} map, and a timestamp string, produce grouped data
plus Markdown + CSV renderings. No FastAPI / disk / clock here so it is unit
testable; the app layer loads manifests + stamps the time."""
from __future__ import annotations

import csv as _csv
import io

_MATCH_NOTE = {
    "name": "Định danh khớp theo tên — CCCD chưa khớp, cần xác minh đúng người.",
    "unmatched": "Không khớp được với bảng kê — cần xác minh đúng người.",
}


def _needs_resubmit(p: dict) -> bool:
    review = p.get("review") or {"fields": {}}
    if any(f.get("flag") for f in review.get("fields", {}).values()):
        return True
    return p.get("matchedBy") in ("name", "unmatched")


def _items_for(packet: dict, manifest: dict | None) -> list[dict]:
    fields = {f["key"]: f for f in (manifest or {}).get("fields", [])}
    docs = {d["id"]: d.get("label", d["id"]) for d in (manifest or {}).get("docs", [])}
    items = []
    for key, fr in (packet.get("review") or {}).get("fields", {}).items():
        flag = fr.get("flag")
        if not flag:
            continue
        f = fields.get(key, {})
        src = (f.get("sources") or [{}])[0]
        items.append({
            "fieldKey": key,
            "fieldLabel": f.get("label", key),
            "document": docs.get(src.get("docId"), "—"),
            "page": (src["page"] + 1) if "page" in src else None,
            "rosterValue": f.get("expected", ""),
            "docValue": src.get("value", ""),
            "reason": flag.get("reason", ""),
            "note": flag.get("note", ""),
        })
    return items


def build_report(case: dict, manifests: dict, generated_at: str) -> dict:
    groups = []
    for p in case.get("packets", []):
        if not _needs_resubmit(p):
            continue
        ident = p.get("rosterIdentity") or p.get("ocrIdentity") or {}
        groups.append({
            "index": p["index"],
            "name": p.get("name") or ident.get("name") or f"Gói {p['index'] + 1}",
            "cccd": ident.get("cccd", ""),
            "matchedBy": p.get("matchedBy", "no-roster"),
            "identityIssue": p.get("matchedBy") in ("name", "unmatched"),
            "items": _items_for(p, manifests.get(p["index"])),
        })

    md = [f"# Báo cáo cần gửi lại — {case.get('name', '')}", "",
          f"_Tạo lúc: {generated_at}_", ""]
    for g in groups:
        md.append(f"## {g['name']} — CCCD {g['cccd']}")
        if g["identityIssue"]:
            md.append(f"> ⚠ {_MATCH_NOTE.get(g['matchedBy'], '')}")
        for it in g["items"]:
            loc = it["document"] + (f", trang {it['page']}" if it["page"] else "")
            reason = f" — {it['reason']}" if it["reason"] else ""
            note = f": {it['note']}" if it["note"] else ""
            md.append(f"- **{it['fieldLabel']}** ({loc}): bảng kê \"{it['rosterValue']}\" "
                      f"≠ chứng từ \"{it['docValue']}\"{reason}{note}")
        md.append("")

    buf = io.StringIO()
    w = _csv.writer(buf)
    w.writerow(["CTV", "CCCD", "Trường", "Chứng từ", "Trang",
                "Bảng kê", "Chứng từ đọc được", "Lý do", "Ghi chú"])
    for g in groups:
        if g["identityIssue"] and not g["items"]:
            w.writerow([g["name"], g["cccd"], "Định danh", "", "", "", "",
                        g["matchedBy"], _MATCH_NOTE.get(g["matchedBy"], "")])
        for it in g["items"]:
            w.writerow([g["name"], g["cccd"], it["fieldLabel"], it["document"],
                        it["page"] or "", it["rosterValue"], it["docValue"],
                        it["reason"], it["note"]])
    return {"groups": groups, "markdown": "\n".join(md), "csv": buf.getvalue()}
```

- [ ] **Step 4: Run to verify pass**

Run: `cd server && python -m pytest report_test.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add server/report.py server/report_test.py
git commit -m "feat(report): pure consolidated-resubmission report builder (md + csv)"
```

### Task 5: API — review endpoint + report endpoints

**Files:**
- Modify: `server/app.py` (replace `put_decision` + `DecisionBody`; add report endpoints; import `build_report`)
- Test: `server/app_test.py`

- [ ] **Step 1: Write failing tests**

Add to `server/app_test.py` (follow its existing `TestClient` + seeded-case pattern):
```python
def test_put_review_persists_and_updates_status(client, seeded_case):  # existing fixtures
    cid = seeded_case  # a ready case with >=1 packet at index 0
    body = {"done": True, "fields": {"cccd": {"seen": True,
            "flag": {"reason": "sai", "note": "x"}}}}
    r = client.put(f"/api/cases/{cid}/packets/0/review", json=body)
    assert r.status_code == 200
    data = r.json()
    assert data["packet"]["review"]["done"] is True
    assert data["progress"]["done"] >= 1

def test_report_endpoint_generates_and_persists(client, seeded_case):
    cid = seeded_case
    client.put(f"/api/cases/{cid}/packets/0/review",
               json={"done": True, "fields": {"cccd": {"seen": True,
                     "flag": {"reason": "sai", "note": "x"}}}})
    r = client.post(f"/api/cases/{cid}/report")
    assert r.status_code == 200
    assert "markdown" in r.json()
    md = client.get(f"/api/cases/{cid}/report.md")
    assert md.status_code == 200 and "Báo cáo" in md.text
    csv = client.get(f"/api/cases/{cid}/report.csv")
    assert csv.status_code == 200 and csv.text.startswith("CTV,CCCD,")
```

- [ ] **Step 2: Run to verify failure**

Run: `cd server && python -m pytest app_test.py -q`
Expected: FAIL (404 / no such route). Also update/remove any existing `put_decision` test in this file.

- [ ] **Step 3: Implement**

In `server/app.py`: add `from report import build_report`. Remove `DecisionBody`, `put_decision`, and `_VALID_DECISIONS`. Add:
```python
class ReviewBody(BaseModel):
    done: bool = False
    fields: dict = {}


@app.put("/api/cases/{cid}/packets/{i}/review")
async def put_review(cid: str, i: int, body: ReviewBody):
    updated = store.set_review(cid, i, {"done": body.done, "fields": body.fields})
    if updated is None:
        raise HTTPException(status_code=404, detail="case or packet not found")
    packet = next((p for p in updated["packets"] if p["index"] == i), None)
    return {"packet": packet, "progress": progress_of(updated["packets"]),
            "status": updated["status"]}


def _load_manifests(cid: str, packets: list[dict]) -> dict:
    out = {}
    for p in packets:
        path = os.path.join(store.case_dir(cid), "packets", str(p["index"]), "manifest.json")
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as f:
                out[p["index"]] = json.load(f)
    return out


@app.post("/api/cases/{cid}/report")
async def post_report(cid: str):
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    manifests = _load_manifests(cid, case["packets"])
    now = datetime.now(timezone.utc).isoformat()
    report = build_report(case, manifests, generated_at=now)
    case_dir = store.case_dir(cid)
    with open(os.path.join(case_dir, "report.md"), "w", encoding="utf-8") as f:
        f.write(report["markdown"])
    with open(os.path.join(case_dir, "report.csv"), "w", encoding="utf-8") as f:
        f.write(report["csv"])
    return report


@app.get("/api/cases/{cid}/report.md")
async def get_report_md(cid: str):
    path = os.path.join(store.case_dir(cid), "report.md")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="report not generated")
    return FileResponse(path, media_type="text/markdown")


@app.get("/api/cases/{cid}/report.csv")
async def get_report_csv(cid: str):
    path = os.path.join(store.case_dir(cid), "report.csv")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="report not generated")
    return FileResponse(path, media_type="text/csv")
```

- [ ] **Step 4: Run to verify pass**

Run: `cd server && python -m pytest -q`  (whole backend suite)
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/app_test.py
git commit -m "feat(api): PUT packet review + POST/GET consolidated report endpoints"
```

---

# Phase 2 — Frontend

### Task 6: API client — types + review/report functions

**Files:**
- Modify: `src/upload/api.ts`
- Test: `src/upload/api.test.ts` (extend existing)

- [ ] **Step 1: Write failing test**

Add to `src/upload/api.test.ts`:
```ts
import { packetNeedsResubmit, reportUrls, API_BASE } from './api'

test('packetNeedsResubmit: field flag or weak match', () => {
  const base = { matchedBy: 'cccd', review: { done: true, fields: {} } } as any
  expect(packetNeedsResubmit(base)).toBe(false)
  expect(packetNeedsResubmit({ ...base, matchedBy: 'name' })).toBe(true)
  expect(packetNeedsResubmit({ ...base, review: { done: true,
    fields: { cccd: { seen: true, flag: { reason: 'sai', note: '' } } } } })).toBe(true)
})

test('reportUrls point at the backend', () => {
  expect(reportUrls('abc').md).toBe(`${API_BASE}/api/cases/abc/report.md`)
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/upload/api.test.ts`
Expected: FAIL (exports missing).

- [ ] **Step 3: Implement**

In `src/upload/api.ts`:
- Add types (place near the existing case types):
```ts
export type MatchedBy = 'cccd' | 'name' | 'unmatched' | 'no-roster'
export interface Identity { cccd: string; name: string }
export interface FieldFlag { reason: string; note: string }
export interface FieldReview { seen: boolean; flag: FieldFlag | null }
export interface PacketReview { done: boolean; fields: Record<string, FieldReview> }
```
- In `PacketMeta`, **remove** `decision`, `rejectReason`, `reviewedAt`; **add**:
```ts
  matchedBy: MatchedBy
  ocrIdentity: Identity
  rosterIdentity: Identity | null
  review: PacketReview
```
- In `CaseProgress`, rename `decided` → `done`.
- Replace `setDecision` with:
```ts
export async function setReview(
  caseId: string, index: number, review: PacketReview,
): Promise<{ packet: PacketMeta; progress: CaseProgress; status: CaseState }> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/packets/${index}/review`, {
    method: 'PUT', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(review),
  })
  if (!res.ok) throw new Error(`setReview: HTTP ${res.status}`)
  return res.json()
}

export interface ReportItem {
  fieldKey: string; fieldLabel: string; document: string; page: number | null
  rosterValue: string; docValue: string; reason: string; note: string
}
export interface ReportGroup {
  index: number; name: string; cccd: string; matchedBy: MatchedBy
  identityIssue: boolean; items: ReportItem[]
}
export interface Report { groups: ReportGroup[]; markdown: string; csv: string }

export async function generateReport(caseId: string): Promise<Report> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/report`, { method: 'POST' })
  if (!res.ok) throw new Error(`generateReport: HTTP ${res.status}`)
  return res.json()
}

export function reportUrls(caseId: string) {
  return {
    md: `${API_BASE}/api/cases/${caseId}/report.md`,
    csv: `${API_BASE}/api/cases/${caseId}/report.csv`,
  }
}

export function packetNeedsResubmit(p: PacketMeta): boolean {
  const flagged = Object.values(p.review?.fields ?? {}).some(f => f.flag)
  return flagged || p.matchedBy === 'name' || p.matchedBy === 'unmatched'
}
```
- Update `caseProgressLabel` to use `p.done` (was `p.decided`): `` `${p.done}/${p.total} đã xong` `` (+ the existing `· N cần xem`, reworded to `· N cần gửi lại` using `p.flagged`). Remove `decisionBadge` + `Decision` type (replaced by packet status in Task 8's helper).

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run src/upload/api.test.ts`
Expected: PASS. Then `npx tsc --noEmit` will show every consumer of the removed symbols — those are fixed in Tasks 8/11/12/13/14. That's expected mid-refactor.

- [ ] **Step 5: Commit**

```bash
git add src/upload/api.ts src/upload/api.test.ts
git commit -m "feat(api-client): review + report types/functions; match info on PacketMeta"
```

### Task 7: Pure review helpers (seen gate, status, callout anchor)

**Files:**
- Create: `src/logic/review.ts`
- Test: `src/logic/review.test.ts`

- [ ] **Step 1: Write failing tests**

Create `src/logic/review.test.ts`:
```ts
import { allSeen, packetStatus, calloutAnchor } from './review'

test('allSeen requires every field key seen', () => {
  const r = { done: false, fields: { a: { seen: true, flag: null } } }
  expect(allSeen(r, ['a'])).toBe(true)
  expect(allSeen(r, ['a', 'b'])).toBe(false)
})

test('packetStatus derivation', () => {
  const clean = { matchedBy: 'cccd', review: { done: true, fields: {} } } as any
  expect(packetStatus(clean)).toBe('clear')
  expect(packetStatus({ ...clean, review: { done: false, fields: {} } })).toBe('untouched')
  expect(packetStatus({ ...clean, review: { done: false,
    fields: { a: { seen: true, flag: null } } } })).toBe('in_review')
  expect(packetStatus({ ...clean, matchedBy: 'name' })).toBe('needs_resubmit')
})

test('calloutAnchor flips below when no room above', () => {
  const box = { left: 100, top: 5, width: 200, height: 30 }
  const a = calloutAnchor(box, 40, 800)        // calloutH=40, paneH=800
  expect(a.placement).toBe('below')
  const b = calloutAnchor({ ...box, top: 400 }, 40, 800)
  expect(b.placement).toBe('above')
})
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run src/logic/review.test.ts`
Expected: FAIL (module missing).

- [ ] **Step 3: Implement**

Create `src/logic/review.ts`:
```ts
import type { PacketReview, PacketMeta } from '../upload/api'

export type PacketStatusKind = 'untouched' | 'in_review' | 'clear' | 'needs_resubmit'

export function allSeen(review: PacketReview, fieldKeys: string[]): boolean {
  return fieldKeys.every(k => review.fields[k]?.seen === true)
}

function needsResubmit(p: Pick<PacketMeta, 'matchedBy' | 'review'>): boolean {
  const flagged = Object.values(p.review?.fields ?? {}).some(f => f.flag)
  return flagged || p.matchedBy === 'name' || p.matchedBy === 'unmatched'
}

export function packetStatus(p: Pick<PacketMeta, 'matchedBy' | 'review'>): PacketStatusKind {
  if (!p.review?.done) {
    return Object.values(p.review?.fields ?? {}).some(f => f.seen) ? 'in_review' : 'untouched'
  }
  return needsResubmit(p) ? 'needs_resubmit' : 'clear'
}

export const PACKET_STATUS_LABEL: Record<PacketStatusKind, string> = {
  untouched: 'Chưa xem',
  in_review: 'Đang xem',
  clear: 'Xong · sạch',
  needs_resubmit: 'Xong · cần gửi lại',
}

// Position the roster callout relative to a field box (viewport px). Prefer just
// above the box; flip below when there isn't `calloutH` px of room above.
export function calloutAnchor(
  box: { left: number; top: number; width: number; height: number },
  calloutH: number,
  paneH: number,
): { left: number; top: number; placement: 'above' | 'below' } {
  const above = box.top >= calloutH + 8
  return above
    ? { left: box.left, top: box.top - calloutH - 8, placement: 'above' }
    : { left: box.left, top: Math.min(box.top + box.height + 8, paneH - calloutH), placement: 'below' }
}
```

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run src/logic/review.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/logic/review.ts src/logic/review.test.ts
git commit -m "feat(review-logic): seen gate, packet status, roster-callout anchor (pure)"
```

### Task 8: MatchKeyStrip component (badge + identity comparison)

**Files:**
- Create: `src/components/MatchKeyStrip.tsx`
- Modify: `src/styles.css`

- [ ] **Step 1: Implement the component**

Create `src/components/MatchKeyStrip.tsx`:
```tsx
import type { MatchedBy, Identity } from '../upload/api'

interface Props { matchedBy: MatchedBy; ocr: Identity; roster: Identity | null }

const BADGE: Record<MatchedBy, { label: string; cls: string }> = {
  cccd: { label: 'Khớp theo CCCD', cls: 'ok' },
  name: { label: 'Khớp theo tên', cls: 'warn' },
  unmatched: { label: 'Chưa khớp bảng kê', cls: 'bad' },
  'no-roster': { label: 'Không có bảng kê', cls: 'muted' },
}

export default function MatchKeyStrip({ matchedBy, ocr, roster }: Props) {
  const badge = BADGE[matchedBy]
  const cccdMismatch = !!roster && ocr.cccd !== roster.cccd
  const nameMismatch = !!roster && ocr.name.toUpperCase() !== roster.name.toUpperCase()
  return (
    <div className="matchkey">
      <span className={`match-badge ${badge.cls}`}>{badge.label}</span>
      {roster && (
        <table className="match-strip">
          <thead><tr><th></th><th>Từ chứng từ</th><th>Từ bảng kê</th></tr></thead>
          <tbody>
            <tr className={cccdMismatch ? 'diff' : ''}>
              <td>CCCD</td><td>{ocr.cccd || '—'}</td><td>{roster.cccd || '—'}</td>
            </tr>
            <tr className={nameMismatch ? 'diff' : ''}>
              <td>Tên</td><td>{ocr.name || '—'}</td><td>{roster.name || '—'}</td>
            </tr>
          </tbody>
        </table>
      )}
    </div>
  )
}
```

- [ ] **Step 2: Add styles**

In `src/styles.css` add (follow existing token/color conventions):
```css
.matchkey { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; }
.match-badge { font-size: 11px; padding: 2px 8px; border-radius: 10px; font-weight: 600; }
.match-badge.ok { background: #e6f4ea; color: #137333; }
.match-badge.warn { background: #fef7e0; color: #b06000; }
.match-badge.bad { background: #fce8e6; color: #c5221f; }
.match-badge.muted { background: var(--surface-2, #eee); color: var(--text-muted); }
.match-strip { border-collapse: collapse; font-size: 12px; }
.match-strip th, .match-strip td { padding: 2px 10px; text-align: left; border: 0.5px solid var(--border); }
.match-strip tr.diff td { background: #fce8e6; color: #c5221f; font-weight: 600; }
```

- [ ] **Step 3: Verify build**

Run: `npx tsc --noEmit` (the new file compiles; other errors from Task 6 remain until later tasks).

- [ ] **Step 4: Commit**

```bash
git add src/components/MatchKeyStrip.tsx src/styles.css
git commit -m "feat(ui): MatchKeyStrip — match badge + OCR-vs-roster identity strip"
```

### Task 9: Roster-value callout on the doc view (`EvidenceViewer`)

**Files:**
- Modify: `src/components/EvidenceViewer.tsx`, `src/styles.css`

- [ ] **Step 1: Add props + state**

In `EvidenceViewer.tsx`:
- Extend `Props` with the focused field's roster info:
```ts
  rosterLabel?: string       // focused field label, e.g. "Số CCCD"
  rosterValue?: string | null // focused field's expected value (bảng kê)
```
- Add state next to the other toggles: `const [showRoster, setShowRoster] = useState(true) // V: pin roster value`.
- Import the anchor helper: `import { calloutAnchor } from '../logic/review'`.

- [ ] **Step 2: Add the `V` hotkey**

Mirror the existing `B` handler (input-focus guard, no modifiers):
```tsx
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
      if (e.key === 'v' || e.key === 'V') { e.preventDefault(); setShowRoster(v => !v) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])
```

- [ ] **Step 3: Render the callout**

After the existing highlight (`{hl && …}`) inside `.ev-stage`, add:
```tsx
        {showRoster && rosterValue && (
          hl
            ? (() => {
                const CALLOUT_H = 52
                const a = calloutAnchor(hl, CALLOUT_H, vp.h)
                return (
                  <div className={`roster-callout ${a.placement}`}
                    style={{ left: a.left, top: a.top }}>
                    <div className="roster-callout-lbl">Bảng kê — {rosterLabel}</div>
                    <div className="roster-callout-val">{rosterValue}</div>
                  </div>
                )
              })()
            : (
              <div className="roster-callout corner">
                <div className="roster-callout-lbl">Bảng kê — {rosterLabel}</div>
                <div className="roster-callout-val">{rosterValue}</div>
              </div>
            )
        )}
```

- [ ] **Step 4: Add the toolbar toggle button**

In `.doc-tools`, next to the box-toggle button, add:
```tsx
          <button className={showRoster ? 'on' : ''} onClick={() => setShowRoster(v => !v)}
            aria-label="Ẩn/hiện giá trị bảng kê" title="Giá trị bảng kê (V)">🏷</button>
```

- [ ] **Step 5: Add styles**

In `src/styles.css`:
```css
.roster-callout { position: absolute; z-index: 5; pointer-events: none;
  background: #1a73e8; color: #fff; border-radius: 8px; padding: 4px 10px;
  box-shadow: 0 2px 8px rgba(0,0,0,.25); max-width: 60%; }
.roster-callout.corner { left: 12px !important; top: 12px !important; }
.roster-callout-lbl { font-size: 10px; text-transform: uppercase; letter-spacing: .04em; opacity: .85; }
.roster-callout-val { font-size: 20px; font-weight: 700; line-height: 1.15; word-break: break-word; }
```

- [ ] **Step 6: Verify build**

Run: `npx tsc --noEmit` (EvidenceViewer compiles given the new optional props; `FolderReview` will pass them in Task 12).

- [ ] **Step 7: Commit**

```bash
git add src/components/EvidenceViewer.tsx src/styles.css
git commit -m "feat(ui): pin roster value on the doc view, anchored to the field (toggle V)"
```

### Task 10: Fields panel — progress meter, seen dots, flag toggle + note

**Files:**
- Modify: `src/components/FolderFieldsPanel.tsx`, `src/styles.css`

- [ ] **Step 1: Extend props**

Add to `Props`:
```ts
  review: PacketReview                       // import type from '../upload/api'
  onToggleFlag: (fieldKey: string, flag: FieldFlag | null) => void
```
Compute at top of the component:
```ts
  const total = ranked.length
  const seen = ranked.filter(r => review.fields[r.field.key]?.seen).length
```

- [ ] **Step 2: Progress meter**

In `.fields-summary`, append:
```tsx
        <span className="seen-progress">{seen}/{total} đã xem</span>
```

- [ ] **Step 3: Seen dot + flag control per field**

In the `.cfield-head` row, add a seen dot before the chip and a flag toggle after the tag:
```tsx
            <span className={`seen-dot ${review.fields[r.field.key]?.seen ? 'on' : ''}`} />
            <span className={`chip ${chip.cls}`}>{chip.glyph}</span>
            <span className="flabel">{r.field.label}</span>
            <span className="ftag">{r.field.group}</span>
            <button className={`flag-btn ${review.fields[r.field.key]?.flag ? 'on' : ''}`}
              title="Đánh dấu cần gửi lại (F)"
              onClick={e => {
                e.stopPropagation()
                const cur = review.fields[r.field.key]?.flag
                onToggleFlag(r.field.key, cur ? null : { reason: '', note: '' })
              }}>⚑</button>
```
When flagged and selected, render a note editor under the field (after `.cfield-exp`):
```tsx
            {review.fields[r.field.key]?.flag && sel && (
              <div className="flag-editor" onClick={e => e.stopPropagation()}>
                <div className="flag-reasons">
                  {['sai', 'thiếu', 'mờ, không đọc được'].map(rs => (
                    <button key={rs}
                      className={review.fields[r.field.key]!.flag!.reason === rs ? 'on' : ''}
                      onClick={() => onToggleFlag(r.field.key,
                        { ...review.fields[r.field.key]!.flag!, reason: rs })}>{rs}</button>
                  ))}
                </div>
                <input className="flag-note" placeholder="Ghi chú (tuỳ chọn)"
                  value={review.fields[r.field.key]!.flag!.note}
                  onChange={e => onToggleFlag(r.field.key,
                    { ...review.fields[r.field.key]!.flag!, note: e.target.value })} />
              </div>
            )}
```

- [ ] **Step 4: Styles**

In `src/styles.css`:
```css
.seen-progress { margin-left: auto; color: var(--text-muted); font-variant-numeric: tabular-nums; }
.seen-dot { width: 8px; height: 8px; border-radius: 50%; border: 1.5px solid var(--border); flex: none; }
.seen-dot.on { background: var(--accent); border-color: var(--accent); }
.flag-btn { margin-left: 6px; border: none; background: none; cursor: pointer; opacity: .4; }
.flag-btn.on { opacity: 1; color: #c5221f; }
.flag-editor { display: flex; flex-direction: column; gap: 6px; margin-top: 6px; }
.flag-reasons { display: flex; gap: 6px; flex-wrap: wrap; }
.flag-reasons button { font-size: 11px; padding: 2px 8px; border: 0.5px solid var(--border);
  border-radius: 10px; background: var(--surface); cursor: pointer; }
.flag-reasons button.on { background: #fce8e6; color: #c5221f; border-color: #c5221f; }
.flag-note { font-size: 12px; padding: 4px 8px; border: 0.5px solid var(--border); border-radius: 6px; }
```

- [ ] **Step 5: Verify build**

Run: `npx tsc --noEmit` (panel compiles; `FolderReview` supplies the new props in Task 12).

- [ ] **Step 6: Commit**

```bash
git add src/components/FolderFieldsPanel.tsx src/styles.css
git commit -m "feat(ui): fields panel — seen progress, seen dots, per-field flag + note"
```

### Task 11: ActionBar → Done-gated finish bar

**Files:**
- Modify: `src/components/ActionBar.tsx`

- [ ] **Step 1: Replace the component body**

Rewrite `src/components/ActionBar.tsx`:
```tsx
interface ActionBarProps {
  done: boolean
  seenCount: number
  total: number
  hint?: string
  onFinish: () => void
}

export default function ActionBar({ done, seenCount, total, hint, onFinish }: ActionBarProps) {
  const remaining = total - seenCount
  const canFinish = remaining <= 0
  if (done) {
    return (
      <div className="action-bar">
        <span className="final approved">✓ Đã xem xong</span>
      </div>
    )
  }
  return (
    <div className="action-bar">
      <span className="hint">{hint ?? '↑↓ chuyển trường'}</span>
      <div className="actions">
        <span className="seen-progress">{seenCount}/{total} đã xem</span>
        <button className="btn primary" disabled={!canFinish} onClick={onFinish}
          title={canFinish ? 'Đánh dấu đã xem xong' : `Còn ${remaining} trường chưa xem`}>
          ✓ Xong
        </button>
      </div>
    </div>
  )
}
```
(The `CaseStatus` import is no longer needed here — remove it.)

- [ ] **Step 2: Verify build**

Run: `npx tsc --noEmit` (its only consumer is `FolderReview`, updated next).

- [ ] **Step 3: Commit**

```bash
git add src/components/ActionBar.tsx
git commit -m "feat(ui): ActionBar becomes the Done gate (disabled until all fields seen)"
```

### Task 12: FolderReview — wire seen, flags, Done, roster callout, match strip

**Files:**
- Modify: `src/components/FolderReview.tsx`

- [ ] **Step 1: Change props + hold review state**

New `Props`:
```ts
import type { PacketReview, FieldFlag, MatchedBy, Identity } from '../upload/api'
import MatchKeyStrip from './MatchKeyStrip'
import { allSeen } from '../logic/review'

interface Props {
  folder: CtvFolder
  review: PacketReview
  matchedBy: MatchedBy
  ocrIdentity: Identity
  rosterIdentity: Identity | null
  onReview: (review: PacketReview) => void   // persists (debounced/flushed by parent)
}
```
Keep `review` as the source of truth from props; all mutations call `onReview(next)`.

- [ ] **Step 2: Mark seen on focus**

In `focusAt`, after setting selection, mark the field seen:
```tsx
  const markSeen = (key: string) => {
    if (review.fields[key]?.seen) return
    onReview({ ...review, fields: { ...review.fields,
      [key]: { seen: true, flag: review.fields[key]?.flag ?? null } } })
  }
```
Call `markSeen(key)` inside `focusAt(key, idx)`. Also mark the initial `first` field seen once on mount (`useEffect(() => { if (first) markSeen(first.key) }, [])`).

- [ ] **Step 3: Flag handler + `F` hotkey**

```tsx
  const toggleFlag = (key: string, flag: FieldFlag | null) => {
    onReview({ ...review, fields: { ...review.fields,
      [key]: { seen: true, flag } } })
  }
```
Add an `F` key handler (input-guarded) that toggles the flag on `selectedKey`:
```tsx
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
      if (e.key === 'f' || e.key === 'F') {
        e.preventDefault()
        const cur = review.fields[selectedKey]?.flag
        toggleFlag(selectedKey, cur ? null : { reason: '', note: '' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [review, selectedKey])
```

- [ ] **Step 4: Header match strip + pass roster value to viewer**

- In `.screen-head`, replace the old status pill with `<MatchKeyStrip matchedBy={matchedBy} ocr={ocrIdentity} roster={rosterIdentity} />`.
- Compute the focused field: `const selField = folder.fields.find(f => f.key === selectedKey)`.
- Pass to `EvidenceViewer`: `rosterLabel={selField?.label} rosterValue={selField?.expected ?? null}`.

- [ ] **Step 5: Done gate via ActionBar**

```tsx
  const fieldKeys = folder.fields.map(f => f.key)
  const seenCount = fieldKeys.filter(k => review.fields[k]?.seen).length
  // ...
  <ActionBar
    done={review.done}
    seenCount={seenCount}
    total={fieldKeys.length}
    hint="↑↓ chuyển trường · ←→ đổi chứng từ · F đánh dấu · B khung · V giá trị bảng kê · ⌥P di chuyển · ? phím tắt"
    onFinish={() => { if (allSeen(review, fieldKeys)) onReview({ ...review, done: true }) }}
  />
```
Remove the old `onUpdate`/approve/reject wiring and the `folder.status` header pill.

- [ ] **Step 6: Verify build**

Run: `npx tsc --noEmit` (FolderReview itself compiles; `UploadFlow` supplies the new props next).

- [ ] **Step 7: Commit**

```bash
git add src/components/FolderReview.tsx
git commit -m "feat(ui): FolderReview — seen tracking, flags (F), Done gate, match strip, roster callout"
```

### Task 13: UploadFlow — persist review, pass match info, remove approve/reject

**Files:**
- Modify: `src/components/UploadFlow.tsx`

- [ ] **Step 1: Replace `onDecide` with review persistence**

- Import `setReview` (drop `setDecision`) and `PacketReview`.
- The `folder`/`detail`/`packetIndex` state stays. Add local review state for the open packet, seeded from the packet meta:
```tsx
  const [review, setReviewState] = useState<PacketReview>({ done: false, fields: {} })
```
- In `onOpenPacket(index)`, after fetching the manifest, seed review from the packet meta:
```tsx
      const meta = detail?.packets.find(p => p.index === index)
      setReviewState(meta?.review ?? { done: false, fields: {} })
```
- Add a debounced/flush persister:
```tsx
  const flushReview = async (r: PacketReview) => {
    if (!caseId || packetIndex == null) return
    try {
      const res = await setReview(caseId, packetIndex, r)
      // keep detail in sync so the grid + prev/next reflect new status
      setDetail(d => d && ({ ...d, packets: d.packets.map(p =>
        p.index === packetIndex ? res.packet : p), status: res.status, progress: res.progress }))
    } catch { setErr(CONN_ERR) }
  }
```
Call `setReviewState(r)` immediately on every `onReview(r)`, and `flushReview(r)` on flag/done changes; for seen-only changes, flush on packet navigation (Back / prev / next). Simplest correct approach: persist on every `onReview` (network call is cheap on localhost) — acceptable for the prototype; note it.

- [ ] **Step 2: Render FolderReview with the new props**

```tsx
      const meta = detail?.packets.find(p => p.index === packetIndex)
      // ...
      <FolderReview
        key={packetIndex ?? folder.id}
        folder={folder}
        review={review}
        matchedBy={meta?.matchedBy ?? 'no-roster'}
        ocrIdentity={meta?.ocrIdentity ?? { cccd: '', name: '' }}
        rosterIdentity={meta?.rosterIdentity ?? null}
        onReview={r => { setReviewState(r); flushReview(r) }}
      />
```
Delete the old `onDecide` function and its approve/reject branches.

- [ ] **Step 3: Verify build**

Run: `npx tsc --noEmit`
Expected: PASS across the project now (all removed-symbol errors resolved).

- [ ] **Step 4: Commit**

```bash
git add src/components/UploadFlow.tsx
git commit -m "feat(ui): persist packet review (seen/flags/done); drop approve/reject flow"
```

### Task 14: CaseDetail — match badge, submission summary, export button

**Files:**
- Modify: `src/components/CaseDetail.tsx`, `src/styles.css`

- [ ] **Step 1: Packet card — status + match badge**

Replace the `decision-badge` usage with the derived packet status and a compact match badge:
```tsx
import { packetStatus, PACKET_STATUS_LABEL } from '../logic/review'
// in PacketCard:
  const status = packetStatus(p)
  // ...
  <div className={`decision-badge ${status}`}>{PACKET_STATUS_LABEL[status]}</div>
  {p.matchedBy === 'name' && <span className="card-match warn">khớp theo tên</span>}
  {p.matchedBy === 'unmatched' && <span className="card-match bad">chưa khớp bảng kê</span>}
```

- [ ] **Step 2: Submission summary + export button**

In the header/banner area, add a summary line and the export button (wired in Task 15):
```tsx
  const flaggedPackets = packets.filter(packetNeedsResubmit).length   // import from api
  const flaggedFields = packets.reduce((n, p) =>
    n + Object.values(p.review?.fields ?? {}).filter(f => f.flag).length, 0)
  // ...
  <div className="case-summary">
    <span>{packets.length} gói · {flaggedPackets} cần gửi lại · {flaggedFields} trường có vấn đề</span>
    <button className="btn primary" onClick={onExport}>Xuất báo cáo gửi lại</button>
  </div>
```
Add `onExport: () => void` to `Props`.

- [ ] **Step 3: Styles**

```css
.case-summary { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 8px 0 16px; }
.card-match { font-size: 10px; padding: 1px 6px; border-radius: 8px; }
.card-match.warn { background: #fef7e0; color: #b06000; }
.card-match.bad { background: #fce8e6; color: #c5221f; }
.decision-badge.clear { color: #137333; }
.decision-badge.needs_resubmit { color: #c5221f; }
.decision-badge.in_review { color: #b06000; }
.decision-badge.untouched { color: var(--text-muted); }
```

- [ ] **Step 4: Verify build**

Run: `npx tsc --noEmit` (CaseDetail needs `onExport` from `UploadFlow` — add a temporary `onExport={() => {}}` at its call site now; Task 15 wires it).

- [ ] **Step 5: Commit**

```bash
git add src/components/CaseDetail.tsx src/components/UploadFlow.tsx src/styles.css
git commit -m "feat(ui): case detail — packet status + match badges, submission summary, export button"
```

### Task 15: ReportPanel — preview, copy, download

**Files:**
- Create: `src/components/ReportPanel.tsx`
- Modify: `src/components/UploadFlow.tsx`, `src/styles.css`

- [ ] **Step 1: Component**

Create `src/components/ReportPanel.tsx`:
```tsx
import { useEffect, useState } from 'react'
import { generateReport, reportUrls, type Report } from '../upload/api'

interface Props { caseId: string; onClose: () => void }

export default function ReportPanel({ caseId, onClose }: Props) {
  const [report, setReport] = useState<Report | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    generateReport(caseId).then(setReport).catch(() => setErr('Không tạo được báo cáo.'))
  }, [caseId])

  const urls = reportUrls(caseId)
  return (
    <div className="report-overlay" onClick={onClose}>
      <div className="report-panel" onClick={e => e.stopPropagation()}>
        <div className="report-head">
          <h3>Báo cáo cần gửi lại</h3>
          <button className="btn" onClick={onClose}>Đóng</button>
        </div>
        {err && <p className="upload-error">{err}</p>}
        {!report && !err && <p>Đang tạo…</p>}
        {report && (
          <>
            <div className="report-actions">
              <button className="btn" onClick={() => {
                navigator.clipboard.writeText(report.markdown)
                setCopied(true); setTimeout(() => setCopied(false), 1500)
              }}>{copied ? 'Đã sao chép' : 'Sao chép (Markdown)'}</button>
              <a className="btn" href={urls.md} download={`bao-cao-${caseId}.md`}>Tải .md</a>
              <a className="btn" href={urls.csv} download={`bao-cao-${caseId}.csv`}>Tải .csv</a>
            </div>
            {report.groups.length === 0
              ? <p className="report-empty">Không có mục nào cần gửi lại. 🎉</p>
              : <pre className="report-preview">{report.markdown}</pre>}
          </>
        )}
      </div>
    </div>
  )
}
```

- [ ] **Step 2: Wire into UploadFlow**

- Add state: `const [showReport, setShowReport] = useState(false)`.
- Pass `onExport={() => setShowReport(true)}` to `<CaseDetail />` (replacing the temporary stub).
- Render `{showReport && caseId && <ReportPanel caseId={caseId} onClose={() => setShowReport(false)} />}` inside the detail screen branch.

- [ ] **Step 3: Styles**

```css
.report-overlay { position: fixed; inset: 0; background: rgba(0,0,0,.4); display: flex;
  align-items: center; justify-content: center; z-index: 50; }
.report-panel { background: var(--bg); border-radius: 12px; padding: 20px; width: min(760px, 92vw);
  max-height: 86vh; display: flex; flex-direction: column; gap: 12px; }
.report-head { display: flex; align-items: center; justify-content: space-between; }
.report-actions { display: flex; gap: 8px; }
.report-preview { flex: 1; overflow: auto; background: var(--surface); border: 0.5px solid var(--border);
  border-radius: 8px; padding: 12px; font: 12px/1.5 ui-monospace, monospace; white-space: pre-wrap; }
.report-empty { color: var(--text-muted); }
```

- [ ] **Step 4: Verify build**

Run: `npx tsc --noEmit`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/components/ReportPanel.tsx src/components/UploadFlow.tsx src/styles.css
git commit -m "feat(ui): ReportPanel — generate/preview/copy/download the resubmission report"
```

### Task 16: Hotkey legend, full test + browser verification

**Files:**
- Modify: `src/components/HotkeyHelp.tsx`

- [ ] **Step 1: Add F and V to the legend**

In `HotkeyHelp.tsx`, add rows: `F` — "Đánh dấu trường cần gửi lại"; `V` — "Ẩn/hiện giá trị bảng kê trên chứng từ". (Match the existing row structure in that file.)

- [ ] **Step 2: Run all unit tests + typecheck**

Run: `npx vitest run && npx tsc --noEmit`
Expected: all vitest green, tsc clean.
Run: `cd server && python -m pytest -q`
Expected: all backend green.

- [ ] **Step 3: Browser verification (per the project's launch flow)**

Start backend (`uvicorn`) + Vite (see the run flow), open a ready case, and confirm:
- Focusing fields fills the "n/n đã xem" meter; **✓ Xong** is disabled until all seen (tooltip "Còn N trường chưa xem"), then enabled.
- Pressing `F` (or ⚑) flags the focused field; reason chips + note input appear; the field styles as flagged.
- The **roster callout** shows above the focused field, tracks it on zoom/pan, stays legible zoomed out, falls back to a corner chip on an unlocated ("cần xem") field, and toggles with `V` independently of `B`.
- The review header shows the **match strip**; force a `Khớp theo tên` packet and confirm the CCCD row highlights as different.
- Mark the packet **Done** → its card shows `Xong · cần gửi lại`; a clean packet shows `Xong · sạch`.
- On case detail, the summary counts update; **Xuất báo cáo gửi lại** opens the panel with the flagged CTV(s) grouped, the identity-issue note present, and `.md`/`.csv` downloads working.
- Take a screenshot of the reviewer (callout + flag) and the report panel as proof.

- [ ] **Step 4: Commit**

```bash
git add src/components/HotkeyHelp.tsx
git commit -m "feat(ui): add F (flag) and V (roster value) to the hotkey legend"
```

---

## Self-review notes (verify during execution)

- **Spec coverage:** seen-tracking + Done gate (T7,T10,T11,T12) · match-key visibility (T3,T8,T12,T14) · flagging with notes (T10,T12) · server report md+csv persisted (T4,T5,T15) · roster value pinned (T7,T9,T12) · approve/reject removed (T6,T11,T12,T13) · migration (T2). All covered.
- **Type consistency:** `PacketReview{done,fields}`, `FieldReview{seen,flag}`, `FieldFlag{reason,note}`, `matchedBy/ocrIdentity/rosterIdentity`, `CaseProgress{done,total,flagged}` are used identically across backend JSON and TS. `packetStatus`/`allSeen`/`calloutAnchor` names match between `review.ts` and its callers.
- **Known simplification (noted, intentional):** the report anchors a flagged field to its **first source** for document/page/docValue; the flag itself stores only `reason`+`note` (not which doc was on screen at flag time). Fine for the prototype; extend the flag with `docId`/`page` later if the exact viewed page matters.
- **Migration:** legacy `decision` packets reset to unreviewed (throwaway prototype; acceptable per spec).
