# v2.0 — Checklist Reviewer Rebuild — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the flat 6-field reviewer with the **two-tier coded checklist** (Preconditions gates + Detail checks) from the Acc requirements and the mockup, keeping the **real scanned document** as the evidence pane. Ends by building `Reviewer-v2.0.html` so v1.0 and v2.0 can be demoed side by side.

**Architecture:** A backend **checklist builder** turns each packet's existing OCR fields + match key + segmented docs into an ordered list of coded `CheckItem`s written into the manifest. Per-packet review state is re-keyed from field-key (`review.fields`) to **check-code** (`review.items`). The reviewer renders `checks` grouped by tier; the scan pane (`EvidenceViewer`) is unchanged and is focused by the selected check's evidence. Three assist levels drive each row: **auto** (G-ID), **value-assisted** (roster value + located source on the scan), **document-routed confirm** (open the doc tab, human confirms).

**Tech Stack:** FastAPI + `pytest` (backend); Vite + React 18 + TS, `vitest` + browser verification (frontend). Spec: `docs/superpowers/specs/2026-07-23-checklist-reviewer-rebuild-design.md`.

## Canonical shapes (identical across backend JSON + TS — do not drift)

**`CheckItem`** (in each packet's `manifest.json` under `checks`, and TS `ctv/types.ts`):
```jsonc
{
  "code": "G-DOC",          // G-DOC G-ID D3 B3 C2 | B1 A1 A2 B2 BANK INFO C1 D1
  "label": "Đủ chứng từ bắt buộc",
  "tier": "gate",            // "gate" | "detail"
  "kind": "confirm",         // "value" | "identity" | "confirm"
  "evidenceDocId": "contract", // doc id to focus; null = packet-level (G-DOC)
  "reference": null,          // roster value (kind "value"); else null
  "source": null,             // located {docId,page,value,bbox,confidence} (kind "value"); else null
  "autostatus": null          // "match"|"mismatch"|"review" for value/identity; null for confirm
}
```

**Per-packet review state** (`case.json` packet dict; replaces `review.fields`):
```jsonc
"review": { "done": false, "items": { "<code>": { "seen": true, "flag": null } } }
```
`flag` = `null | {reason, note}`. Keyed by **check code**.

**v1 checklist (order + mapping)** — the builder emits exactly these, gates first:

| # | code | label | tier | kind | evidence (doc kind) | data |
|---|------|-------|------|------|--------------------|------|
| 1 | G-DOC | Đủ chứng từ bắt buộc | gate | confirm | (packet) | — |
| 2 | G-ID | Đúng người — CCCD & tên khớp | gate | identity | contract | match key |
| 3 | D3 | Cam kết TNCN đúng mẫu năm hiện hành | gate | confirm | commitment | — |
| 4 | B3 | Hợp đồng đủ chữ ký & con dấu | gate | confirm | contract | — |
| 5 | C2 | BBNT đủ chữ ký, con dấu & giáp lai | gate | confirm | bbnt | — |
| 6 | B1 | Họ tên khớp bảng kê | detail | value | contract | field `name` |
| 7 | A1 | Số CCCD khớp giữa chứng từ | detail | value | contract | field `cccd` |
| 8 | A2 | Mã số thuế khớp bảng kê | detail | value | contract | field `mst` |
| 9 | B2 | Phí dịch vụ khớp bảng kê | detail | value | contract | field `phi` |
| 10 | BANK | Số tài khoản khớp bảng kê | detail | value | contract | field `tk` |
| 11 | INFO | Ngày sinh khớp hồ sơ | detail | value | contract | field `ngaysinh` |
| 12 | C1 | Nội dung & thời gian khớp BBNT | detail | confirm | bbnt | — |
| 13 | D1 | Thông tin & MST khớp cam kết | detail | confirm | commitment | — |

Doc kinds present in manifests: `contract, bbnt, commitment, pit, appendix, id_front, id_back` (see `src/ctv/types.ts`). `docByKind` returns the first doc of that kind, or `None`.

---

# Phase 1 — Backend

### Task 1: `checklist.py` — pure `build_checklist` (the crux)

**Files:** Create `server/checklist.py`; Test `server/checklist_test.py`.

- [ ] **Step 1: Write failing tests** — `server/checklist_test.py`:
```python
from checklist import build_checklist

FIELDS = [
  {"key": "name", "label": "Họ và tên", "expected": "Nguyễn Hoàng Phúc",
   "sources": [{"docId": "contract", "page": 0, "value": "Nguyễn Hoàng Phúc", "bbox": {"x":1,"y":1,"width":1,"height":1}, "confidence": 0.9}]},
  {"key": "mst", "label": "MST", "expected": "095204007694",
   "sources": [{"docId": "contract", "page": 0, "value": "8391246072", "bbox": {"x":1,"y":1,"width":1,"height":1}, "confidence": 0.9}]},
  {"key": "phi", "label": "Phí", "expected": "5.555.556", "sources": []},
]
DOCS = [{"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ"},
        {"id": "bbnt", "kind": "bbnt", "label": "Biên bản thanh lý"},
        {"id": "camket", "kind": "commitment", "label": "Bản cam kết"}]
MATCH = {"matchedBy": "cccd", "ocrIdentity": {"cccd": "079", "name": "X"}, "rosterIdentity": {"cccd": "079", "name": "X"}}

def _by_code(checks): return {c["code"]: c for c in checks}

def test_emits_gates_first_then_detail_in_order():
    checks = build_checklist(FIELDS, MATCH, DOCS)
    codes = [c["code"] for c in checks]
    assert codes[:5] == ["G-DOC", "G-ID", "D3", "B3", "C2"]
    assert set(codes[5:]) <= {"B1","A1","A2","B2","BANK","INFO","C1","D1"}
    assert all(c["tier"] == "gate" for c in checks[:5])

def test_value_check_carries_reference_source_and_autostatus():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["B1"]["kind"] == "value" and c["B1"]["reference"] == "Nguyễn Hoàng Phúc"
    assert c["B1"]["source"]["value"] == "Nguyễn Hoàng Phúc" and c["B1"]["autostatus"] == "match"
    assert c["A2"]["autostatus"] == "mismatch"          # 8391246072 != 095204007694
    assert c["B2"]["autostatus"] == "review"            # no source

def test_identity_and_confirm_kinds():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["G-ID"]["kind"] == "identity" and c["G-ID"]["autostatus"] == "match"
    assert c["B3"]["kind"] == "confirm" and c["B3"]["evidenceDocId"] == "contract"
    assert c["C2"]["evidenceDocId"] == "bbnt" and c["D3"]["evidenceDocId"] == "camket"
    assert c["G-DOC"]["evidenceDocId"] is None

def test_weak_match_identity_is_review():
    c = _by_code(build_checklist(FIELDS, {**MATCH, "matchedBy": "name"}, DOCS))
    assert c["G-ID"]["autostatus"] == "review"
```

- [ ] **Step 2: Run to verify failure** — `cd server && python3 -m pytest checklist_test.py -q` → FAIL (no module).

- [ ] **Step 3: Implement** — `server/checklist.py`:
```python
"""Pure builder: per-packet OCR fields + match key + segmented docs -> the coded,
two-tier review checklist (CheckItem dicts). No IO/OCR here; unit tested. The
pipeline calls this and writes the result into each packet's manifest under `checks`."""
from __future__ import annotations
import re, unicodedata

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    return "".join(ch for ch in s if not unicodedata.combining(ch)).casefold().strip()

def _digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")

def _autostatus(reference: str, source: dict | None) -> str:
    val = (source or {}).get("value", "")
    if not source or not val:
        return "review"
    # numeric-ish values compare by digits; else accent-insensitive text
    if _digits(reference) and _digits(val):
        return "match" if _digits(reference) == _digits(val) else "mismatch"
    return "match" if _norm(reference) == _norm(val) else "mismatch"

def _doc_by_kind(docs: list[dict], kind: str) -> str | None:
    for d in docs:
        if d.get("kind") == kind:
            return d["id"]
    return None

# code -> (label, evidence doc kind, source field key)
_VALUE = [
    ("B1", "Họ tên khớp bảng kê", "contract", "name"),
    ("A1", "Số CCCD khớp giữa chứng từ", "contract", "cccd"),
    ("A2", "Mã số thuế khớp bảng kê", "contract", "mst"),
    ("B2", "Phí dịch vụ khớp bảng kê", "contract", "phi"),
    ("BANK", "Số tài khoản khớp bảng kê", "contract", "tk"),
    ("INFO", "Ngày sinh khớp hồ sơ", "contract", "ngaysinh"),
]
_CONFIRM_GATES = [
    ("D3", "Cam kết TNCN đúng mẫu năm hiện hành", "commitment"),
    ("B3", "Hợp đồng đủ chữ ký & con dấu", "contract"),
    ("C2", "BBNT đủ chữ ký, con dấu & giáp lai", "bbnt"),
]
_CONFIRM_DETAIL = [
    ("C1", "Nội dung & thời gian khớp BBNT", "bbnt"),
    ("D1", "Thông tin & MST khớp cam kết", "commitment"),
]

def build_checklist(fields: list[dict], match: dict, docs: list[dict]) -> list[dict]:
    by_key = {f["key"]: f for f in fields}
    contract = _doc_by_kind(docs, "contract") or (docs[0]["id"] if docs else None)
    checks: list[dict] = []

    # --- Tier 1: gates ---
    checks.append({"code": "G-DOC", "label": "Đủ chứng từ bắt buộc", "tier": "gate",
                   "kind": "confirm", "evidenceDocId": None,
                   "reference": None, "source": None, "autostatus": None})
    matched_by = match.get("matchedBy", "no-roster")
    checks.append({"code": "G-ID", "label": "Đúng người — CCCD & tên khớp", "tier": "gate",
                   "kind": "identity", "evidenceDocId": contract,
                   "reference": (match.get("rosterIdentity") or {}).get("cccd", ""),
                   "source": {"docId": contract, "page": 0,
                              "value": (match.get("ocrIdentity") or {}).get("cccd", ""),
                              "bbox": None, "confidence": 1.0} if contract else None,
                   "autostatus": "match" if matched_by == "cccd" else "review"})
    for code, label, kind_doc in _CONFIRM_GATES:
        checks.append({"code": code, "label": label, "tier": "gate", "kind": "confirm",
                       "evidenceDocId": _doc_by_kind(docs, kind_doc),
                       "reference": None, "source": None, "autostatus": None})

    # --- Tier 2: detail ---
    for code, label, kind_doc, fkey in _VALUE:
        f = by_key.get(fkey)
        if not f:
            continue
        src = (f.get("sources") or [None])[0]
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "value",
                       "evidenceDocId": (src or {}).get("docId") or _doc_by_kind(docs, kind_doc),
                       "reference": f.get("expected", ""), "source": src,
                       "autostatus": _autostatus(f.get("expected", ""), src)})
    for code, label, kind_doc in _CONFIRM_DETAIL:
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "confirm",
                       "evidenceDocId": _doc_by_kind(docs, kind_doc),
                       "reference": None, "source": None, "autostatus": None})
    return checks
```
Note the gate order is G-DOC, G-ID, then the confirm gates (D3, B3, C2) — matching the canonical table.

- [ ] **Step 4: Run to verify pass** — `cd server && python3 -m pytest checklist_test.py -q` → PASS (4).
- [ ] **Step 5: Commit**
```bash
cd /Users/lap16603/Desktop/ap-review-prototype/.claude/worktrees/gracious-dijkstra-fbc604
git add server/checklist.py server/checklist_test.py
git commit -m "feat(checklist): pure build_checklist — fields+match+docs -> coded two-tier checks"
```

### Task 2: Pipeline writes `checks` into the manifest

**Files:** Modify `server/pipeline.py`; Test `server/pipeline_test.py`.

- [ ] **Step 1: Read** `server/pipeline.py` around the manifest build/write (the `oc.build_manifest(...)` call + `json.dump(manifest, ...)`, ~line 265-269) and where `identity`/`row`/`how` are in scope.

- [ ] **Step 2: Write failing test** — add to `pipeline_test.py` (reuse the existing `_install_fake_detection` harness from Task-3 of v1):
```python
def test_manifest_carries_checks(tmp_path, monkeypatch):
    result = run_fake_pipeline(tmp_path, monkeypatch)  # existing helper
    import json, os
    m = json.load(open(os.path.join(str(tmp_path), "packets", "0", "manifest.json"), encoding="utf-8"))
    codes = [c["code"] for c in m["checks"]]
    assert codes[:2] == ["G-DOC", "G-ID"]
    assert "B1" in codes
```
(If the helper writes to a different out dir, assert on the manifest path it uses.)

- [ ] **Step 3: Run → FAIL** (`KeyError: 'checks'`).

- [ ] **Step 4: Implement** — in `run_pipeline`, add `import checklist` (top) and, right before writing the manifest, inject checks:
```python
        manifest = oc.build_manifest(folder_id, p.name or "", product, result["folder"]["docs"], fields)
        manifest["checks"] = checklist.build_checklist(
            fields,
            {"matchedBy": how,
             "ocrIdentity": {"cccd": identity.get("cccd", ""), "name": identity.get("name", "")},
             "rosterIdentity": ({"cccd": row.get("cccd", ""), "name": row.get("name", "")} if row is not None else None)},
            result["folder"]["docs"],
        )
        with open(os.path.join(out_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
```
(`fields`, `how`, `identity`, `row`, `result["folder"]["docs"]` are all already in scope here.)

- [ ] **Step 5: Run `python3 -m pytest pipeline_test.py -q` → PASS.**
- [ ] **Step 6: Commit** `git add server/pipeline.py server/pipeline_test.py && git commit -m "feat(pipeline): write the coded checklist into each packet manifest"`

### Task 3: `cases.py` — review keyed by `items` + migration

**Files:** Modify `server/cases.py`; Test `server/cases_test.py`.

- [ ] **Step 1: Write failing tests** — update `cases_test.py`'s `_pkt` helper to use `review.items` and add:
```python
def test_progress_and_needs_resubmit_use_items():
    from cases import needs_resubmit, progress_of
    flagged = {"index":0,"confidence":"green","matchedBy":"cccd",
               "review":{"done":True,"items":{"A2":{"seen":True,"flag":{"reason":"sai","note":""}}}}}
    clean = {"index":1,"confidence":"green","matchedBy":"cccd","review":{"done":True,"items":{}}}
    assert needs_resubmit(flagged) is True and needs_resubmit(clean) is False
    assert progress_of([flagged, clean]) == {"done":2,"total":2,"flagged":1}

def test_load_migrates_fields_to_items(tmp_path):
    import json
    from cases import CaseStore
    cid="old"; d=tmp_path/cid; d.mkdir()
    old={"id":cid,"name":"x","createdAt":None,"status":"in_review","pdfName":"x.pdf",
         "rosterName":None,"summary":None,"error":None,
         "packets":[{"index":0,"confidence":"green","matchedBy":"cccd",
                     "review":{"done":False,"fields":{"name":{"seen":True,"flag":None}}}}]}
    (d/"case.json").write_text(json.dumps(old),encoding="utf-8")
    p=CaseStore(str(tmp_path)).get(cid)["packets"][0]
    assert p["review"] == {"done":False,"items":{}} and "fields" not in p["review"]
```
Also change existing `set_review` test to pass `{"done":True,"items":{...}}`.

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** — in `server/cases.py` replace every `review.get("fields")` / `"fields"` with `"items"`:
  - `needs_resubmit`: `review.get("items", {}).values()` (and default `{"items": {}}`).
  - `_ensure_packet_defaults`: `out.setdefault("review", {"done": False, "items": {}})`.
  - `set_review`: `p["review"] = {"done": bool(review.get("done", False)), "items": review.get("items", {}) or {}}`.
  - `_load` migration (the non-processing `else` branch): if a packet's `review` has `fields` (or lacks `items`), set `p["review"] = {"done": p["review"].get("done", False), "items": {}}` (reset — field-keys don't map to check-codes), pop any `fields`, and `_write` the case. Keep the existing legacy-`decision` migration too (a packet with neither `review` nor the new shape → `{"done":False,"items":{}}`).
  `case_status` already uses only `review.done` — unchanged.

