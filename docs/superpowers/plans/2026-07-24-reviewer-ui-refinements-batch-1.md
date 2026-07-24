# Reviewer UI Refinements (Batch 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement items 1–10 of `docs/review-ui-refinements.md` (walked against the real case FA-PM260226080) on the v2 checklist reviewer — doc-viewer view modes, view-follows-check, gate/routing cleanups, a reference-template lightbox, signature-focus heuristics, and three bug fixes.

**Architecture:** The reviewer is a Vite+React+TS frontend (`src/`) driven by a FastAPI+PyMuPDF+Tesseract backend (`server/`). The backend `build_checklist` emits coded `CheckItem` rows into each packet manifest; the offline single-file export mirrors that shape in `src/ctv/demoChecklist.ts`. Testable logic lives in pure modules (`src/logic/*`, `server/*.py`) with unit tests; React components and CSS carry no unit tests (no testing-library in the toolchain) and are verified in the browser preview. This plan keeps that split: every new behavior gets a pure, tested helper; component/CSS wiring consumes it and is preview-verified.

**Tech Stack:** React 18 + TypeScript 5 + Vite 5, Vitest 2 (frontend logic tests), Python 3.14 + pytest 9 (backend), PyMuPDF/pytesseract (OCR, not unit-tested).

---

## Decisions & assumptions (baked into this plan)

These were chosen with sensible defaults; flag at the plan-review checkpoint if any should change.

1. **Item 6 reference asset is a PII-free placeholder.** The real blank *Mẫu 08/CK-TNCN* ("Acc will provide") is not in the repo and must stay PII-free. We ship a bundled placeholder SVG (`public/reference/mau-08-ck-tncn-2026.svg`) wired end-to-end, with a `TODO(acc)` note to swap in the real blank form. The feature, lightbox, and offline inlining all work with the placeholder.
2. **Offline demo gains one commitment doc.** The three synthetic folders (`src/ctv/folders.ts`) currently have no `commitment` doc, so after item 5 they'd never show D3/D1 and item 6's button would be invisible offline. We add a minimal PII-free `commitment` doc (`bancamket.svg`) to **one** folder (`le-thi-mai-anh`) so the export demonstrates D3/D1 + the reference button, and leave the other two without one so the *conditional omission* (item 5) is also demonstrable.
3. **`CheckItem` gains two optional fields:** `focus?: CheckFocus | null` (item 7 signature landing) and `referenceAsset?: string` (item 6). Both optional → backward compatible with pre-v2 manifests.
4. **View mode is controlled-with-local-override.** `FolderReview` owns `viewMode` + a per-check default; `EvidenceViewer`'s toolbar overrides it; selecting another check re-applies that check's default (the override "holds while the reviewer stays on the check" because `focusCheck` re-seeds the default on every check change).
5. **Item 9 is validated synthetically.** The real fix depends on OCR output of a real (PII) contract we cannot open. We implement the spec's mechanism (name uses tolerant label-anchored location like other value fields; B1 prefers its routed contract source) and cover it with synthetic word-list tests in the module's established style. Real-case validation is the user's separate manual step.

## Toolchain / commands (verified against a green baseline)

- Frontend types: `npx tsc --noEmit` (expect exit 0)
- Frontend logic tests (one file): `npx vitest run src/logic/<file>.test.ts`
- Frontend all tests: `npx vitest run`
- Backend tests (from repo worktree root): `cd server && python3 -m pytest <file> -v` — server modules import by bare name, so pytest **must** run with `server/` as the working directory. Full: `cd server && python3 -m pytest`.
- Offline export: `npm run build:single` then copy `dist-single/*.html` to `~/Downloads/Reviewer-v2.0.html`.

Baseline before any change: tsc exit 0 · vitest 35 passed · pytest 101 passed.

## File structure (what each task creates / modifies)

**New pure-logic modules (tested):**
- `src/logic/pageNav.ts` (+`.test.ts`) — page/document stepping across a doc list (items 8, 10, 1-cont).
- `src/logic/viewMode.ts` (+`.test.ts`) — `ViewMode`, `viewModeForCheck`, continuous-zoom clamp (items 1, 2, 3).