- [ ] **Step 4: Run `python3 -m pytest cases_test.py -q` → PASS.**
- [ ] **Step 5: Commit** `git add server/cases.py server/cases_test.py && git commit -m "feat(cases): review state keyed by check code (review.items) + migration"`

### Task 4: `report.py` — build over `checks` + `review.items`

**Files:** Modify `server/report.py`; Test `server/report_test.py`.

- [ ] **Step 1: Update tests** — `report_test.py`: change the sample packets' `review.fields` → `review.items` keyed by **code**, and give each MANIFEST a `checks` list instead of relying on `fields`. Example flagged item:
```python
CASE = {"name":"FA.pdf","packets":[
  {"index":0,"name":"Lê Thị Mai Anh","matchedBy":"cccd",
   "ocrIdentity":{"cccd":"079","name":"Lê Thị Mai Anh"},"rosterIdentity":{"cccd":"079","name":"Lê Thị Mai Anh"},
   "review":{"done":True,"items":{"A2":{"seen":True,"flag":{"reason":"sai","note":"lệch số"}}}}},
]}
MANIFESTS = {0: {"checks":[
  {"code":"A2","label":"Mã số thuế khớp bảng kê","tier":"detail","kind":"value",
   "evidenceDocId":"contract","reference":"095204007694",
   "source":{"docId":"contract","page":0,"value":"8391246072"},"autostatus":"mismatch"}],
  "docs":[{"id":"contract","label":"Hợp đồng dịch vụ"}]}}
def test_report_item_resolves_from_checks():
    from report import build_report
    r = build_report(CASE, MANIFESTS, generated_at="2026-07-23T00:00:00Z")
    it = r["groups"][0]["items"][0]
    assert it["fieldLabel"]=="Mã số thuế khớp bảng kê" and it["document"]=="Hợp đồng dịch vụ"
    assert it["rosterValue"]=="095204007694" and it["docValue"]=="8391246072"
```
Keep the weak-match / markdown / csv tests (adjust to `items`).

- [ ] **Step 2: Run → FAIL.**

- [ ] **Step 3: Implement** — rewrite `_items_for` and `_needs_resubmit` to use `items` + `checks`:
```python
def _needs_resubmit(p: dict) -> bool:
    review = p.get("review") or {"items": {}}
    if any(i.get("flag") for i in review.get("items", {}).values()):
        return True
    return p.get("matchedBy") in ("name", "unmatched")

def _items_for(packet: dict, manifest: dict | None) -> list[dict]:
    checks = {c["code"]: c for c in (manifest or {}).get("checks", [])}
    docs = {d["id"]: d.get("label", d["id"]) for d in (manifest or {}).get("docs", [])}
    out = []
    for code, ir in (packet.get("review") or {}).get("items", {}).items():
        flag = ir.get("flag")
        if not flag:
            continue
        c = checks.get(code, {})
        src = c.get("source") or {}
        out.append({
            "code": code,
            "fieldLabel": c.get("label", code),
            "document": docs.get(c.get("evidenceDocId"), "—"),
            "page": (src["page"] + 1) if "page" in src else None,
            "rosterValue": c.get("reference") or "",
            "docValue": src.get("value") or "cần xem",
            "reason": flag.get("reason", ""),
            "note": flag.get("note", ""),
        })
    return out
```
`build_report`, markdown, and csv bodies stay the same (they consume `items[]` with the same field names).