**New components / assets:**
- `src/components/ReferenceLightbox.tsx` — modal over the scan pane (item 6).
- `public/reference/mau-08-ck-tncn-2026.svg` — placeholder reference asset (item 6).
- `public/folders/le-thi-mai-anh/bancamket.svg` — synthetic commitment doc (demo, decision #2).

**Modified:**
- `src/ctv/types.ts` — `CheckItem.focus`, `CheckItem.referenceAsset`, `CheckFocus` (items 6, 7).
- `server/checklist.py` (+`checklist_test.py`) — remove G-ID (4); conditional doc-routed checks (5); B1 routed-source preference (9); B3/C2 signature focus + thanh-lý routing (7).
- `server/ocr_extract.py` (+`ocr_extract_test.py`) — name located-slot fallback on the contract (9).
- `server/pipeline_test.py` — G-ID assertion fixups (4).
- `src/ctv/demoChecklist.ts` — mirror 4/5/6/7 for the offline export.
- `src/ctv/folders.ts` — add commitment doc to one folder (decision #2).
- `src/components/FolderReview.tsx` — reset/clamp page (8); ←→ page nav (10); view-mode state + follows-check (1,2,3); reference lightbox host (6).
- `src/components/EvidenceViewer.tsx` — clamp pager (8); view-mode toolbar + continuous/2-page rendering (1); soft signature focus caption (7/2).
- `src/components/ChecklistPanel.tsx` — reference button on the routed check (6).
- `src/components/HotkeyHelp.tsx` — legend "←→ trang" + view-mode note (10, 1).
- `src/styles.css` — continuous/2-page layout, view-mode control, reference lightbox, soft caption.

## Task sequencing & dependencies

- **Phase 1 — warm-up frontend bugs (no backend, no view-mode dep):** Task 1 (item 8), Task 2 (item 10).
- **Phase 2 — backend checklist/OCR + offline mirror:** Task 3 (item 4), Task 4 (item 5), Task 5 (item 9), Task 6 (item 7 backend).
- **Phase 3 — reference asset feature:** Task 7 (item 6).
- **Phase 4 — doc-viewer view modes (big refactor):** Task 8 (item 1).
- **Phase 5 — view-follows-check:** Task 9 (item 2), Task 10 (item 3).
- **Phase 6 — full verification + offline export:** Task 11.

Item 10's continuous-mode branch (←→ jumps documents) is introduced in Task 8/9 where continuous mode exists; Task 2 delivers the single/2-page page-nav that is correct on its own.

---

## Task 1: Item 8 — reset & clamp the page counter on doc switch

**Why:** `focusCheck` only sets `activePage` for value checks; the tab handler (`onSelectDoc`) never resets it, so switching to a shorter doc leaves a stale index (shows "4 / 2", falls back to page 0). Reset `activePage` on every active-doc change and clamp to `[0, pageCount-1]`.

**Files:**
- Create: `src/logic/pageNav.ts`, `src/logic/pageNav.test.ts`
- Modify: `src/components/FolderReview.tsx` (`onSelectDoc`, `focusCheck`), `src/components/EvidenceViewer.tsx` (pager clamp)

- [ ] **Step 1: Write the failing test** — `src/logic/pageNav.test.ts`

```ts
import { describe, it, expect } from 'vitest'
import { clampPage } from './pageNav'

describe('clampPage', () => {
  it('clamps a stale high index down to the last page', () => {
    expect(clampPage(3, 2)).toBe(1)   // page 4 of a 2-page doc -> last (index 1)
  })
  it('clamps negatives up to 0', () => {
    expect(clampPage(-2, 5)).toBe(0)
  })
  it('passes an in-range index through', () => {
    expect(clampPage(2, 5)).toBe(2)
  })
  it('returns 0 for an empty/zero-page doc', () => {
    expect(clampPage(4, 0)).toBe(0)
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/logic/pageNav.test.ts`
Expected: FAIL — `clampPage` is not exported / module missing.

- [ ] **Step 3: Write minimal implementation** — `src/logic/pageNav.ts`

```ts
// Pure page/document navigation helpers for the scan pane. Kept out of the
// React components so the index math (clamping, rolling into adjacent docs)
// is unit-tested (the components themselves carry no tests).

/** Clamp a page index into a doc's real range; 0 when the doc has no pages. */
export function clampPage(page: number, pageCount: number): number {
  if (pageCount <= 0) return 0
  return Math.max(0, Math.min(page, pageCount - 1))
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/logic/pageNav.test.ts`
Expected: PASS (4 tests).

- [ ] **Step 5: Wire the reset into `FolderReview.onSelectDoc`**

In `src/components/FolderReview.tsx`, the current handler passed to `EvidenceViewer` is:

```tsx
onSelectDoc={id => { setActiveDocId(id); setFocusBbox(null) }}
```

Replace with a handler that resets the page to the switched-to doc's page 0 (there is nothing selected to land on when switching by tab), clamped defensively:

```tsx
onSelectDoc={id => {
  const d = folder.docs.find(x => x.id === id)
  setActiveDocId(id)
  setActivePage(clampPage(0, d?.pages.length ?? 0))
  setFocusBbox(null)
}}
```

Add the import at the top of `FolderReview.tsx`:

```tsx
import { clampPage } from '../logic/pageNav'
```

- [ ] **Step 6: Clamp the pager in `EvidenceViewer` (defensive)**

In `src/components/EvidenceViewer.tsx`, `page` is currently `doc.pages[activePage] ?? doc.pages[0]` and the pager label is `{activePage + 1} / {pageCount}`. A stale index must never *display*. Introduce a clamped index and use it for both the rendered page and the label:

```tsx
import { clampPage } from '../logic/pageNav'
// ...
const doc = docs.find(d => d.id === activeDocId) ?? docs[0]
const pageCount = doc.pages.length
const pageIdx = clampPage(activePage, pageCount)   // never out of range
const page = doc.pages[pageIdx] ?? doc.pages[0]
```

Then use `pageIdx` in the pager block (label + disabled logic + the `onSelectPage` deltas):

```tsx
{pageCount > 1 && (
  <div className="doc-pager">
    <button disabled={pageIdx === 0} onClick={() => onSelectPage(pageIdx - 1)} aria-label="Trang trước">‹</button>
    <span>{pageIdx + 1} / {pageCount}</span>
    <button disabled={pageIdx === pageCount - 1} onClick={() => onSelectPage(pageIdx + 1)} aria-label="Trang sau">›</button>
  </div>
)}
```

(Leave the existing `nat`/`inflated` derivations reading from `page`, which now comes from the clamped index.)

- [ ] **Step 7: Verify types + full logic tests**

Run: `npx tsc --noEmit` → exit 0
Run: `npx vitest run` → all pass (35 + 4 new)

- [ ] **Step 8: Preview-verify** (see verification workflow at end): open the reviewer, select a check on a multi-page doc, page to page ≥3, then click a tab whose doc has fewer pages → counter reads "1 / N", never "4 / 2".

- [ ] **Step 9: Commit**

```bash
git add src/logic/pageNav.ts src/logic/pageNav.test.ts src/components/FolderReview.tsx src/components/EvidenceViewer.tsx
git commit -m "fix(reviewer): reset & clamp page index on doc switch (batch1 #8)"
```

---

## Task 2: Item 10 — bind ←→ to page navigation, rolling into adjacent documents

**Why:** The current `ArrowLeft/ArrowRight` branch computes `n = c?.source ? 1 : 0` and returns on `n < 2` — always true, so it never navigates and never `preventDefault`s, yet the legend advertises "←→ tài liệu". Bind ←→ to **page** navigation; at a doc's first/last page, roll into the previous/next document. Update the legend to "←→ trang". (The `Cuộn liên tục` special-case — ←→ jumps documents — is added in Task 8/9 where that mode exists.)

**Files:**
- Modify: `src/logic/pageNav.ts` (+ `pageNav.test.ts`) — `stepPage`
- Modify: `src/components/FolderReview.tsx` (keydown handler + ActionBar hint)
- Modify: `src/components/HotkeyHelp.tsx` (legend row)

- [ ] **Step 1: Write the failing test** — append to `src/logic/pageNav.test.ts`

```ts
import { stepPage } from './pageNav'

const DOCS = [
  { id: 'a', pages: [{}, {}] },        // 2 pages
  { id: 'b', pages: [{}] },            // 1 page
  { id: 'c', pages: [{}, {}, {}] },    // 3 pages
] as unknown as import('../ctv/types').EvidenceDoc[]

describe('stepPage', () => {
  it('advances within a doc', () => {
    expect(stepPage(DOCS, 'a', 0, +1)).toEqual({ docId: 'a', page: 1 })
  })
  it('rolls forward into the next doc at the first page of it', () => {
    expect(stepPage(DOCS, 'a', 1, +1)).toEqual({ docId: 'b', page: 0 })
  })
  it('rolls backward into the previous doc at its last page', () => {
    expect(stepPage(DOCS, 'b', 0, -1)).toEqual({ docId: 'a', page: 1 })
  })
  it('stays put at the very first page going back', () => {
    expect(stepPage(DOCS, 'a', 0, -1)).toEqual({ docId: 'a', page: 0 })
  })
  it('stays put at the very last page going forward', () => {
    expect(stepPage(DOCS, 'c', 2, +1)).toEqual({ docId: 'c', page: 2 })
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/logic/pageNav.test.ts`
Expected: FAIL — `stepPage` not exported.

- [ ] **Step 3: Implement `stepPage`** — add to `src/logic/pageNav.ts`

```ts
import type { EvidenceDoc } from '../ctv/types'

/**
 * Step one page in `dir` (+1 / -1) within `docs`, rolling into the adjacent
 * document at the first/last page. Clamped at the very ends (first page of the
 * first doc / last page of the last doc). Returns the resulting {docId, page}.
 */
export function stepPage(
  docs: EvidenceDoc[], activeDocId: string, activePage: number, dir: 1 | -1,
): { docId: string; page: number } {
  const di = Math.max(0, docs.findIndex(d => d.id === activeDocId))
  const doc = docs[di]
  const last = doc.pages.length - 1
  const p = clampPage(activePage, doc.pages.length)
  if (dir === 1) {
    if (p < last) return { docId: doc.id, page: p + 1 }
    if (di < docs.length - 1) return { docId: docs[di + 1].id, page: 0 }
    return { docId: doc.id, page: last }               // at the very end
  } else {
    if (p > 0) return { docId: doc.id, page: p - 1 }
    if (di > 0) {
      const prev = docs[di - 1]
      return { docId: prev.id, page: Math.max(0, prev.pages.length - 1) }
    }
    return { docId: doc.id, page: 0 }                   // at the very start
  }
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npx vitest run src/logic/pageNav.test.ts`
Expected: PASS (all pageNav tests).

- [ ] **Step 5: Rewire the ←→ branch in `FolderReview`**

In `src/components/FolderReview.tsx`, replace the dead branch:

```tsx
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        const c = checks.find(x => x.code === selectedCode)
        const n = c?.source ? 1 : 0
        if (n < 2) return // single-source checks (v1) — nothing to page through yet
      }
```

with page navigation:

```tsx
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault()
        const dir = e.key === 'ArrowRight' ? 1 : -1
        const { docId, page } = stepPage(folder.docs, activeDocId, activePage, dir)
        setActiveDocId(docId)
        setActivePage(page)
        setFocusBbox(null)   // paging away from a located value clears its box
      }
```

Add `stepPage` to the existing pageNav import:

```tsx
import { clampPage, stepPage } from '../logic/pageNav'
```

Add `activeDocId, activePage` to the keydown effect's dependency array (it currently lists `[checks, selectedCode, review]`):

```tsx
  }, [checks, selectedCode, review, folder, activeDocId, activePage])
```

- [ ] **Step 6: Update the ActionBar hint** in `FolderReview.tsx`

Change the hint string's `←→ tài liệu` segment to `←→ trang`:

```tsx
        hint="↑↓ mục · ←→ trang · F đánh dấu · B khung · V bảng kê · ⌥P di chuyển · ? phím tắt"
```

- [ ] **Step 7: Update the hotkey legend** in `src/components/HotkeyHelp.tsx`

Replace the `← / →` row:

```tsx
  { keys: '← / →', desc: 'Chuyển trang (sang tài liệu kế khi hết trang)' },
```

- [ ] **Step 8: Verify + preview**

Run: `npx tsc --noEmit` → 0; `npx vitest run` → all pass.
Preview: select a check, press → repeatedly → pages advance and roll into the next doc's page 1; ← rolls back into the previous doc's last page. The tab highlight follows the active doc.

- [ ] **Step 9: Commit**

```bash
git add src/logic/pageNav.ts src/logic/pageNav.test.ts src/components/FolderReview.tsx src/components/HotkeyHelp.tsx
git commit -m "fix(reviewer): ←→ navigates pages, rolls into adjacent docs; legend '←→ trang' (batch1 #10)"
```

---

## Task 3: Item 4 — remove the G-ID gate

**Why:** Identity is verified in detail by B1 (name) + A1 (CCCD); the always-on header match badge + CCCD-mismatch strip (`MatchKeyStrip`) already carries the automatic weak-match warning. Drop G-ID so gates become 4: G-DOC, D3, B3, C2. `MatchKeyStrip` is unaffected (it reads `matchedBy`/identities, not the checklist).

**Files:**
- Modify: `server/checklist.py` (drop the G-ID append), `server/checklist_test.py`, `server/pipeline_test.py`
- Modify: `src/ctv/demoChecklist.ts` (drop the G-ID row)

- [ ] **Step 1: Update the backend tests first (they encode the old 5-gate order)**

In `server/checklist_test.py`:
- `test_emits_gates_first_then_detail_in_order` — change to 4 gates without G-ID:

```python
def test_emits_gates_first_then_detail_in_order():
    checks = build_checklist(FIELDS, MATCH, DOCS)
    codes = [c["code"] for c in checks]
    assert codes[:4] == ["G-DOC", "D3", "B3", "C2"]
    assert "G-ID" not in codes
    assert set(codes[4:]) <= {"B1", "A1", "A2", "B2", "BANK", "INFO", "C1", "D1"}
    assert all(c["tier"] == "gate" for c in checks[:4])
```

- `test_identity_and_confirm_kinds` — drop the G-ID assertion, keep the confirm ones:

```python
def test_confirm_kinds_and_routing():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert "G-ID" not in c
    assert c["B3"]["kind"] == "confirm" and c["B3"]["evidenceDocId"] == "contract"
    assert c["C2"]["evidenceDocId"] == "bbnt" and c["D3"]["evidenceDocId"] == "camket"
    assert c["G-DOC"]["evidenceDocId"] is None
```

- Delete `test_weak_match_identity_is_review` entirely (it tested G-ID). The weak-match path is now MatchKeyStrip's concern, covered by its own frontend behavior.

In `server/pipeline_test.py`, `test_manifest_carries_checks` currently asserts `codes[:2] == ["G-DOC", "G-ID"]`. Change to:

```python
    assert codes[0] == "G-DOC"
    assert "G-ID" not in codes
    assert "B1" in codes
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && python3 -m pytest checklist_test.py pipeline_test.py -q`
Expected: FAIL — `build_checklist` still emits G-ID.

- [ ] **Step 3: Remove G-ID from `build_checklist`** in `server/checklist.py`

Delete the entire G-ID append block (the `checks.append({"code": "G-ID", ...})` plus its `matched_by = match.get(...)` line). Result — the gate section becomes:

```python
    checks.append({"code": "G-DOC", "label": "Đủ chứng từ bắt buộc", "tier": "gate",
                   "kind": "confirm", "evidenceDocId": None,
                   "reference": None, "source": None, "autostatus": None})
    for code, label, kind_doc in _CONFIRM_GATES:
        checks.append({"code": code, "label": label, "tier": "gate", "kind": "confirm",
                       "evidenceDocId": contract if kind_doc == "contract" else _doc_by_kind(docs, kind_doc),
                       "reference": None, "source": None, "autostatus": None})
```

(`match` is still a parameter — it's used only for the removed block now, but keep the signature `build_checklist(fields, match, docs)` unchanged so the pipeline call site and the MatchKeyStrip data flow are untouched. Leave `_autostatus` in place; it's still used by value checks.)

- [ ] **Step 4: Run backend tests to verify they pass**

Run: `cd server && python3 -m pytest checklist_test.py pipeline_test.py -q`
Expected: PASS.

- [ ] **Step 5: Drop G-ID from the offline mirror** in `src/ctv/demoChecklist.ts`

Remove the entire `{ code: 'G-ID', ... }` object (and its two-line comment above it) from the `checks` array. Remove the now-unused `cccd` local (`const cccd: CtvField | undefined = byKey.get('cccd')`) **only if** nothing else references it — the value loop uses `byKey.get('cccd')` independently, so this local is unused after the G-ID removal; delete it and its `CtvField` import if that import becomes unused.

- [ ] **Step 6: Verify frontend**

Run: `npx tsc --noEmit` → 0 (fix any unused-import errors surfaced). `npx vitest run` → all pass.

- [ ] **Step 7: Commit**

```bash
git add server/checklist.py server/checklist_test.py server/pipeline_test.py src/ctv/demoChecklist.ts
git commit -m "feat(checklist): drop G-ID gate — identity covered by B1/A1 + match badge (batch1 #4)"
```

---

## Task 4: Item 5 — document-routed checks omitted when their evidence doc is absent

**Why:** D3/D1 route to the `commitment` ("Bản cam kết") doc, present in only ~8/32 packets (genuinely absent elsewhere, not an OCR miss). A routed check that opens nothing is a dead row. **General rule:** any document-routed check whose evidence doc is missing must not be emitted (applies to Phụ lục-routed checks too). G-DOC (routes to nothing by design, `evidenceDocId: None`) is exempt — it's a glance gate, not doc-routed.

**Files:**
- Modify: `server/checklist.py` (+ `checklist_test.py`)
- Modify: `src/ctv/demoChecklist.ts`

- [ ] **Step 1: Write failing tests** — add to `server/checklist_test.py`

```python
DOCS_NO_COMMIT = [{"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ"},
                  {"id": "bbnt", "kind": "bbnt", "label": "Biên bản nghiệm thu"}]

def test_omits_commitment_routed_checks_when_no_commitment_doc():
    codes = [c["code"] for c in build_checklist(FIELDS, MATCH, DOCS_NO_COMMIT)]
    assert "D3" not in codes and "D1" not in codes
    assert codes[:3] == ["G-DOC", "B3", "C2"]      # D3 gate drops out of the gate run

def test_keeps_commitment_routed_checks_when_commitment_present():
    codes = [c["code"] for c in build_checklist(FIELDS, MATCH, DOCS)]  # DOCS has 'camket'
    assert "D3" in codes and "D1" in codes

def test_bbnt_routed_checks_omitted_when_no_bbnt():
    docs = [{"id": "contract", "kind": "contract", "label": "x"}]
    codes = [c["code"] for c in build_checklist(FIELDS, MATCH, docs)]
    assert "C2" not in codes   # C2 routes to bbnt; none present -> omitted
    assert "B3" in codes       # B3 routes to contract (present) -> kept
```

- [ ] **Step 2: Run to verify failure**

Run: `cd server && python3 -m pytest checklist_test.py -q`
Expected: FAIL — D3/D1/C2 still emitted.

- [ ] **Step 3: Skip routed checks whose doc is absent** in `server/checklist.py`

For the two confirm loops, compute the routed doc id and `continue` when it's `None`. Contract-routed checks keep the existing first-doc fallback (a packet always has *some* doc for the contract slot), so only genuinely-missing routed kinds drop:

```python
    for code, label, kind_doc in _CONFIRM_GATES:
        doc_id = contract if kind_doc == "contract" else _doc_by_kind(docs, kind_doc)
        if doc_id is None:
            continue   # #5: document-routed check with no evidence doc -> no dead row
        checks.append({"code": code, "label": label, "tier": "gate", "kind": "confirm",
                       "evidenceDocId": doc_id,
                       "reference": None, "source": None, "autostatus": None})
```

Apply the identical guard to the `_CONFIRM_DETAIL` loop (C1/D1):

```python
    for code, label, kind_doc in _CONFIRM_DETAIL:
        doc_id = _doc_by_kind(docs, kind_doc)
        if doc_id is None:
            continue   # #5
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "confirm",
                       "evidenceDocId": doc_id,
                       "reference": None, "source": None, "autostatus": None})
```

Note: this batch does **not** implement C1/D1 logic (explicitly out of scope), but D1's *row* is still emitted/omitted by the same routing rule as every other commitment-routed check — that's consistent and correct.

- [ ] **Step 4: Run backend tests → pass**

Run: `cd server && python3 -m pytest checklist_test.py -q` → PASS.

- [ ] **Step 5: Mirror in `demoChecklist.ts`** — omit commitment/bbnt-routed rows when the doc is absent.

Replace the hard-coded D3 gate and the C1/D1 detail pushes with conditional emission driven by the routed doc. Concretely, compute the routed ids up front and only push when present:

```ts
  const commitment = docByKind(folder, 'commitment')
  const bbnt = docByKind(folder, 'bbnt')

  const checks: CheckItem[] = [
    { code: 'G-DOC', label: 'Đủ chứng từ bắt buộc', tier: 'gate', kind: 'confirm',
      evidenceDocId: null, reference: null, source: null, autostatus: null },
  ]
  if (commitment) checks.push(
    { code: 'D3', label: 'Cam kết TNCN đúng mẫu năm hiện hành', tier: 'gate', kind: 'confirm',
      evidenceDocId: commitment, reference: null, source: null, autostatus: null })
  checks.push(
    { code: 'B3', label: 'Hợp đồng đủ chữ ký & con dấu', tier: 'gate', kind: 'confirm',
      evidenceDocId: contract, reference: null, source: null, autostatus: null })
  if (bbnt) checks.push(
    { code: 'C2', label: 'BBNT đủ chữ ký, con dấu & giáp lai', tier: 'gate', kind: 'confirm',
      evidenceDocId: bbnt, reference: null, source: null, autostatus: null })
```

And at the bottom, gate C1/D1 on their docs:

```ts
  if (bbnt) checks.push(
    { code: 'C1', label: 'Nội dung & thời gian khớp BBNT', tier: 'detail', kind: 'confirm',
      evidenceDocId: bbnt, reference: null, source: null, autostatus: null })
  if (commitment) checks.push(
    { code: 'D1', label: 'Thông tin & MST khớp cam kết', tier: 'detail', kind: 'confirm',
      evidenceDocId: commitment, reference: null, source: null, autostatus: null })
```

(Preserve the existing gate order: G-DOC, D3, B3, C2. Keep the value-check loop between the gate pushes and the C1/D1 pushes exactly as is.)

- [ ] **Step 6: Verify frontend**

Run: `npx tsc --noEmit` → 0; `npx vitest run` → all pass. (The three current synthetic folders have no commitment doc yet, so D3/D1 won't render offline until Task 7 adds one to `le-thi-mai-anh` — expected.)

- [ ] **Step 7: Commit**

```bash
git add server/checklist.py server/checklist_test.py src/ctv/demoChecklist.ts
git commit -m "feat(checklist): omit document-routed checks when their evidence doc is absent (batch1 #5)"
```

---

## Task 5: Item 9 — B1 (name) lands on the contract's label-anchored slot, not the BBNT

**Why:** B1 shows the *typed BBNT* name instead of the contract's boxed supplier-label slot. `find_name`'s existing geometric fallback already boxes a "cần xem" slot at the contract's all-caps "BÊN CUNG ỨNG DỊCH VỤ" label (the spec quotes it in caps → `_is_labeled_anchor` accepts it), so the contract usually *does* get a hoten source. The observable bug is **source selection**: `build_checklist` takes `sources[0]`, and in packets where the BBNT is segmented before the contract, `sources[0]` is the BBNT. **The fix (§5b below):** make document-routed *value* checks prefer the source on their routed doc — B1 then shows the contract slot, while the typed BBNT name stays reachable via its tab (roster callout drives the comparison; OCR locates, the human reads handwriting). **Precondition guard (§5a below):** a synthetic `ocr_extract` test pinning that the contract's all-caps supplier label yields a located slot even with unread handwriting — the assumption the fix depends on. It should already pass with the current code (find_name's geometric fallback fires), so **no `ocr_extract` code change is expected**; a tolerant `_located_name_hits` fallback is given to add **only if that guard fails**. Real-case (PII) validation is the user's separate manual step; if the real contract yields no hoten source, extend name location then.

**Files:**
- Modify: `server/checklist.py` (+ `checklist_test.py`) — the fix
- Modify: `src/ctv/demoChecklist.ts` — offline mirror
- Modify: `server/ocr_extract_test.py` (+ possibly `ocr_extract.py`) — precondition guard, code change only if the guard fails

### 5a — name located-slot precondition guard (ocr_extract)

- [ ] **Step 1: Write the guard test** — add to `server/ocr_extract_test.py`

```python
from ocr_extract import _hits_for_doc, FIELD_SPECS

def _word(text, x, y, w=40, h=20, conf=90):
    return {"text": text, "x": x, "y": y, "w": w, "h": h, "conf": conf}

_HOTEN_SPEC = next(s for s in FIELD_SPECS if s["key"] == "hoten")

def test_name_gets_located_slot_on_noisy_contract_label():
    # Supplier-block label OCRs with trailing noise tokens ("(Ký, ghi rõ họ tên)")
    # and the handwritten name below is unreadable -> find_name's strict match
    # would miss it; the tolerant located-slot fallback still boxes a slot.
    page0 = [
        _word("BÊN", 100, 500), _word("CUNG", 150, 500), _word("ỨNG", 210, 500),
        _word("DỊCH", 260, 500), _word("VỤ", 320, 500),
        _word("(Ký,", 380, 500), _word("ghi", 430, 500), _word("rõ", 470, 500),
    ]
    hits = _hits_for_doc(_HOTEN_SPEC, {0: page0})
    assert hits, "expected a located name slot on the contract page"
    page_idx, hit = hits[0]
    assert page_idx == 0
    assert hit["value"] == ""            # unread -> cần xem
    assert hit["confidence"] == 0.0
    assert hit["bbox"]["width"] > 0 and hit["bbox"]["x"] >= 320  # right of the label
```

Note: with the *current* code this may already pass if `find_name`'s geometric fallback fires; the test pins the required behavior either way. If it passes unchanged, keep it (a regression guard) and proceed to 5b. If it fails, implement Step 3.

- [ ] **Step 2: Run to verify** — `cd server && python3 -m pytest ocr_extract_test.py::test_name_gets_located_slot_on_noisy_contract_label -q`

- [ ] **Step 3: Add the tolerant fallback** in `server/ocr_extract.py`

Add a helper that reuses the value-field machinery (substring anchor + geometric slot) but keeps the labeled-context guard, then call it from `_hits_for_doc` for name fields **only when `find_name` yields nothing for that doc**:

```python
def _located_name_hits(lines: list[list[dict]], anchors: list[str]) -> list[dict]:
    """Tolerant located-slot fallback for name fields (#009 batch1): on a doc
    where `find_name`'s strict token match found nothing, still box the value
    slot at a supplier/heading label found by SUBSTRING (like value fields do
    via `locate_field`), scoped to labeled lines (ALL CAPS or a ':'/heading
    context) so recurring mixed-case prose mentions never flood it. Emits
    unread ('') slots — the human reads the handwriting."""
    anchors_norm = [norm(a) for a in anchors]
    hits = []
    for line in lines:
        text = " ".join(w["text"] for w in line)
        if not any(a in norm(text) for a in anchors_norm):
            continue
        letters = [ch for ch in text if ch.isalpha()]
        labeled = (bool(letters) and text == text.upper()) or text.rstrip().endswith(":")
        if not labeled:
            continue
        hits.append({"value": "", "bbox": _label_region_bbox(line, anchors_norm, lines), "confidence": 0.0})
    return _dedupe_and_cap(hits)
```

Then update `_hits_for_doc`:

```python
def _hits_for_doc(spec: dict, pages: dict[int, list[dict]]) -> list[tuple[int, dict]]:
    hits = []
    for page_idx, words in pages.items():
        lines = group_lines(words)
        if spec["kind"] == "name":
            page_hits = find_name(lines, spec["anchors"])
            if not page_hits:
                page_hits = _located_name_hits(lines, spec["anchors"])
        else:
            page_hits = locate_field(lines, spec)
        hits.extend((page_idx, h) for h in page_hits)
    return hits
```

- [ ] **Step 4: Run → pass, and confirm no flooding regression**

Run: `cd server && python3 -m pytest ocr_extract_test.py -q` → PASS (new test + all existing name/flooding tests still green — the labeled guard keeps prose out).

### 5b — value checks prefer their routed-doc source (checklist) — THE fix

- [ ] **Step 5: Write the failing test** — add to `server/checklist_test.py`

```python
def test_value_check_prefers_source_on_its_routed_doc():
    # hoten located on BOTH bbnt (readable) and contract (unread slot); B1 routes
    # to 'contract', so it must pick the contract source, not sources[0].
    fields = [{"key": "hoten", "label": "Họ và tên", "expected": "Nguyễn Hoàng Phúc",
               "sources": [
                   {"docId": "bbnt", "page": 2, "value": "Nguyễn Hoàng Phúc",
                    "bbox": {"x":1,"y":1,"width":1,"height":1}, "confidence": 0.9},
                   {"docId": "contract", "page": 0, "value": "",
                    "bbox": {"x":5,"y":5,"width":9,"height":3}, "confidence": 0.0},
               ]}]
    c = {x["code"]: x for x in build_checklist(fields, MATCH, DOCS)}
    assert c["B1"]["evidenceDocId"] == "contract"
    assert c["B1"]["source"]["docId"] == "contract"
```

- [ ] **Step 6: Run → fail** (`build_checklist` takes `sources[0]` = bbnt).

- [ ] **Step 7: Add routed-source preference** in `server/checklist.py`

In the `_VALUE` loop, when the routed doc kind resolves to a concrete doc id present among the field's sources, prefer that source:

```python
    for code, label, kind_doc, fkey in _VALUE:
        f = by_key.get(fkey)
        if not f:
            continue
        sources = f.get("sources") or []
        routed = contract if kind_doc == "contract" else _doc_by_kind(docs, kind_doc)
        src = next((s for s in sources if s and s.get("docId") == routed), None) or (sources[0] if sources else None)
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "value",
                       "evidenceDocId": (src or {}).get("docId") or routed,
                       "reference": f.get("expected", ""), "source": src,
                       "autostatus": _autostatus(f.get("expected", ""), src)})
```

This preserves existing behavior when there's a single source (`test_contract_routed_checks_fall_back_to_first_doc` still passes) and fixes B1's multi-source case.

- [ ] **Step 8: Mirror the preference in `demoChecklist.ts`** (so the offline demo behaves identically)

In the value loop of `src/ctv/demoChecklist.ts`, replace `const src = f.sources[0] ?? null` with routed-source preference. Add a routed-kind lookup per code. Since the demo's `VALUE` table currently carries `[code, label, fieldKey]`, extend it to `[code, label, fieldKey, routedKind]` and select accordingly:

```ts
const VALUE: ReadonlyArray<readonly [string, string, string, EvidenceKind]> = [
  ['B1', 'Họ tên khớp bảng kê', 'name', 'contract'],
  ['A1', 'Số CCCD khớp giữa chứng từ', 'cccd', 'contract'],
  ['B2', 'Phí dịch vụ khớp bảng kê', 'gross', 'contract'],
  ['BANK', 'Số tài khoản khớp bảng kê', 'bank_acct', 'contract'],
  ['INFO', 'Ngày sinh khớp hồ sơ', 'dob', 'contract'],
]
// ...
for (const [code, label, fieldKey, routedKind] of VALUE) {
  const f = byKey.get(fieldKey)
  if (!f) continue
  const routed = docByKind(folder, routedKind) ?? contract
  const src = f.sources.find(s => s.docId === routed) ?? f.sources[0] ?? null
  checks.push({
    code, label, tier: 'detail', kind: 'value',
    evidenceDocId: src?.docId ?? contract,
    reference: f.expected ?? '', source: src,
    autostatus: autostatus(f.expected ?? '', src),
  })
}
```

- [ ] **Step 9: Full verify**

Run: `cd server && python3 -m pytest -q` → all pass. `npx tsc --noEmit` → 0. `npx vitest run` → all pass.

- [ ] **Step 10: Commit**

```bash
git add server/ocr_extract.py server/ocr_extract_test.py server/checklist.py server/checklist_test.py src/ctv/demoChecklist.ts
git commit -m "fix(ocr/checklist): name lands on contract label-anchored slot; value checks prefer routed-doc source (batch1 #9)"
```

---

## Task 6: Item 7 (backend) — B3 & C2 signature focus region (heuristic, no detection)

**Why:** No signature detection ("locate & look"). Both signature gates auto-navigate to the evidence doc's **last page** and zoom to a **bottom band** (where sign/seal/giáp-lai sit), with a **soft caption** ("Khu vực chữ ký & con dấu") and **no hard red box** (a precise box would imply detection we don't have). When a packet has two BBNTs (nghiệm thu + thanh lý), C2 focuses the **thanh lý** one. `build_checklist` computes this from `docs` (which carry `pages` with width/height).

**Files:**
- Modify: `src/ctv/types.ts` (add `CheckFocus` + `CheckItem.focus`)
- Modify: `server/checklist.py` (+ `checklist_test.py`)
- Modify: `src/ctv/demoChecklist.ts`

- [ ] **Step 1: Add the type** in `src/ctv/types.ts`

Below `CheckItem`, add:

```ts
// A soft "land & look" focus for checks with no detectable bbox (e.g. the
// signature/seal band of a contract or BBNT). The scan pane navigates to
// `page` and zooms to `bbox`, drawing `caption` instead of the red value box.
export interface CheckFocus { page: number; bbox: Bbox; caption: string }
```

and extend `CheckItem` with an optional field (keep it optional for pre-v2 manifests):

```ts
export interface CheckItem {
  code: string
  label: string
  tier: CheckTier
  kind: CheckKind
  evidenceDocId: string | null
  reference: string | null
  source: CtvSource | null
  autostatus: CheckAutoStatus | null
  focus?: CheckFocus | null       // #7 signature landing (no red box)
}
```

Run `npx tsc --noEmit` → still 0 (optional field, no consumers yet).

- [ ] **Step 2: Write failing backend tests** — add to `server/checklist_test.py`

Give the test docs real `pages` so the focus band can be computed:

```python
DOCS_PAGED = [
    {"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ",
     "pages": [{"src": "a", "width": 1000, "height": 1400},
               {"src": "b", "width": 1000, "height": 1400}]},
    {"id": "bbnt-0", "kind": "bbnt", "label": "Biên bản nghiệm thu",
     "pages": [{"src": "c", "width": 1000, "height": 1400}]},
    {"id": "bbnt-1", "kind": "bbnt", "label": "Biên bản thanh lý hợp đồng",
     "pages": [{"src": "d", "width": 1000, "height": 1400},
               {"src": "e", "width": 1000, "height": 1400}]},
    {"id": "camket", "kind": "commitment", "label": "Bản cam kết",
     "pages": [{"src": "f", "width": 1000, "height": 1400}]},
]

def test_signature_gates_focus_last_page_bottom_band():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS_PAGED))
    b3 = c["B3"]["focus"]
    assert b3 is not None
    assert b3["page"] == 1                       # contract's last page (0-based)
    assert b3["caption"] == "Khu vực chữ ký & con dấu"
    # bottom band: starts in the lower part of the page, reaches the bottom edge
    assert b3["bbox"]["y"] > 1400 * 0.5
    assert b3["bbox"]["y"] + b3["bbox"]["height"] <= 1400
    assert b3["bbox"]["width"] == 1000

def test_c2_focuses_thanh_ly_bbnt_when_two_bbnts():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS_PAGED))
    assert c["C2"]["evidenceDocId"] == "bbnt-1"   # the thanh lý one, not nghiệm thu
    assert c["C2"]["focus"]["page"] == 1          # its last page

def test_signature_focus_absent_when_doc_has_no_pages():
    # DOCS (the module-level fixture) has no 'pages' -> no focus computed, no crash
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["B3"].get("focus") in (None, )
```

- [ ] **Step 3: Run → fail** (`focus` not emitted; C2 routes to first bbnt).

- [ ] **Step 4: Implement focus + thanh-lý routing** in `server/checklist.py`

Add helpers and use them in the gate loop. The bottom band = the lower ~28% of the last page, full width:

```python
_SIGN_CAPTION = "Khu vực chữ ký & con dấu"
_SIGN_BAND_FRAC = 0.28   # bottom fraction of the page where sign/seal/giáp-lai sit

def _doc_obj_by_kind(docs: list[dict], kind: str) -> dict | None:
    for d in docs:
        if d.get("kind") == kind:
            return d
    return None

def _bbnt_for_c2(docs: list[dict]) -> dict | None:
    """C2 focuses the thanh-lý BBNT when a packet has both (nghiệm thu + thanh
    lý); else the only/first BBNT. Distinguished by label (the type enum shares
    'bbnt' for both)."""
    bbnts = [d for d in docs if d.get("kind") == "bbnt"]
    if not bbnts:
        return None
    for d in bbnts:
        if "thanh ly" in _norm(d.get("label", "")):
            return d
    return bbnts[0]

def _signature_focus(doc: dict | None) -> dict | None:
    """Last page + bottom-band bbox + soft caption for a signature gate, or
    None if the doc is missing or carries no page geometry (e.g. a bare test
    fixture)."""
    if not doc:
        return None
    pages = doc.get("pages") or []
    if not pages:
        return None
    last = len(pages) - 1
    p = pages[last]
    w, h = p.get("width", 0), p.get("height", 0)
    if not (w and h):
        return None
    band = round(h * _SIGN_BAND_FRAC)
    return {"page": last, "caption": _SIGN_CAPTION,
            "bbox": {"x": 0, "y": h - band, "width": w, "height": band}}
```

In the gate loop, route C2 to the thanh-lý BBNT and attach focus for B3/C2:

```python
    for code, label, kind_doc in _CONFIRM_GATES:
        if code == "C2":
            doc = _bbnt_for_c2(docs)
        elif kind_doc == "contract":
            doc = _doc_obj_by_kind(docs, "contract") or (docs[0] if docs else None)
        else:
            doc = _doc_obj_by_kind(docs, kind_doc)
        if doc is None:
            continue   # #5: routed doc absent -> no dead row
        focus = _signature_focus(doc) if code in ("B3", "C2") else None
        checks.append({"code": code, "label": label, "tier": "gate", "kind": "confirm",
                       "evidenceDocId": doc["id"],
                       "reference": None, "source": None, "autostatus": None,
                       "focus": focus})
```

(Note: this replaces the Task-4 gate loop; `contract` local is still computed above for value routing. `D3` gets `focus=None`, as do all other checks — leave `focus` absent/None on non-signature rows. `_norm` already exists in this module.)

- [ ] **Step 5: Run backend tests → pass**

Run: `cd server && python3 -m pytest checklist_test.py -q` → PASS (new focus/thanh-lý tests + all prior). Confirm `test_confirm_kinds_and_routing` from Task 3 still holds — with the module-level `DOCS` (single bbnt "Biên bản thanh lý"), `C2` routes to `"bbnt"`. ✓

- [ ] **Step 6: Mirror in `demoChecklist.ts`**

Add the same computation (folder docs carry `pages`). Add helpers near the top:

```ts
const SIGN_CAPTION = 'Khu vực chữ ký & con dấu'
const SIGN_BAND_FRAC = 0.28

function signatureFocus(doc: EvidenceDoc | undefined): CheckFocus | null {
  if (!doc || doc.pages.length === 0) return null
  const last = doc.pages.length - 1
  const { width: w, height: h } = doc.pages[last]
  if (!w || !h) return null
  const band = Math.round(h * SIGN_BAND_FRAC)
  return { page: last, caption: SIGN_CAPTION, bbox: { x: 0, y: h - band, width: w, height: band } }
}

const bbntForC2 = (folder: CtvFolder): EvidenceDoc | undefined => {
  const bbnts = folder.docs.filter(d => d.kind === 'bbnt')
  return bbnts.find(d => norm(d.label).includes('thanh ly')) ?? bbnts[0]
}
```

Import `CheckFocus` from `./types`. Set `focus` on the B3/C2 rows: B3 → `signatureFocus(folder.docs.find(d => d.kind === 'contract'))`, C2 → route `evidenceDocId` to `bbntForC2(folder)?.id ?? null` and `focus: signatureFocus(bbntForC2(folder))`. Keep the Task-4 conditional-emission guards. All other rows may omit `focus` (optional).

- [ ] **Step 7: Verify frontend**

Run: `npx tsc --noEmit` → 0; `npx vitest run` → all pass. (No UI consumes `focus` yet — that's Task 9.)

- [ ] **Step 8: Commit**

```bash
git add src/ctv/types.ts server/checklist.py server/checklist_test.py src/ctv/demoChecklist.ts
git commit -m "feat(checklist): B3/C2 signature focus band (last page bottom) + C2 thanh-lý routing (batch1 #7 backend)"
```

---

## Task 7: Item 6 — D3 "Xem mẫu chuẩn" reference-template lightbox

**Why:** D3 (and later other checks) should offer a **"Xem mẫu chuẩn — {year}"** button that opens a blank reference form in a **lightbox/modal over the scan pane** (submitted doc stays underneath). PII-free, bundled as a static asset so it works in the offline export. Add an optional `referenceAsset?: string` to `CheckItem`; no new review state.

**Files:**
- Create: `public/reference/mau-08-ck-tncn-2026.svg` (placeholder), `src/components/ReferenceLightbox.tsx`
- Modify: `src/ctv/types.ts` (`CheckItem.referenceAsset`), `server/checklist.py` (+ test), `src/ctv/demoChecklist.ts`, `src/ctv/folders.ts` (commitment doc for one demo folder), `src/components/ChecklistPanel.tsx`, `src/components/FolderReview.tsx`, `src/styles.css`

- [ ] **Step 1: Add the type field** in `src/ctv/types.ts`

```ts
  focus?: CheckFocus | null
  referenceAsset?: string          // #6 blank reference-template asset (e.g. Mẫu 08/CK-TNCN)
```

- [ ] **Step 2: Backend test + implementation** — D3 carries the asset path.

Add to `server/checklist_test.py`:

```python
def test_d3_carries_reference_asset_when_commitment_present():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["D3"]["referenceAsset"] == "/reference/mau-08-ck-tncn-2026.svg"

def test_no_reference_asset_on_other_checks():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert "referenceAsset" not in c["B3"] or c["B3"].get("referenceAsset") is None
```

Run → fail. Then in `server/checklist.py`, define the constant and attach it to D3 in the gate loop:

```python
_D3_REFERENCE_ASSET = "/reference/mau-08-ck-tncn-2026.svg"   # blank current-year Mẫu 08/CK-TNCN (PII-free)
```

In the gate loop, when building the check dict, add the asset for D3 only:

```python
        check = {"code": code, "label": label, "tier": "gate", "kind": "confirm",
                 "evidenceDocId": doc["id"],
                 "reference": None, "source": None, "autostatus": None,
                 "focus": focus}
        if code == "D3":
            check["referenceAsset"] = _D3_REFERENCE_ASSET
        checks.append(check)
```

Run: `cd server && python3 -m pytest checklist_test.py -q` → PASS.

- [ ] **Step 3: Create the placeholder asset** — `public/reference/mau-08-ck-tncn-2026.svg`

A PII-free A4 placeholder that clearly reads as the blank template slot (real blank form to be dropped in by Acc). Match the synthetic folder assets' style (plain SVG):

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 1414" width="1000" height="1414">
  <rect width="1000" height="1414" fill="#ffffff"/>
  <rect x="40" y="40" width="920" height="1334" fill="none" stroke="#c8d0da" stroke-width="2"/>
  <text x="500" y="120" text-anchor="middle" font-family="Arial, sans-serif" font-size="34" font-weight="700" fill="#1f2d3d">Mẫu 08/CK-TNCN</text>
  <text x="500" y="170" text-anchor="middle" font-family="Arial, sans-serif" font-size="22" fill="#5b6a7d">Bản cam kết thuế thu nhập cá nhân — Mẫu chuẩn (trống)</text>
  <text x="500" y="210" text-anchor="middle" font-family="Arial, sans-serif" font-size="18" fill="#9aa7b4">Năm 2026 · bản tham chiếu · dữ liệu trống</text>
  <g stroke="#e3e8ee" stroke-width="1.5">
    <line x1="80" y1="300" x2="920" y2="300"/><line x1="80" y1="360" x2="920" y2="360"/>
    <line x1="80" y1="420" x2="920" y2="420"/><line x1="80" y1="480" x2="920" y2="480"/>
    <line x1="80" y1="540" x2="920" y2="540"/><line x1="80" y1="600" x2="920" y2="600"/>
  </g>
  <!-- TODO(acc): replace this placeholder with the real blank current-year Mẫu 08/CK-TNCN (must stay PII-free). -->
</svg>
```

- [ ] **Step 4: Create the lightbox component** — `src/components/ReferenceLightbox.tsx`

```tsx
import { useEffect } from 'react'
import { assetUrl } from '../assets'

interface Props { src: string | null; title: string; onClose: () => void }

// #6: a modal over the scan pane showing a blank reference template (the
// submitted doc stays underneath). Esc / backdrop / ✕ close it. No review state.
export default function ReferenceLightbox({ src, title, onClose }: Props) {
  useEffect(() => {
    if (!src) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [src, onClose])
  if (!src) return null
  return (
    <div className="ref-backdrop" onClick={onClose}>
      <div className="ref-panel" onClick={e => e.stopPropagation()}>
        <div className="ref-head">
          <strong>{title}</strong>
          <button className="ref-close" onClick={onClose} aria-label="Đóng">✕</button>
        </div>
        <div className="ref-body">
          <img src={assetUrl(src)} alt={title} draggable={false} />
        </div>
      </div>
    </div>
  )
}
```

- [ ] **Step 5: Add the button to the routed check row** in `src/components/ChecklistPanel.tsx`

Extend `Props` with an `onOpenReference: (asset: string, label: string) => void` callback. In `row(c)`, when `c.referenceAsset` is set, render a button inside `.check-main` (below the label). The year comes from the asset filename or a fixed current year — use a fixed label "Xem mẫu chuẩn — 2026" derived from the asset (keep it simple: the button label is `Xem mẫu chuẩn — {yearFromAsset}`):

```tsx
{c.referenceAsset && (
  <button className="ref-btn" onClick={e => { e.stopPropagation(); onOpenReference(c.referenceAsset!, c.label) }}>
    Xem mẫu chuẩn — {(c.referenceAsset.match(/(20\d{2})/)?.[1]) ?? ''}
  </button>
)}
```

Thread the new prop through the component signature and its destructure.

- [ ] **Step 6: Host the lightbox in `FolderReview`**

Add state + handler and render the lightbox after `EvidenceViewer` inside `.panes` (so it overlays the scan pane):

```tsx
const [refAsset, setRefAsset] = useState<{ src: string; title: string } | null>(null)
// ...
<ChecklistPanel checks={checks} review={review} selectedCode={selectedCode}
  onSelect={focusCheck} onToggleFlag={toggleFlag}
  onOpenReference={(src, label) => setRefAsset({ src, title: `Mẫu chuẩn — ${label}` })} />
// ...after EvidenceViewer, still inside .panes:
<ReferenceLightbox src={refAsset?.src ?? null} title={refAsset?.title ?? ''} onClose={() => setRefAsset(null)} />
```

Import `ReferenceLightbox`.

- [ ] **Step 7: Add one commitment doc to a demo folder** (decision #2) — `src/ctv/folders.ts`

Create `public/folders/le-thi-mai-anh/bancamket.svg` (a PII-free A4 placeholder titled "BẢN CAM KẾT" — same SVG style as Step 3, different title text). Then add a `commitment` doc to the `le-thi-mai-anh` folder's `docs` array (use the same `A4` size spread the other docs use):

```ts
{ id: 'commitment', kind: 'commitment', label: 'Bản cam kết', pages: [{ src: `/folders/${id}/bancamket.svg`, ...A4 }] },
```

(Add it after the `bbnt` doc. Only this one folder — leave `tran-minh-khoa` and `pham-quoc-hung` without a commitment doc so item 5's omission is visible offline.)

- [ ] **Step 8: Set `referenceAsset` on D3 in the offline mirror** — `src/ctv/demoChecklist.ts`

On the D3 push (only emitted when `commitment` exists), add `referenceAsset: '/reference/mau-08-ck-tncn-2026.svg'`.

- [ ] **Step 9: Style the button + lightbox** — `src/styles.css`

```css
.ref-btn { margin-top: 6px; font-size: 12px; padding: 3px 10px; border: 0.5px solid var(--accent);
  color: var(--accent); background: transparent; border-radius: 6px; cursor: pointer; }
.ref-btn:hover { background: #eaf1fb; }
.ref-backdrop { position: absolute; inset: 0; background: rgba(15,23,32,.55); z-index: 20;
  display: flex; align-items: center; justify-content: center; }
.ref-panel { background: var(--surface); border-radius: 10px; width: min(70%, 760px); max-height: 88%;
  display: flex; flex-direction: column; box-shadow: 0 10px 40px rgba(0,0,0,.35); overflow: hidden; }
.ref-head { display: flex; align-items: center; justify-content: space-between; padding: 10px 14px;
  border-bottom: 0.5px solid var(--border); }
.ref-close { border: 0; background: transparent; font-size: 16px; cursor: pointer; }
.ref-body { overflow: auto; padding: 12px; background: var(--mat); }
.ref-body img { display: block; width: 100%; height: auto; background: #fff; }
```

The `.ref-backdrop` is `position: absolute; inset: 0` and must overlay the scan pane — ensure `.panes` (or the scan section) is a positioned ancestor. `.ev` is `flex: 1`; add `position: relative` to `.panes` if the backdrop should cover the whole review area, or to `.ev` to cover just the scan pane. Per spec ("over the scan pane"), anchor it to `.ev`: render the lightbox *inside* EvidenceViewer instead — simpler positioning. **Chosen approach:** pass `refAsset` into `EvidenceViewer` is heavier; instead set `.panes { position: relative }` and let the backdrop cover the panes area (checklist + scan). This is acceptable and keeps FolderReview as the host. Add `.panes { position: relative }` if not already present.

- [ ] **Step 10: Verify + preview**

Run: `npx tsc --noEmit` → 0; `npx vitest run` → all pass; `cd server && python3 -m pytest -q` → all pass.
Preview: on the `le-thi-mai-anh` demo folder, D3 appears with a "Xem mẫu chuẩn — 2026" button; clicking opens the lightbox over the scan pane; Esc/backdrop/✕ close it. The other two folders show no D3 row.

- [ ] **Step 11: Commit**

```bash
git add src/ctv/types.ts server/checklist.py server/checklist_test.py src/ctv/demoChecklist.ts src/ctv/folders.ts src/components/ReferenceLightbox.tsx src/components/ChecklistPanel.tsx src/components/FolderReview.tsx src/styles.css public/reference public/folders/le-thi-mai-anh/bancamket.svg
git commit -m "feat(reviewer): D3 'Xem mẫu chuẩn' reference-template lightbox + referenceAsset (batch1 #6)"
```

---

## Task 8: Item 1 — doc-viewer view modes (1 trang / Cuộn liên tục / 2 trang)

**Why:** Add a scan-pane toolbar with three modes. `1 trang` = current single-page transform view (the only mode that auto-focuses, delivered in Task 9). `Cuộn liên tục` = all pages of the current doc stacked in natural vertical scroll (a real refactor: today's zoom is a single-page CSS transform; continuous needs a scroll-stack with width-based zoom). `2 trang` = two-page spread, pager steps by 2. Zoom/pan available in all modes; no new hotkey (toolbar only). In `Cuộn liên tục`, ←→ jumps between documents (pages already scroll — completing item 10's continuous branch).

**Files:**
- Modify: `src/logic/viewMode.ts` (create) + `viewMode.test.ts`; `src/logic/pageNav.ts` (`stepDoc`) + tests
- Modify: `src/components/EvidenceViewer.tsx` (mode state, toolbar, continuous/2-page rendering, mode-aware zoom)
- Modify: `src/components/FolderReview.tsx` (owns `viewMode`; continuous ←→ = stepDoc)
- Modify: `src/styles.css` (continuous + 2-page layout, mode control)
- Modify: `src/components/HotkeyHelp.tsx` (note view-mode toolbar)

- [ ] **Step 1: Create `viewMode.ts` types + zoom clamp, with tests** — `src/logic/viewMode.test.ts`

```ts
import { describe, it, expect } from 'vitest'
import { clampZoom, VIEW_MODES } from './viewMode'

describe('viewMode', () => {
  it('exposes the three modes in toolbar order', () => {
    expect(VIEW_MODES.map(m => m.mode)).toEqual(['1', 'cont', '2'])
  })
  it('clamps continuous zoom into [0.5, 4]', () => {
    expect(clampZoom(0.1)).toBe(0.5)
    expect(clampZoom(9)).toBe(4)
    expect(clampZoom(1.5)).toBe(1.5)
  })
})
```

- [ ] **Step 2: Run → fail.** Then implement `src/logic/viewMode.ts`:

```ts
export type ViewMode = '1' | 'cont' | '2'

export const VIEW_MODES: ReadonlyArray<{ mode: ViewMode; label: string }> = [
  { mode: '1', label: '1 trang' },
  { mode: 'cont', label: 'Cuộn liên tục' },
  { mode: '2', label: '2 trang' },
]

/** Continuous-mode width multiplier, clamped to a sane range (1 = fit width). */
export function clampZoom(z: number): number {
  return Math.max(0.5, Math.min(4, z))
}
```

Run → PASS.

- [ ] **Step 3: Add `stepDoc` to `pageNav.ts`, with tests** — append to `src/logic/pageNav.test.ts`:

```ts
import { stepDoc } from './pageNav'

describe('stepDoc', () => {
  it('moves to the next document', () => {
    expect(stepDoc(DOCS, 'a', +1)).toBe('b')
  })
  it('moves to the previous document', () => {
    expect(stepDoc(DOCS, 'b', -1)).toBe('a')
  })
  it('clamps at the ends', () => {
    expect(stepDoc(DOCS, 'a', -1)).toBe('a')
    expect(stepDoc(DOCS, 'c', +1)).toBe('c')
  })
})
```

Run → fail. Implement in `src/logic/pageNav.ts`:

```ts
/** Step to the adjacent document id (clamped at the ends). */
export function stepDoc(docs: EvidenceDoc[], activeDocId: string, dir: 1 | -1): string {
  const i = Math.max(0, docs.findIndex(d => d.id === activeDocId))
  return docs[Math.max(0, Math.min(i + dir, docs.length - 1))].id
}
```

Run → PASS.

- [ ] **Step 4: Refactor `EvidenceViewer` to render three modes.** This is the core change. Add a controlled `viewMode` + `onSetViewMode` prop pair, a continuous-zoom state, and two render branches. Key requirements:
  - **Props:** add `viewMode: ViewMode` and `onSetViewMode: (m: ViewMode) => void` to `Props`.
  - **Toolbar:** a segmented control (top-left of the stage) rendering `VIEW_MODES`; the active one highlighted; clicking calls `onSetViewMode`.
  - **`1 trang`:** unchanged transform stage — one page image inside `.doc-page` with the `frame` transform; `hl`/roster callout as today; pager steps by 1.
  - **`2 trang`:** transform stage, but `.doc-page` contains up to two page images side-by-side (`pageIdx` and `pageIdx+1`); `loupeFrame` fits the combined natural box (`natW = wA + gap + wB`, `natH = max(hA,hB)`); pager steps by 2 and its label reads `{pairStart+1}–{min(pairStart+2,pageCount)} / {pageCount}`; auto-focus disabled (only `1 trang` auto-focuses); the red `hl`/roster callout render only in `1 trang`.
  - **`Cuộn liên tục`:** a native-scroll container `.ev-scroll` (replaces the transform stage) listing **all** `doc.pages` stacked vertically; each `<img>` sized `width: {contZoom * 100}%` of a fit-width baseline (use `width` in px = `fitWidthPx * contZoom`, `height: auto`); vertical + horizontal scroll native; no red box, no auto-zoom; when the doc changes, scroll to top.
  - **Mode-aware zoom/fit:** the `zoom(factor)` and Alt +/- handlers and the +/- toolbar buttons adjust `frame.scale` in `1`/`2` and `contZoom` (via `clampZoom`) in `cont`. `fit` resets: `frame` via `loupeFrame(null, natCombined, vp)` in `1`/`2`, `contZoom = 1` in `cont`. The percent readout shows `frame.scale` in transform modes, `contZoom` in continuous.
  - **Pan:** transform modes keep drag-pan (`panMode`); continuous uses native scroll (disable `panMode` drag when `viewMode === 'cont'`).
  - Guard the auto-focus `useLayoutEffect` so it only runs when `viewMode === '1'` (and not `lockView`).

  A near-complete implementation for the render body (adapt imports/handlers to the existing file):

```tsx
// derived
const isCont = viewMode === 'cont'
const step = viewMode === '2' ? 2 : 1
const pairStart = viewMode === '2' ? pageIdx - (pageIdx % 2) : pageIdx
const pagesInView = viewMode === '2'
  ? doc.pages.slice(pairStart, pairStart + 2)
  : [page]
const gap = 16
const natCombined = viewMode === '2'
  ? { w: pagesInView.reduce((s, p) => s + p.width, 0) + gap * (pagesInView.length - 1),
      h: Math.max(...pagesInView.map(p => p.height)) }
  : nat

// auto-focus only in single-page mode
useLayoutEffect(() => {
  if (viewMode !== '1' || lockView || vp.w === 0) return
  setFrame(loupeFrame(inflated, nat, vp))
}, [inflated, vp.w, vp.h, activeDocId, pageIdx, lockView, viewMode])

// re-fit the pair when 2-page mode / pair changes
useLayoutEffect(() => {
  if (viewMode !== '2' || lockView || vp.w === 0) return
  setFrame(loupeFrame(null, natCombined, vp))
}, [viewMode, pairStart, activeDocId, vp.w, vp.h, lockView])

// continuous: scroll to top on doc change
const scrollRef = useRef<HTMLDivElement>(null)
useLayoutEffect(() => {
  if (isCont && scrollRef.current) scrollRef.current.scrollTop = 0
}, [isCont, activeDocId])
```

  Render the stage conditionally:

```tsx
{isCont ? (
  <div className="ev-scroll" ref={scrollRef}>
    {doc.pages.map((p, i) => (
      <img key={i} className="cont-page" src={assetUrl(p.src)}
        style={{ width: (vp.w * 0.92) * contZoom, height: 'auto' }}
        alt="" draggable={false} />
    ))}
  </div>
) : (
  <div className={panMode ? 'ev-stage panning' : 'ev-stage'} ref={ref} onMouseDown={onStageMouseDown}>
    <div className="doc-page" style={{ transform: `translate(${frame.tx}px, ${frame.ty}px) scale(${frame.scale})` }}>
      {pagesInView.map((p, i) => (
        <img key={i} src={assetUrl(p.src)} width={p.width} height={p.height}
          style={{ marginLeft: i > 0 ? gap : 0 }} alt="" draggable={false} />
      ))}
    </div>
    {viewMode === '1' && hl && <div className="doc-hl" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />}
    {viewMode === '1' && showRoster && rosterValue && (/* existing roster callout block */)}
  </div>
)}
```

  Move the pager/tools/mode-control so they render in both branches (siblings of the stage/scroll). The `.doc-page` must become `display: flex` for the 2-page row (see CSS step). Keep the ResizeObserver on a wrapper that exists in both branches (attach `ref`/`scrollRef` appropriately, or wrap both in a common positioned container that the ResizeObserver watches for `vp`).

  **Important:** the ResizeObserver currently observes `ref` (the stage). In continuous mode the stage isn't rendered. Attach a stable outer wrapper `<div className="ev-view">` around both branches and observe *that* for `vp`, so `vp.w` is valid in all modes.

- [ ] **Step 5: Add the view-mode state to `FolderReview`** and pass it down.

```tsx
const [viewMode, setViewMode] = useState<ViewMode>('1')
// ...
<EvidenceViewer /* ...existing... */ viewMode={viewMode} onSetViewMode={setViewMode} />
```

Import `ViewMode` from `../logic/viewMode`. (Task 9 makes `viewMode` follow the selected check; for now it's a manual toolbar toggle defaulting to `1 trang`.)

- [ ] **Step 6: Continuous-mode ←→ jumps documents** — in `FolderReview`'s ←→ branch (from Task 2), special-case continuous:

```tsx
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        e.preventDefault()
        const dir = e.key === 'ArrowRight' ? 1 : -1
        if (viewMode === 'cont') {
          const docId = stepDoc(folder.docs, activeDocId, dir)
          setActiveDocId(docId); setActivePage(0); setFocusBbox(null)
        } else {
          const { docId, page } = stepPage(folder.docs, activeDocId, activePage, dir)
          setActiveDocId(docId); setActivePage(page); setFocusBbox(null)
        }
      }
```

Add `stepDoc` to the import and `viewMode` to the effect deps.

- [ ] **Step 7: CSS** — `src/styles.css`

```css
.ev-view { flex: 1; position: relative; min-height: 0; display: flex; }
.ev-modes { position: absolute; top: 10px; left: 10px; z-index: 3; display: flex; gap: 2px;
  background: var(--surface); border: 0.5px solid var(--border); border-radius: 8px; padding: 2px; }
.ev-modes button { border: 0; background: transparent; cursor: pointer; font-size: 12px;
  padding: 3px 8px; border-radius: 6px; color: var(--text-muted); white-space: nowrap; }
.ev-modes button.on { background: var(--accent); color: #fff; }
.doc-page { position: absolute; top: 0; left: 0; transform-origin: 0 0; display: flex; align-items: flex-start; }
.ev-scroll { flex: 1; overflow: auto; background: var(--mat); padding: 16px; display: flex;
  flex-direction: column; align-items: center; gap: 16px; }
.cont-page { display: block; background: #fff; box-shadow: 0 1px 6px rgba(0,0,0,.15); max-width: none; }
```

(Keep `.ev-stage`/`.doc-hl`/`.doc-pager`/`.doc-tools` as-is; they now live inside `.ev-view`.)

- [ ] **Step 8: Hotkey legend note** — `src/components/HotkeyHelp.tsx`, add a row:

```tsx
  { keys: 'Thanh chế độ xem', desc: '1 trang · Cuộn liên tục · 2 trang (trên thanh công cụ)' },
```

- [ ] **Step 9: Verify + preview thoroughly** (this is the biggest change)

Run: `npx tsc --noEmit` → 0; `npx vitest run` → all pass.
Preview each mode on a multi-page doc (the demo contract has 5 pages):
  - `1 trang`: single page, red box + roster callout still work, Alt+/- zoom, pager steps 1.
  - `Cuộn liên tục`: all 5 pages stacked, natural scroll, +/- changes page width, ←→ jumps to the adjacent document.
  - `2 trang`: two pages side by side, pager steps by 2, label like "1–2 / 5", Alt+/- zoom the pair.
Screenshot each mode for the completion evidence.

- [ ] **Step 10: Commit**

```bash
git add src/logic/viewMode.ts src/logic/viewMode.test.ts src/logic/pageNav.ts src/logic/pageNav.test.ts src/components/EvidenceViewer.tsx src/components/FolderReview.tsx src/components/HotkeyHelp.tsx src/styles.css
git commit -m "feat(reviewer): scan-pane view modes — 1 trang / Cuộn liên tục / 2 trang (batch1 #1)"
```

---

## Task 9: Item 2 — view mode follows the selected check (value / signature / skim)

**Why:** On selecting a check, open it in the view that fits it; a manual override holds while the reviewer stays on that check; moving to another check re-applies that check's default. Three shapes: **value** → `1 trang`, auto-zoom to the detected bbox; **signature** (B3, C2) → `1 trang`, auto-zoom to the last-page bottom band (Task 6's `focus`), soft caption, no red box; **skim** (G-DOC, D3, D1) → `Cuộn liên tục`, no zoom.

**Files:**
- Modify: `src/logic/viewMode.ts` (+ test) — `viewModeForCheck`
- Modify: `src/components/FolderReview.tsx` (`focusCheck` computes default mode + focus; `onSetViewMode` marks override)
- Modify: `src/components/EvidenceViewer.tsx` (soft focus caption vs red box)

- [ ] **Step 1: Write the failing test** — add to `src/logic/viewMode.test.ts`

```ts
import { viewModeForCheck } from './viewMode'
import type { CheckItem } from '../ctv/types'

const mk = (over: Partial<CheckItem>): CheckItem => ({
  code: 'X', label: 'x', tier: 'detail', kind: 'value',
  evidenceDocId: 'd', reference: null, source: null, autostatus: null, ...over,
})

describe('viewModeForCheck', () => {
  it('value checks -> 1 trang', () => {
    expect(viewModeForCheck(mk({ kind: 'value' }))).toBe('1')
  })
  it('signature gates (with focus) -> 1 trang', () => {
    expect(viewModeForCheck(mk({ code: 'B3', kind: 'confirm', focus: { page: 1, bbox: { x:0,y:0,width:1,height:1 }, caption: 'c' } }))).toBe('1')
    expect(viewModeForCheck(mk({ code: 'C2', kind: 'confirm' }))).toBe('1')
  })
  it('skim checks (G-DOC, D3, D1) -> continuous', () => {
    expect(viewModeForCheck(mk({ code: 'G-DOC', kind: 'confirm' }))).toBe('cont')
    expect(viewModeForCheck(mk({ code: 'D3', kind: 'confirm' }))).toBe('cont')
    expect(viewModeForCheck(mk({ code: 'D1', kind: 'confirm' }))).toBe('cont')
  })
})
```

- [ ] **Step 2: Run → fail.** Implement in `src/logic/viewMode.ts`:

```ts
import type { CheckItem } from '../ctv/types'

const SIGNATURE_CODES = new Set(['B3', 'C2'])
const SKIM_CODES = new Set(['G-DOC', 'D3', 'D1'])

/**
 * The default view mode for a check (#2). value + signature land on a single
 * page (1 trang; value auto-zooms to its bbox, signature to its focus band);
 * skim/glance checks open in continuous scroll. A manual toolbar override is
 * layered on top of this in FolderReview and reset when the check changes.
 */
export function viewModeForCheck(c: CheckItem): ViewMode {
  if (c.kind === 'value') return '1'
  if (SIGNATURE_CODES.has(c.code)) return '1'
  if (SKIM_CODES.has(c.code)) return 'cont'
  return '1'
}
```

Run → PASS.

- [ ] **Step 3: Make `focusCheck` apply the per-check default mode + focus** in `src/components/FolderReview.tsx`.

Extend `focusCheck` so, in addition to setting the doc/page/bbox, it:
- sets `viewMode` to `viewModeForCheck(c)` (re-seeding on every check change → a manual override only survives while the same check stays selected);
- for **value** checks: page/bbox from `c.source` as today (red box);
- for **signature** checks with `c.focus`: `setActivePage(c.focus.page)`, `setFocusBbox(c.focus.bbox)`, and set a soft-caption state so EvidenceViewer draws the caption, not the red box;
- for **skim** checks: page 0, no bbox, no caption (continuous mode, no zoom).

```tsx
const [focusCaption, setFocusCaption] = useState<string | null>(null)

const focusCheck = (code: string) => {
  setSelectedCode(code)
  const c = checks.find(x => x.code === code)
  if (!c) return
  const docId = c.evidenceDocId ?? folder.docs[0]?.id ?? ''
  setActiveDocId(docId)
  setViewMode(viewModeForCheck(c))
  if (c.kind === 'value' && c.source) {
    setActivePage(c.source.page); setFocusBbox(c.source.bbox); setFocusCaption(null)
  } else if (c.focus) {                       // signature (#7)
    setActivePage(c.focus.page); setFocusBbox(c.focus.bbox); setFocusCaption(c.focus.caption)
  } else {                                    // skim / plain confirm
    const d = folder.docs.find(x => x.id === docId)
    setActivePage(clampPage(0, d?.pages.length ?? 0)); setFocusBbox(null); setFocusCaption(null)
  }
  markSeen(code)
}
```

Import `viewModeForCheck`. Pass `focusCaption` to `EvidenceViewer` (new prop). When the toolbar changes the mode via `onSetViewMode`, that's the manual override — no extra flag needed because `focusCheck` re-seeds `viewMode` on the next check change.

Also update `onSelectPage`/`onSelectDoc` handlers to clear `focusCaption` (paging away from a signature band drops the caption): add `setFocusCaption(null)` alongside the existing `setFocusBbox(null)` calls, and in the ←→ keydown branch.

- [ ] **Step 4: Render the soft caption in `EvidenceViewer`.**

Add `focusCaption?: string | null` to `Props`. In `1 trang` mode, when `focusCaption` is set, draw a soft band caption instead of the red `doc-hl` box:
- suppress the red box when `focusCaption` is set: `{viewMode === '1' && !focusCaption && hl && <div className="doc-hl" .../>}`;
- add a soft highlight + caption:

```tsx
{viewMode === '1' && focusCaption && hl && (
  <>
    <div className="doc-hl soft" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />
    <div className="doc-caption" style={{ left: hl.left, top: hl.top - 26 }}>{focusCaption}</div>
  </>
)}
```

CSS in `src/styles.css`:

```css
.doc-hl.soft { border-style: dashed; border-color: var(--accent); background: rgba(43,108,214,.06); }
.doc-caption { position: absolute; z-index: 5; background: var(--accent); color: #fff; font-size: 11px;
  padding: 2px 8px; border-radius: 10px; white-space: nowrap; pointer-events: none; }
```

- [ ] **Step 5: Verify + preview**

Run: `npx tsc --noEmit` → 0; `npx vitest run` → all pass.
Preview: selecting a **value** check → `1 trang` + red box auto-zoom; **B3/C2** → `1 trang` landing on the last page bottom with the dashed band + "Khu vực chữ ký & con dấu" caption (no red box); **G-DOC/D3/D1** → `Cuộn liên tục`. Manually switch the toolbar to `2 trang` on a value check, then arrow to the next check → the next check re-applies its own default (override didn't stick across checks). Switch modes and stay on the same check → the override holds.

- [ ] **Step 6: Commit**

```bash
git add src/logic/viewMode.ts src/logic/viewMode.test.ts src/components/FolderReview.tsx src/components/EvidenceViewer.tsx src/styles.css
git commit -m "feat(reviewer): view mode follows the check (value/signature/skim) + soft signature caption (batch1 #2, #7 UI)"
```

---

## Task 10: Item 3 — G-DOC opens in continuous view (glance item, no auto-focus)

**Why:** G-DOC "Đủ chứng từ bắt buộc" is a glance item — keep no auto-focus, and open it in continuous view. This falls out of Task 9's shape mapping (`SKIM_CODES` includes `G-DOC`). This task is a **verification + guard** task: confirm the behavior and lock it with a test.

**Files:**
- Modify: `src/logic/viewMode.test.ts` (explicit G-DOC assertion — may already exist from Task 9 Step 1; keep it)

- [ ] **Step 1: Confirm the mapping test** already asserts `viewModeForCheck({code:'G-DOC',...}) === 'cont'` (added in Task 9). If not present, add it.

- [ ] **Step 2: Preview-verify** G-DOC: selecting it switches the scan pane to `Cuộn liên tục`, shows the first doc from the top with no red box and no auto-zoom.

- [ ] **Step 3: No code change expected.** If a regression is found (e.g. G-DOC's `evidenceDocId` is `null` so no doc loads), fix by defaulting G-DOC's active doc to `folder.docs[0]` in `focusCheck` (it already does `c.evidenceDocId ?? folder.docs[0]?.id`). Confirm the continuous scroll shows the first document.

- [ ] **Step 4: Commit** (only if a change was needed)

```bash
git commit -am "test(reviewer): lock G-DOC -> continuous glance view (batch1 #3)"
```

---

## Task 11: Full verification + offline export rebuild

**Why:** The batch's hard constraint — all three suites green, then the offline single-file export rebuilt and `~/Downloads/Reviewer-v2.0.html` refreshed. Never commit PII (the export inlines only the synthetic PII-free folders + the placeholder reference asset).

**Files:** none new (build artifacts only).

- [ ] **Step 1: Full test sweep**

```bash
npx tsc --noEmit
npx vitest run
cd server && python3 -m pytest -q ; cd ..
```

Expected: tsc exit 0 · vitest all pass · pytest all pass. Fix any failures before proceeding.

- [ ] **Step 2: Preview smoke test** the reviewer end-to-end (all three view modes, view-follows-check for value/signature/skim, ←→ paging + continuous doc-jump, D3 reference lightbox on `le-thi-mai-anh`, D3/D1 absent on the other two folders, page counter never stale).

- [ ] **Step 3: Rebuild the offline export**

```bash
npm run build:single
```

Expected: `dist-single/*.html` produced with no errors. Confirm the built file inlines `public/reference/mau-08-ck-tncn-2026.svg` and `public/folders/le-thi-mai-anh/bancamket.svg` as data URIs (grep the output for `__ASSETS__` entries or open it).

- [ ] **Step 4: Refresh the download**

```bash
cp dist-single/*.html ~/Downloads/Reviewer-v2.0.html
```

(Confirm the single-file build's output filename first; adjust the glob if the build emits a specific name.)

- [ ] **Step 5: Open the offline file** (`file://` load in the preview browser) and smoke-test the demo — the three view modes, the D3 lightbox, and view-follows-check all work with no server.

- [ ] **Step 6: Final commit** (build output is gitignored — `dist-single/` and `AP-Review-Prototype.html` are in `.gitignore`; do **not** commit `~/Downloads/*`). If any source touched in this task, commit it; otherwise nothing to commit here.

---

## Self-review checklist (run before handing off)

- [ ] **Spec coverage:** items 1 (Task 8), 2 (Task 9), 3 (Task 10), 4 (Task 3), 5 (Task 4), 6 (Task 7), 7 (Tasks 6+9), 8 (Task 1), 9 (Task 5), 10 (Tasks 2+8). C1/D1 logic intentionally **not** implemented (their rows are still routed/omitted by the item-5 rule; that's expected).
- [ ] **PII:** no real PDFs/PNGs/manifests/reports added; the only new assets are PII-free placeholders. `dist-single`/downloads not committed.
- [ ] **Vietnamese UI** preserved on every new string ("1 trang", "Cuộn liên tục", "2 trang", "Xem mẫu chuẩn — 2026", "Khu vực chữ ký & con dấu", "←→ trang").
- [ ] **Type consistency:** `ViewMode` (`'1'|'cont'|'2'`), `CheckFocus {page,bbox,caption}`, `CheckItem.focus`/`referenceAsset`, `stepPage`/`stepDoc`/`clampPage`, `viewModeForCheck`/`clampZoom` — names identical across all tasks that reference them.
- [ ] **Gates after item 4/5:** G-DOC always; D3 only with a commitment doc; B3 always (contract fallback); C2 only with a bbnt doc → 4 gates max, fewer when docs absent.