- [ ] **Step 4: Run `python3 -m pytest report_test.py -q` → PASS.**
- [ ] **Step 5: Commit** `git add server/report.py server/report_test.py && git commit -m "feat(report): build over checklist items (review.items + manifest.checks)"`

### Task 5: `app.py` — review body `{done, items}`

**Files:** Modify `server/app.py`; Test `server/app_test.py`.

- [ ] **Step 1: Update tests** — in `app_test.py` change the `PUT …/review` bodies from `{"done":...,"fields":{...}}` to `{"done":...,"items":{"A2":{"seen":True,"flag":{...}}}}`, and assert on `packet["review"]["items"]`.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — `ReviewBody`: `class ReviewBody(BaseModel): done: bool = False; items: dict = {}`. `put_review`: `store.set_review(cid, i, {"done": body.done, "items": body.items})`. (Report endpoints unchanged.)
- [ ] **Step 4: Run whole backend `cd server && python3 -m pytest -q` → all green.**
- [ ] **Step 5: Commit** `git add server/app.py server/app_test.py && git commit -m "feat(api): review body keyed by items"`

---

# Phase 2 — Frontend data layer

### Task 6: `ctv/types.ts` — CheckItem + CtvFolder.checks

**Files:** Modify `src/ctv/types.ts`.

- [ ] **Step 1: Add types** (after `CtvSource`):
```ts
export type CheckTier = 'gate' | 'detail'
export type CheckKind = 'value' | 'identity' | 'confirm'
export type CheckAutoStatus = 'match' | 'mismatch' | 'review'

export interface CheckItem {
  code: string
  label: string
  tier: CheckTier
  kind: CheckKind
  evidenceDocId: string | null
  reference: string | null
  source: CtvSource | null
  autostatus: CheckAutoStatus | null
}
```
Add to `CtvFolder`: `checks?: CheckItem[]` (optional so existing synthetic folders still typecheck until Task 14 supplies them).

- [ ] **Step 2: Verify** `node node_modules/typescript/bin/tsc --noEmit` — new types compile (consumer errors from later tasks are expected once we touch them; at this point tsc should still be clean since additions are optional).
- [ ] **Step 3: Commit** `git add src/ctv/types.ts && git commit -m "feat(types): CheckItem + CtvFolder.checks"`

### Task 7: `api.ts` — PacketReview.items + CheckItem re-export

**Files:** Modify `src/upload/api.ts`, `src/upload/api.test.ts`.

- [ ] **Step 1: Test** — add to `api.test.ts` a test that `packetNeedsResubmit` reads `review.items`:
```ts
test('packetNeedsResubmit reads items', () => {
  const base = { matchedBy:'cccd', review:{done:true, items:{}} } as any
  expect(packetNeedsResubmit(base)).toBe(false)
  expect(packetNeedsResubmit({...base, review:{done:true, items:{A2:{seen:true, flag:{reason:'x',note:''}}}}})).toBe(true)
})
```
- [ ] **Step 2: Run `npx vitest run src/upload/api.test.ts` → FAIL.**
- [ ] **Step 3: Implement** — in `api.ts`: `PacketReview` → `{ done: boolean; items: Record<string, FieldReview> }`. Update `packetNeedsResubmit`: `Object.values(p.review?.items ?? {})`. `setReview` body already sends the `PacketReview` object (now with `items`) — no signature change. (Report types unchanged.) Re-export the check types: `export type { CheckItem, CheckTier, CheckKind } from '../ctv/types'`.
- [ ] **Step 4: Run vitest (that file) → PASS.** `tsc` will now flag `review.fields` consumers (FolderReview, FolderFieldsPanel, UploadFlow, DemoFlow, logic/review) — expected; fixed in later tasks.
- [ ] **Step 5: Commit** `git add src/upload/api.ts src/upload/api.test.ts && git commit -m "feat(api-client): PacketReview keyed by items; re-export CheckItem"`

### Task 8: `logic/review.ts` — over items/codes

**Files:** Modify `src/logic/review.ts`, `src/logic/review.test.ts`.

- [ ] **Step 1: Update tests** — change `review.fields` → `review.items`, and `allSeen(review, ['a'])` semantics stay (keys are now codes). Add nothing new structurally.
- [ ] **Step 2: Run → FAIL.**
- [ ] **Step 3: Implement** — replace `.fields` with `.items` in `allSeen`, `needsResubmit`, `packetStatus`. `allSeen(review, codes)`. `calloutAnchor` + `PACKET_STATUS_LABEL` unchanged.
- [ ] **Step 4: Run `npx vitest run src/logic/review.test.ts` → PASS.**
- [ ] **Step 5: Commit** `git add src/logic/review.ts src/logic/review.test.ts && git commit -m "feat(review-logic): key seen/status over review.items (codes)"`

---

# Phase 3 — Frontend UI (the two-tier reviewer)

### Task 9: `ChecklistPanel` component (new) + styles

**Files:** Create `src/components/ChecklistPanel.tsx`; Modify `src/styles.css`. (No unit test — verified in-browser.)

Renders the checklist grouped by tier. Props:
```ts
interface Props {
  checks: CheckItem[]
  review: PacketReview
  selectedCode: string
  onSelect: (code: string) => void
  onToggleFlag: (code: string, flag: FieldFlag | null) => void
}
```
- [ ] **Step 1: Build the component.** Split `checks` into `gates = checks.filter(c=>c.tier==='gate')` and `detail = checks.filter(c=>c.tier==='detail')`. Compute `seen`/`total` from `review.items`. Derive a per-row status: flagged → 'flag'; else if kind==='confirm' → (seen ? 'ok' : 'review'); else autostatus ('match'→ok / 'mismatch'→bad / 'review'). Render:
  - header row: "Danh sách kiểm tra" + `{seen}/{total} đã xem` + a progress bar.
  - **Preconditions card** (`.precond`): title "ĐIỀU KIỆN TIÊN QUYẾT" + an "Đủ điều kiện" badge when all gates are `ok`/passed; each gate row = status icon + label + a right-side status word (Đạt / Cần xem / Đã đánh dấu).
  - **Detail list** (`.detail`): title "KIỂM TRA CHI TIẾT"; each row = status icon + label; for `value` kind a sub-line "Bảng kê: {reference}" + a match hint (Khớp / Lệch / Cần xem); a flag button (⚑ "Đánh dấu" / "Đã đánh dấu"). Selected row highlighted. Clicking a row → `onSelect(code)`; flag button → `onToggleFlag` (stopPropagation); flagged+selected → inline reason chips (`sai`/`thiếu`/`mờ, không đọc được`) + note input (reuse the v1 flag-editor markup/logic keyed by code).
- [ ] **Step 2: Styles** — add `.checklist`, `.precond` (tinted card, left accent), `.precond-badge`, `.check-row` (+ `.on` selected, status color left-dot), `.check-sub`, `.match-hint` (ok/bad/review), `.flag-btn`, the flag editor classes (reuse v1's `.flag-reasons`/`.flag-note`), progress bar. Use a **calm accent** (blue/teal token), not pink; define an `--accent` token so brand can swap.
- [ ] **Step 3: Verify** `tsc --noEmit` — component compiles (FolderReview supplies props in Task 10).
- [ ] **Step 4: Commit** `git add src/components/ChecklistPanel.tsx src/styles.css && git commit -m "feat(ui): ChecklistPanel — two-tier checklist (preconditions + detail)"`

### Task 10: `FolderReview` — rewire to the checklist

**Files:** Modify `src/components/FolderReview.tsx`.

- [ ] **Step 1: Read** the current `FolderReview.tsx` (v1: keyed by `selectedKey`/`ranked`/`review.fields`).
- [ ] **Step 2: Rewire.**
  - Source of checks: `const checks = folder.checks ?? []`.
  - State: `selectedCode` (default `checks[0]?.code`), plus the existing `activeDocId/activePage/focusBbox/lockView`.
  - `focusCheck(code)`: set `selectedCode`; find the check; set `activeDocId = check.evidenceDocId ?? folder.docs[0].id`; for `kind==='value'` with a `source` → `activePage = source.page`, `focusBbox = source.bbox`; else clear `focusBbox` (confirm/gate → just show the doc). Call `markSeen(code)`.
  - `markSeen(code)` / `toggleFlag(code, flag)`: same as v1 but keyed by code into `review.items`; call `onReview`.
  - `F` hotkey toggles flag on `selectedCode`. Arrow ↑/↓ moves between checks (gates then detail, in `checks` order); ←/→ can step a value check's sources if >1 (most have 1 — keep the guard).
  - Header: keep the CTV title; render `<MatchKeyStrip .../>` as the header **badge** (Task 11).
  - Panes: `<ChecklistPanel checks={checks} review={review} selectedCode={selectedCode} onSelect={focusCheck} onToggleFlag={toggleFlag} />` + `<EvidenceViewer ... rosterLabel/rosterValue from selected check (Task 12) />`.
  - Done gate: `fieldKeys` → `codes = checks.map(c=>c.code)`; `seenCount`; `<ActionBar done seenCount total onFinish/>` with `allSeen(review, codes)`.
  - Remove `rankFolder`/`FolderFieldsPanel` usage.
- [ ] **Step 3: Verify** `tsc --noEmit` — FolderReview compiles; UploadFlow/DemoFlow still error (fixed in Task 13/14).
- [ ] **Step 4: Commit** `git add src/components/FolderReview.tsx && git commit -m "feat(ui): FolderReview drives the checklist (selectedCode, per-check evidence focus)"`

### Task 11: `MatchKeyStrip` → header badge

**Files:** Modify `src/components/MatchKeyStrip.tsx`, `src/styles.css`.

- [ ] **Step 1:** Adjust to the mockup: a compact pill — shield glyph + "Danh tính khớp" (ok, matchedBy cccd), "Khớp theo tên" (warn), "Chưa khớp bảng kê" (bad), "Không có bảng kê" (muted). Keep the OCR-vs-roster table available (e.g. shown on hover / expand or below the pill); the header uses just the pill. Props unchanged (`matchedBy, ocr, roster`).
- [ ] **Step 2: Verify tsc; Commit** `git commit -m "feat(ui): match key as a compact header badge"`

### Task 12: `EvidenceViewer` — reference from the selected check

**Files:** Modify `src/components/FolderReview.tsx` (props it passes) — `EvidenceViewer` itself likely needs no change (already takes optional `rosterLabel`/`rosterValue`).

- [ ] **Step 1:** In FolderReview compute `const sel = checks.find(c => c.code === selectedCode)`, pass `rosterLabel={sel?.label}` and `rosterValue={sel?.kind === 'value' ? sel.reference : null}` (so the roster callout shows only for value checks; confirm/gate checks show the doc with no callout). Confirm `EvidenceViewer` renders the callout only when `rosterValue` is truthy (it already guards `showRoster && rosterValue`).
- [ ] **Step 2: Verify tsc; Commit** `git commit -m "feat(ui): roster callout driven by the selected value check"`

### Task 13: `CaseDetail` + `UploadFlow` — items

**Files:** Modify `src/components/CaseDetail.tsx`, `src/components/UploadFlow.tsx`.

- [ ] **Step 1:** `CaseDetail` — the flagged-field count reads `p.review?.items` (was `.fields`); `packetStatus` unchanged (uses review). `UploadFlow` — seed `review` from `meta?.review ?? {done:false, items:{}}`; the FolderReview props already updated in Task 10; `flushReview` unchanged (passes the `PacketReview`). Grep for any remaining `.fields` on review and switch to `.items`.
- [ ] **Step 2: Verify** `tsc --noEmit` — only `DemoFlow` should remain (Task 14).
- [ ] **Step 3: Commit** `git add src/components/CaseDetail.tsx src/components/UploadFlow.tsx && git commit -m "feat(ui): case detail + flow read review.items"`

### Task 14: `DemoFlow` + synthetic checks (offline export)

**Files:** Create `src/ctv/demoChecklist.ts`; Modify `src/components/DemoFlow.tsx`.

The offline export's synthetic folders (`ctv/folders.ts`) have their own field keys — build a representative checklist for them so the v2.0 export shows the two-tier UI.

- [ ] **Step 1: Create `src/ctv/demoChecklist.ts`** — `demoChecklist(folder: CtvFolder): CheckItem[]` producing the gate items (G-DOC packet-level; G-ID from the folder's cccd field vs itself → match; D3/B3/C2 confirm pointing at the folder's docs by kind) + value items mapped from the synthetic fields present (`name→B1`, `cccd→A1`, `bank_acct→BANK`, `gross→B2`, …) with `reference`=field.expected, `source`=field.sources[0], `autostatus` by a simple compare; + C1/D1 confirm. Mirror the backend `build_checklist` order/labels. (One folder has a deliberate mismatch so the demo shows a `Lệch`/flag path.)
- [ ] **Step 2: Wire `DemoFlow`** — build `checks` via `demoChecklist(folder)` and attach to the folder passed to `FolderReview` (`{...folder, checks}`); `reviews` state keyed by folder id holds `PacketReview` with `items`. Everything else (match badge props, nav) as today.
- [ ] **Step 3: Verify** `tsc --noEmit` → **fully clean**. `npx vitest run` → green.
- [ ] **Step 4: Commit** `git add src/ctv/demoChecklist.ts src/components/DemoFlow.tsx && git commit -m "feat(ui): offline demo renders the checklist (synthetic checks)"`

### Task 15: Retire `FolderFieldsPanel`; update hotkey legend

**Files:** Delete `src/components/FolderFieldsPanel.tsx`; Modify `src/components/HotkeyHelp.tsx`.

- [ ] **Step 1:** Confirm no importers of `FolderFieldsPanel` remain (`grep -rn FolderFieldsPanel src`); delete it. Update `HotkeyHelp` if any label references "trường"/fields → "mục kiểm tra". Update the ActionBar hint string in FolderReview to "↑↓ mục · ←→ tài liệu · F đánh dấu · B khung · V bảng kê".
- [ ] **Step 2: Verify** `tsc --noEmit` clean; `npx vitest run` green.
- [ ] **Step 3: Commit** `git add -A && git commit -m "chore(ui): retire FolderFieldsPanel; checklist-oriented hotkey labels"`

---

# Phase 4 — Verify + v2.0 export

### Task 16: Full verification + build `Reviewer-v2.0.html`

**Files:** none (verification + build).

- [ ] **Step 1: Green suite** — `node node_modules/typescript/bin/tsc --noEmit` (0), `npx vitest run` (all), `cd server && python3 -m pytest -q` (all).
- [ ] **Step 2: Live browser (orchestrator does this, not a subagent)** — restart backend on new code; re-OCR a case (so packets carry `checks`); open a packet and confirm: Preconditions card pinned on top with the 5 gates; Detail list below; focusing a **value** check auto-focuses the located value on the **scanned** page with the roster callout; focusing a **confirm** check opens the right document tab (no callout); flag a check → "Đã đánh dấu"; Done unlocks only at all-seen; export report lists flagged checks by code+label. Screenshot as proof.
- [ ] **Step 3: Build the export** — `npm run build:single`; copy to `~/Downloads/Reviewer-v2.0.html`. (v1.0 export already exists.)
- [ ] **Step 4: Commit** any doc/verification notes; report both exports ready.

---

## Self-review notes (verify during execution)

- **Spec coverage:** checklist model (T1) · manifest carries checks (T2) · review keyed by code + migration (T3) · report over checks (T4) · API (T5) · TS types (T6,T7) · logic (T8) · two-tier UI (T9,T10) · match badge (T11) · scan-based value callout / confirm routing (T12) · flow (T13) · offline demo (T14) · cleanup (T15) · verify + v2.0 export (T16). Deferred (Mode B C3/E1, gate-fail flow, CV, region anchoring) intentionally absent.
- **Type/shape consistency:** `CheckItem` fields identical in `checklist.py` output, `manifest.checks`, and `ctv/types.ts`; `review.items` keyed by code across `cases.py`/`report.py`/`api.ts`/`review.ts`/UI; report item fields (`fieldLabel/document/page/rosterValue/docValue/reason/note`) unchanged so md/csv render untouched.
- **Scan pane is real:** `EvidenceViewer` unchanged; value checks focus the located bbox on the scan, confirm checks just open the tab. No transcription view.
- **Known simplification:** confirm checks (G-DOC/D3/B3/C2/C1/D1) route to the document, not a pinpoint region — noted in the spec; upgradeable later by giving those `CheckItem`s a `source`/bbox without model changes.
