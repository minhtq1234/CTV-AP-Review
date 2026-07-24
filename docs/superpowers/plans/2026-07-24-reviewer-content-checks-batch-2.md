# Reviewer content checks + AI recap (batch 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refine C1 into a single confirm check whose evidence is the Phụ lục (falling back to the BBNT), and add an on-demand "AI tóm tắt" (recap) popover to content-bearing docs — served by a canned source offline and a live GreenNode server endpoint (seam-ready, live call left as a TODO).

**Architecture:** The recap is exposed through **one seam**: `FolderReview`/`EvidenceViewer` take an optional `getRecap(doc) => Promise<DocRecap>` prop. The offline `DemoFlow` supplies a **canned** resolver reading a recap baked into the synthetic packet's `EvidenceDoc.recap`; the live `UploadFlow` supplies a **server-backed** resolver hitting `POST /api/cases/{cid}/packets/{i}/recap`. The server endpoint extracts **only the typed content region** of the doc (`recap.content_region_for`) and passes it to `greennode.summarize` — a second seam where the live HTTP call drops in behind a `NotConfigured` TODO. Recaps are cached (per-doc in the viewer session; in the manifest server-side). C1 routing prefers the `appendix` doc, falling back to `bbnt`. D1 is **parked** — untouched.

**Tech Stack:** React 18 + TypeScript (Vite), Vitest (node env, no RTL — logic is unit-tested, components verified via `tsc --noEmit` + the browser preview), FastAPI + pytest (server). Vietnamese UI throughout.

**Base branch:** this branch is reset onto the v2 foundation `9221d87`; batch 2 runs parallel to batch 1 and reconciles at merge.

**Hard constraints (do not break):**
- OCR/data are local, PII-bearing — never commit real PDFs/PNGs/manifests/reports/PII. Only the **typed content region** may ever leave for GreenNode (VNG's own cloud).
- After changes: `npx tsc --noEmit`, `npx vitest run`, and `pytest` in `server/` must all pass; then `npm run build:single` and refresh `~/Downloads/Reviewer-v2.0.html` — confirm the canned recap renders offline with no network.

---

## File Structure

**Frontend (create):**
- `src/logic/recap.ts` — pure recap helpers: `CONTENT_BEARING_KINDS`, `isContentBearing`, `RECAP_DISCLAIMER`.
- `src/logic/recap.test.ts` — unit tests for the above.
- `src/components/RecapPopover.tsx` — presentational popover (Tóm tắt / Nhận định / footer disclaimer / spinner / error).
- `src/ctv/demoChecklist.test.ts` — unit test for C1 appendix→bbnt routing in the offline builder.

**Frontend (modify):**
- `src/ctv/types.ts` — add `DocRecap`; add optional `recap?: DocRecap` to `EvidenceDoc`.
- `src/ctv/demoChecklist.ts` — C1 routes to `appendix` when present, else `bbnt`.
- `src/components/EvidenceViewer.tsx` — recap button (content-bearing docs only) + popover state/cache/escape.
- `src/components/FolderReview.tsx` — thread `getRecap` prop to `EvidenceViewer`.
- `src/components/DemoFlow.tsx` — canned recap resolver, wire to `FolderReview`.
- `src/ctv/folders.ts` — bake canned recaps into synthetic `contract`/`bbnt` docs (+ a Phụ lục doc on one folder, Task 10).
- `src/components/UploadFlow.tsx` — live recap resolver, wire to `FolderReview`.
- `src/upload/api.ts` — re-export `DocRecap`; add `fetchDocRecap`.
- `src/styles.css` — recap popover styles.

**Backend (create):**
- `server/recap.py` — `content_region_for(manifest, doc_id)` (pure), `CONTENT_BEARING_KINDS`, `DISCLAIMER`.
- `server/greennode.py` — `NotConfigured`, `is_configured`, `summarize` (live call = TODO).
- `server/recap_test.py` — content-region + greennode + endpoint tests.

**Backend (modify):**
- `server/checklist.py` — C1 routes to `appendix` when present, else `bbnt`.
- `server/checklist_test.py` — C1 routing tests.
- `server/app.py` — `POST /api/cases/{cid}/packets/{i}/recap` endpoint.

**Docs:** the batch-2 spec (`docs/review-ui-content-checks.md`) and batch-1 spec (`docs/review-ui-refinements.md`) are brought into the worktree in Task 0 so the branch is self-contained.

---

### Task 0: Bring the specs into the worktree

The two design docs live uncommitted in the main worktree. Copy them in so this branch is self-contained and the plan's references resolve. They are PII-free design docs — safe to commit.

**Files:**
- Create: `docs/review-ui-content-checks.md` (copy)
- Create: `docs/review-ui-refinements.md` (copy)

- [ ] **Step 1: Copy the specs from the main worktree**

```bash
cp /Users/lap16603/Desktop/ap-review-prototype/docs/review-ui-content-checks.md docs/review-ui-content-checks.md
cp /Users/lap16603/Desktop/ap-review-prototype/docs/review-ui-refinements.md docs/review-ui-refinements.md
```

- [ ] **Step 2: Verify they are present**

Run: `ls docs/review-ui-*.md`
Expected: both files listed.

- [ ] **Step 3: Commit**

```bash
git add docs/review-ui-content-checks.md docs/review-ui-refinements.md docs/superpowers/plans/2026-07-24-reviewer-content-checks-batch-2.md
git commit -m "docs: batch-2 spec (content checks + AI recap) + implementation plan"
```

---

### Task 1: Recap types + pure logic (frontend)

**Files:**
- Modify: `src/ctv/types.ts`
- Create: `src/logic/recap.ts`
- Test: `src/logic/recap.test.ts`

- [ ] **Step 1: Write the failing test**

Create `src/logic/recap.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { isContentBearing, CONTENT_BEARING_KINDS, RECAP_DISCLAIMER } from './recap'

describe('isContentBearing', () => {
  it('is true for docs whose typed body carries reviewable content', () => {
    for (const k of ['contract', 'bbnt', 'appendix', 'commitment'] as const) {
      expect(isContentBearing(k)).toBe(true)
    }
  })
  it('is false for id scans and the PIT lookup (nothing to read fast)', () => {
    for (const k of ['id_front', 'id_back', 'pit'] as const) {
      expect(isContentBearing(k)).toBe(false)
    }
  })
  it('CONTENT_BEARING_KINDS is exactly the four content docs', () => {
    expect([...CONTENT_BEARING_KINDS].sort()).toEqual(['appendix', 'bbnt', 'commitment', 'contract'])
  })
})

describe('RECAP_DISCLAIMER', () => {
  it('frames the recap as assist, never verdict', () => {
    expect(RECAP_DISCLAIMER).toContain('Bản xem thử')
    expect(RECAP_DISCLAIMER).toContain('quyết định cuối cùng do bạn')
  })
})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npx vitest run src/logic/recap.test.ts`
Expected: FAIL — cannot resolve `./recap`.

- [ ] **Step 3: Add `DocRecap` + `EvidenceDoc.recap` to `src/ctv/types.ts`**

After the `EvidenceKind` type (line 7), add:

```ts
// AI recap of a content-bearing doc (Tóm tắt + Nhận định + footer disclaimer). An
// assist, never a verdict — displaying it never marks or flags a check.
export interface DocRecap {
  bullets: string[]   // Tóm tắt — 2–3 plain bullets
  nhanDinh: string    // Nhận định — a tentative conclusion
  disclaimer: string  // footer disclaimer
}
```

In `interface EvidenceDoc`, add a `recap` field (after `pages`):

```ts
export interface EvidenceDoc {
  id: string
  kind: EvidenceKind
  label: string
  pages: DocPage[]
  recap?: DocRecap   // canned recap baked into synthetic demo packets (offline export)
}
```

- [ ] **Step 4: Create `src/logic/recap.ts`**

```ts
import type { EvidenceKind } from '../ctv/types'

// Docs whose typed body carries reviewable content — the ones the "AI tóm tắt"
// affordance is offered on. C1 is just the first place a reviewer reaches for it;
// identity scans (CCCD) and the PIT lookup are excluded (nothing to read fast).
export const CONTENT_BEARING_KINDS: readonly EvidenceKind[] = ['contract', 'bbnt', 'appendix', 'commitment']

export function isContentBearing(kind: EvidenceKind): boolean {
  return CONTENT_BEARING_KINDS.includes(kind)
}

// Shown at the foot of every recap popover. Keep in sync with server/recap.py's DISCLAIMER.
export const RECAP_DISCLAIMER =
  'Bản xem thử. AI hỗ trợ đọc nhanh hồ sơ dài/phức tạp — quyết định cuối cùng do bạn.'
```

- [ ] **Step 5: Run test to verify it passes**

Run: `npx vitest run src/logic/recap.test.ts`
Expected: PASS (5 assertions across 4 tests).

- [ ] **Step 6: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 7: Commit**

```bash
git add src/ctv/types.ts src/logic/recap.ts src/logic/recap.test.ts
git commit -m "feat(recap): DocRecap type + content-bearing helpers + disclaimer"
```

---

### Task 2: C1 routing — prefer Phụ lục, fall back to BBNT

C1 stays a **single confirm detail check**. Its evidence is the `appendix` (Phụ lục) when the packet has one, else the `bbnt`. Applies to both the backend builder and the offline builder. D1 is untouched.

**Files:**
- Modify: `server/checklist.py:79-82`
- Test: `server/checklist_test.py`
- Modify: `src/ctv/demoChecklist.ts:74-79`
- Test: `src/ctv/demoChecklist.test.ts` (create)

- [ ] **Step 1: Write the failing backend test**

Add to `server/checklist_test.py` (end of file):

```python
DOCS_WITH_APPENDIX = [
    {"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ"},
    {"id": "bbnt", "kind": "bbnt", "label": "Biên bản nghiệm thu"},
    {"id": "pluc", "kind": "appendix", "label": "Phụ lục"},
]

def test_c1_routes_to_appendix_when_present():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS_WITH_APPENDIX))
    assert c["C1"]["evidenceDocId"] == "pluc"
    assert c["C1"]["kind"] == "confirm" and c["C1"]["tier"] == "detail"

def test_c1_falls_back_to_bbnt_when_no_appendix():
    c = _by_code(build_checklist(FIELDS, MATCH, DOCS))
    assert c["C1"]["evidenceDocId"] == "bbnt"
```

- [ ] **Step 2: Run backend test to verify it fails**

Run: `cd server && python3 -m pytest checklist_test.py::test_c1_routes_to_appendix_when_present -q`
Expected: FAIL — `evidenceDocId == "bbnt"`, not `"pluc"`.

- [ ] **Step 3: Implement C1 routing in `server/checklist.py`**

Replace the `_CONFIRM_DETAIL` loop (lines 79-82):

```python
    for code, label, kind_doc in _CONFIRM_DETAIL:
        doc_id = _doc_by_kind(docs, kind_doc)
        if code == "C1":
            # Content lives in the Phụ lục (typed SOW/KPI/Actual) when present;
            # fall back to the BBNT body otherwise. One check either way (no split).
            doc_id = _doc_by_kind(docs, "appendix") or doc_id
        checks.append({"code": code, "label": label, "tier": "detail", "kind": "confirm",
                       "evidenceDocId": doc_id,
                       "reference": None, "source": None, "autostatus": None})
    return checks
```

- [ ] **Step 4: Run backend tests to verify they pass**

Run: `cd server && python3 -m pytest checklist_test.py -q`
Expected: PASS (all existing + 2 new).

- [ ] **Step 5: Write the failing frontend test**

Create `src/ctv/demoChecklist.test.ts`:

```ts
import { describe, it, expect } from 'vitest'
import { demoChecklist } from './demoChecklist'
import type { CtvFolder, EvidenceDoc } from './types'

const baseDoc = (id: string, kind: EvidenceDoc['kind']): EvidenceDoc =>
  ({ id, kind, label: id, pages: [{ src: `/x/${id}.svg`, width: 10, height: 10 }] })

const folder = (docs: EvidenceDoc[]): CtvFolder => ({
  id: 'f', name: 'N', product: 'P', status: 'pending', exempt: false,
  docs, fields: [],
})

const byCode = (folderArg: CtvFolder) =>
  Object.fromEntries(demoChecklist(folderArg).map(c => [c.code, c]))

describe('demoChecklist C1 routing', () => {
  it('routes C1 to the appendix (Phụ lục) when present', () => {
    const c = byCode(folder([baseDoc('contract', 'contract'), baseDoc('bbnt', 'bbnt'), baseDoc('pluc', 'appendix')]))
    expect(c['C1'].evidenceDocId).toBe('pluc')
    expect(c['C1'].kind).toBe('confirm')
  })
  it('falls back to the bbnt when there is no appendix', () => {
    const c = byCode(folder([baseDoc('contract', 'contract'), baseDoc('bbnt', 'bbnt')]))
    expect(c['C1'].evidenceDocId).toBe('bbnt')
  })
})
```

- [ ] **Step 6: Run frontend test to verify it fails**

Run: `npx vitest run src/ctv/demoChecklist.test.ts`
Expected: FAIL — C1 routes to `bbnt` even when an appendix is present.

- [ ] **Step 7: Implement C1 routing in `src/ctv/demoChecklist.ts`**

Replace the C1 push (lines 75-76) inside the final `checks.push(...)`:

```ts
  checks.push(
    { code: 'C1', label: 'Nội dung & thời gian khớp BBNT', tier: 'detail', kind: 'confirm',
      // Content lives in the Phụ lục when present, else the BBNT body. Single check.
      evidenceDocId: docByKind(folder, 'appendix') ?? docByKind(folder, 'bbnt'),
      reference: null, source: null, autostatus: null },
    { code: 'D1', label: 'Thông tin & MST khớp cam kết', tier: 'detail', kind: 'confirm',
      evidenceDocId: docByKind(folder, 'commitment'), reference: null, source: null, autostatus: null },
  )
```

- [ ] **Step 8: Run frontend test + typecheck**

Run: `npx vitest run src/ctv/demoChecklist.test.ts && npx tsc --noEmit`
Expected: PASS, no type errors.

- [ ] **Step 9: Commit**

```bash
git add server/checklist.py server/checklist_test.py src/ctv/demoChecklist.ts src/ctv/demoChecklist.test.ts
git commit -m "feat(c1): route C1 evidence to Phụ lục when present, else BBNT"
```

---

### Task 3: RecapPopover component + styles

Presentational only — no data fetching, no review-state mutation. Verified via `tsc` + the browser preview (repo has no RTL/component-test harness).

**Files:**
- Create: `src/components/RecapPopover.tsx`
- Modify: `src/styles.css` (append recap styles)

- [ ] **Step 1: Create `src/components/RecapPopover.tsx`**

```tsx
import type { DocRecap } from '../ctv/types'

interface Props {
  loading: boolean
  error: string | null
  recap: DocRecap | null
  docLabel: string
  onClose: () => void
}

// The AI-recap popover: Tóm tắt (bullets) + Nhận định (tentative conclusion) + a
// footer disclaimer. Pure display — it never marks or flags a check.
export default function RecapPopover({ loading, error, recap, docLabel, onClose }: Props) {
  const ready = !!recap && !loading && !error
  return (
    <div className="recap-pop" role="dialog" aria-label="AI tóm tắt tài liệu">
      <div className="recap-pop-head">
        <span className="recap-pop-title">✨ AI tóm tắt — {docLabel}</span>
        <button className="recap-pop-x" onClick={onClose} aria-label="Đóng">×</button>
      </div>
      <div className="recap-pop-body">
        {loading && <div className="recap-loading">Đang đọc tài liệu…</div>}
        {error && !loading && <div className="recap-error">{error}</div>}
        {ready && (
          <>
            <div className="recap-sec-h">Tóm tắt</div>
            <ul className="recap-bullets">
              {recap!.bullets.map((b, i) => <li key={i}>{b}</li>)}
            </ul>
            <div className="recap-sec-h">Nhận định</div>
            <p className="recap-nhandinh">{recap!.nhanDinh}</p>
          </>
        )}
      </div>
      {ready && <div className="recap-pop-foot">{recap!.disclaimer}</div>}
    </div>
  )
}
```

- [ ] **Step 2: Append recap styles to `src/styles.css`**

Append at the end of the file:

```css
/* AI recap popover — overlays the scan pane's top-right, below the toolbar. */
.recap-pop {
  position: absolute; top: 8px; right: 8px; z-index: 20;
  width: min(360px, calc(100% - 16px)); max-height: calc(100% - 16px);
  display: flex; flex-direction: column;
  background: var(--panel, #fff); color: var(--ink, #1a1a1a);
  border: 1px solid var(--line, #d9d9d9); border-radius: 10px;
  box-shadow: 0 8px 28px rgba(0, 0, 0, 0.18);
  font-size: 13px;
}
.recap-pop-head {
  display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 10px 12px; border-bottom: 1px solid var(--line, #eee);
}
.recap-pop-title { font-weight: 600; }
.recap-pop-x {
  border: none; background: none; cursor: pointer; font-size: 18px; line-height: 1;
  padding: 0 4px; color: var(--muted, #888);
}
.recap-pop-x:hover { color: var(--ink, #1a1a1a); }
.recap-pop-body { padding: 10px 12px; overflow-y: auto; }
.recap-sec-h { font-weight: 600; margin: 6px 0 4px; color: var(--muted, #666); text-transform: uppercase; letter-spacing: .03em; font-size: 11px; }
.recap-bullets { margin: 0 0 6px; padding-left: 18px; }
.recap-bullets li { margin: 3px 0; }
.recap-nhandinh { margin: 0; }
.recap-loading { color: var(--muted, #888); font-style: italic; }
.recap-error { color: var(--danger, #b23); }
.recap-pop-foot {
  padding: 8px 12px; border-top: 1px solid var(--line, #eee);
  color: var(--muted, #888); font-size: 11px; font-style: italic;
}
```

Note: use the same CSS-variable names already used elsewhere in `src/styles.css`; if a variable is absent the fallback after the comma applies. Check the top of `styles.css` for the actual variable names and match them.

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add src/components/RecapPopover.tsx src/styles.css
git commit -m "feat(recap): RecapPopover component + styles"
```

---

### Task 4: EvidenceViewer — recap button + popover wiring

Add the "AI tóm tắt" button to the doc-tools toolbar (only for content-bearing docs), open the popover on demand, cache per doc, and close it on doc change / Escape.

**Files:**
- Modify: `src/components/EvidenceViewer.tsx`

- [ ] **Step 1: Add imports + the `getRecap` prop**

At the top of `src/components/EvidenceViewer.tsx`, add imports:

```ts
import type { Bbox, Frame } from '../types'
import type { DocRecap, EvidenceDoc } from '../ctv/types'
import { isContentBearing } from '../logic/recap'
import RecapPopover from './RecapPopover'
```

(Keep the other existing imports.) Extend the `Props` interface with:

```ts
  getRecap?: (doc: EvidenceDoc) => Promise<DocRecap>  // seam: canned (offline) or server (live)
```

Add `getRecap` to the destructured params in the component signature.

- [ ] **Step 2: Add recap state + handlers**

After the existing `useState` declarations (near line 33), add:

```ts
  const [recapOpen, setRecapOpen] = useState(false)
  const [recapLoading, setRecapLoading] = useState(false)
  const [recapError, setRecapError] = useState<string | null>(null)
  const [recapCache, setRecapCache] = useState<Record<string, DocRecap>>({})
```

After `doc`/`page` are derived (near line 35), add the open handler:

```ts
  const openRecap = useCallback(async () => {
    setRecapOpen(true); setRecapError(null)
    if (recapCache[doc.id] || !getRecap) return  // cached → instant; no resolver → nothing to fetch
    setRecapLoading(true)
    try {
      const r = await getRecap(doc)
      setRecapCache(m => ({ ...m, [doc.id]: r }))
    } catch (e) {
      setRecapError(e instanceof Error ? e.message : 'Không tạo được bản tóm tắt.')
    } finally {
      setRecapLoading(false)
    }
  }, [doc, getRecap, recapCache])
```

- [ ] **Step 3: Close the popover on doc change and on Escape**

Add two effects (after the other `useEffect`s, before `const fit`):

```ts
  // Close the recap when the active document changes — a recap is per-doc.
  useEffect(() => { setRecapOpen(false); setRecapError(null); setRecapLoading(false) }, [activeDocId])

  // Escape closes the recap while it's open.
  useEffect(() => {
    if (!recapOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setRecapOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [recapOpen])
```

- [ ] **Step 4: Add the toolbar button**

In the `.doc-tools` block, add as the last button (after the `?` help button, ~line 222):

```tsx
          {getRecap && isContentBearing(doc.kind) && (
            <button className={recapOpen ? 'on' : ''} onClick={openRecap}
              aria-label="AI tóm tắt tài liệu" title="AI tóm tắt tài liệu">✨</button>
          )}
```

- [ ] **Step 5: Render the popover over the stage**

Inside `.ev-stage`, after the `.doc-tools` closing `</div>` (~line 223) and before `.ev-stage`'s closing `</div>`, add:

```tsx
        {recapOpen && (
          <RecapPopover loading={recapLoading} error={recapError}
            recap={recapCache[doc.id] ?? null} docLabel={doc.label}
            onClose={() => setRecapOpen(false)} />
        )}
```

- [ ] **Step 6: Typecheck + full existing test suite**

Run: `npx tsc --noEmit && npx vitest run`
Expected: no type errors; all existing tests still pass (35+ from earlier tasks).

- [ ] **Step 7: Commit**

```bash
git add src/components/EvidenceViewer.tsx
git commit -m "feat(recap): AI tóm tắt button + popover in the doc pane"
```

---

### Task 5: FolderReview — thread the `getRecap` seam

**Files:**
- Modify: `src/components/FolderReview.tsx`

- [ ] **Step 1: Add the prop + imports**

In `src/components/FolderReview.tsx`, add to the type imports:

```ts
import type { CtvFolder, DocRecap, EvidenceDoc } from '../ctv/types'
```

Extend `interface Props` with:

```ts
  getRecap?: (doc: EvidenceDoc) => Promise<DocRecap>
```

Add `getRecap` to the destructured props of `FolderReview`.

- [ ] **Step 2: Pass it to EvidenceViewer**

In the `<EvidenceViewer ... />` element (line 99-105), add the prop:

```tsx
        <EvidenceViewer docs={folder.docs} activeDocId={activeDocId} activePage={activePage}
          focusBbox={focusBbox} lockView={lockView} getRecap={getRecap}
          onSelectDoc={id => { setActiveDocId(id); setFocusBbox(null) }}
          onSelectPage={p => { setActivePage(p); setFocusBbox(null) }}
          onToggleLock={() => setLockView(v => !v)}
          rosterLabel={sel?.label}
          rosterValue={sel?.kind === 'value' ? sel.reference : null} />
```

- [ ] **Step 3: Typecheck**

Run: `npx tsc --noEmit`
Expected: no errors (prop is optional; existing callers unaffected).

- [ ] **Step 4: Commit**

```bash
git add src/components/FolderReview.tsx
git commit -m "feat(recap): thread getRecap seam through FolderReview"
```

---

### Task 6: Offline canned recap — folders.ts + DemoFlow

Bake plausible Vietnamese recaps into the synthetic `contract` and `bbnt` docs, and wire `DemoFlow` to resolve them with a short spinner delay (no network). This makes the offline export always demo the feature, PII-free.

**Files:**
- Modify: `src/ctv/folders.ts`
- Modify: `src/components/DemoFlow.tsx`

- [ ] **Step 1: Add recap helpers + attach to docs in `src/ctv/folders.ts`**

Update the imports at the top:

```ts
import type { DocRecap, EvidenceDoc, CtvFolder } from './types'
import { RECAP_DISCLAIMER } from '../logic/recap'
```

Add recap builders above `docsFor`:

```ts
const contractRecap = (product: string): DocRecap => ({
  bullets: [
    `Hợp đồng cung ứng dịch vụ CTV cho sản phẩm ${product}.`,
    'Phạm vi: cung ứng dịch vụ theo thoả thuận; phí chi trả một lần.',
    'Trang cuối có mục chữ ký & con dấu của hai bên.',
  ],
  nhanDinh: 'Nội dung hợp đồng phù hợp phạm vi CTV; chưa thấy mâu thuẫn với bảng kê.',
  disclaimer: RECAP_DISCLAIMER,
})
const bbntRecap = (product: string): DocRecap => ({
  bullets: [
    `Biên bản nghiệm thu dịch vụ ${product}.`,
    'Xác nhận đã hoàn thành khối lượng công việc trong kỳ.',
    'Thời gian nghiệm thu nằm trong kỳ thanh toán.',
  ],
  nhanDinh: 'Nội dung & thời gian khớp BBNT; không thấy mâu thuẫn — có thể xác nhận C1.',
  disclaimer: RECAP_DISCLAIMER,
})
```

Change `docsFor` to accept per-doc recaps:

```ts
type FolderRecaps = { contract?: DocRecap; bbnt?: DocRecap }
const docsFor = (id: string, recaps: FolderRecaps = {}): EvidenceDoc[] => [
  { id: 'id_front', kind: 'id_front', label: 'CCCD mặt trước', pages: [{ src: `/folders/${id}/cccd-front.svg`, ...CARD }] },
  { id: 'id_back', kind: 'id_back', label: 'CCCD mặt sau', pages: [{ src: `/folders/${id}/cccd-back.svg`, ...CARD }] },
  { id: 'contract', kind: 'contract', label: 'Hợp đồng (5 trang)', recap: recaps.contract, pages: [
    { src: `/folders/${id}/contract.svg`, ...A4 },
    { src: '/folders/_shared/contract-2.svg', ...A4 },
    { src: '/folders/_shared/contract-3.svg', ...A4 },
    { src: '/folders/_shared/contract-4.svg', ...A4 },
    { src: `/folders/${id}/contract-5.svg`, ...A4 },
  ] },
  { id: 'pit', kind: 'pit', label: 'Tờ khai PIT', pages: [{ src: `/folders/${id}/pit.svg`, ...A4 }] },
  { id: 'bbnt', kind: 'bbnt', label: 'Biên bản nghiệm thu', recap: recaps.bbnt, pages: [{ src: `/folders/${id}/bbnt.svg`, ...A4 }] },
]
```

For **each** of the three folders in the `folders` array, pass recaps to `docsFor`. The products are: `le-thi-mai-anh` → `'Crossfire: Legends'`, `pham-quoc-hung` → its own product, `tran-minh-khoa` → its own product. Update each `docs:` line, e.g. for the first:

```ts
    docs: docsFor('le-thi-mai-anh', { contract: contractRecap('Crossfire: Legends'), bbnt: bbntRecap('Crossfire: Legends') }),
```

Do the same for the other two, using **that folder's own `product` string** (read it from the folder literal directly below the `docs:` line and reuse the exact same string).

- [ ] **Step 2: Wire the canned resolver in `src/components/DemoFlow.tsx`**

Add imports:

```ts
import type { CtvFolder, DocRecap, EvidenceDoc } from '../ctv/types'
import { RECAP_DISCLAIMER } from '../logic/recap'
```

(Merge the `DocRecap, EvidenceDoc` into the existing `CtvFolder` type import line.)

Inside `DemoFlow`, before the `return`, add the resolver:

```ts
  // Canned recap: read the recap baked into the synthetic doc, behind a short delay
  // so the popover shows its spinner. No network, PII-free — this is what the offline
  // export demonstrates. Live GreenNode drops in behind the same getRecap seam (UploadFlow).
  const cannedRecap = (doc: EvidenceDoc): Promise<DocRecap> =>
    new Promise(resolve => setTimeout(() => resolve(doc.recap ?? {
      bullets: ['Chưa có bản tóm tắt mẫu cho tài liệu này.'],
      nhanDinh: 'Không có nhận định.',
      disclaimer: RECAP_DISCLAIMER,
    }), 500))
```

Pass it to `FolderReview` (in the JSX around line 80-88):

```tsx
      <FolderReview
        key={folder.id}
        folder={{ ...folder, checks: demoChecklist(folder) }}
        review={reviewFor(folder.id)}
        matchedBy="cccd"
        ocrIdentity={identityOf(folder)}
        rosterIdentity={identityOf(folder)}
        getRecap={cannedRecap}
        onReview={r => setReviews(m => ({ ...m, [folder.id]: r }))}
      />
```

- [ ] **Step 3: Typecheck + tests**

Run: `npx tsc --noEmit && npx vitest run`
Expected: no type errors; all tests pass.

- [ ] **Step 4: Verify in the browser preview (dev server)**

Start the dev server via the preview tool (`.claude/launch.json` name `dev`, or create it: runtimeExecutable `npm`, runtimeArgs `["run","dev"]`, port `5173`). Open the offline demo (App renders `DemoFlow` when `window.__ASSETS__` is present — in dev it renders the live `UploadFlow`; to see the canned demo in dev, temporarily open `DemoFlow` OR just verify against the built single-file in Task 11). For this task, at minimum confirm the dev server compiles with no console errors after the change (read_console_messages).

- [ ] **Step 5: Commit**

```bash
git add src/ctv/folders.ts src/components/DemoFlow.tsx
git commit -m "feat(recap): canned recaps in synthetic packets + DemoFlow resolver"
```

---

### Task 7: Server recap seam — content region + GreenNode client

Pure content-region extraction (only the typed content of one doc) and the GreenNode client seam (live call = TODO, raises `NotConfigured`).

**Files:**
- Create: `server/recap.py`
- Create: `server/greennode.py`
- Test: `server/recap_test.py` (create; endpoint tests added in Task 8)

- [ ] **Step 1: Write the failing test**

Create `server/recap_test.py`:

```python
import pytest

import recap
import greennode

MANIFEST = {
    "id": "p0",
    "docs": [
        {"id": "contract", "kind": "contract", "label": "Hợp đồng dịch vụ", "pages": []},
        {"id": "bbnt", "kind": "bbnt", "label": "Biên bản nghiệm thu", "pages": []},
        {"id": "idf", "kind": "id_front", "label": "CCCD", "pages": []},
    ],
    "fields": [
        {"label": "Phí dịch vụ", "sources": [{"docId": "contract", "value": "10.000.000", "page": 0}]},
        {"label": "Họ tên", "sources": [{"docId": "bbnt", "value": "Nguyễn Văn A", "page": 0}]},
    ],
}


def test_content_region_is_only_that_docs_typed_content():
    r = recap.content_region_for(MANIFEST, "contract")
    assert "Hợp đồng dịch vụ" in r
    assert "Phí dịch vụ: 10.000.000" in r
    assert "Nguyễn Văn A" not in r  # the bbnt field must not leak into the contract region


def test_content_region_none_for_non_content_bearing():
    assert recap.content_region_for(MANIFEST, "idf") is None


def test_content_region_none_for_unknown_doc():
    assert recap.content_region_for(MANIFEST, "nope") is None


def test_disclaimer_frames_as_assist():
    assert "Bản xem thử" in recap.DISCLAIMER
    assert "quyết định cuối cùng do bạn" in recap.DISCLAIMER


def test_greennode_unconfigured_by_default(monkeypatch):
    monkeypatch.delenv("GREENNODE_API_URL", raising=False)
    monkeypatch.delenv("GREENNODE_API_KEY", raising=False)
    assert greennode.is_configured() is False
    with pytest.raises(greennode.NotConfigured):
        greennode.summarize("bất kỳ nội dung nào")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && python3 -m pytest recap_test.py -q`
Expected: FAIL — `import recap` / `import greennode` not found.

- [ ] **Step 3: Create `server/recap.py`**

```python
"""Assemble the *typed content region* of one document for the AI recap — the ONLY
text ever sent to GreenNode (VNG's own cloud). No images, no packet-wide PII: just
the typed content located on that one document. Pure + unit-tested."""
from __future__ import annotations

# Docs whose typed body carries reviewable content (mirrors src/logic/recap.ts).
CONTENT_BEARING_KINDS = ("contract", "bbnt", "appendix", "commitment")

# Shown at the foot of every recap. Keep in sync with src/logic/recap.ts's RECAP_DISCLAIMER.
DISCLAIMER = (
    "Bản xem thử. AI hỗ trợ đọc nhanh hồ sơ dài/phức tạp — "
    "quyết định cuối cùng do bạn."
)


def content_region_for(manifest: dict, doc_id: str) -> str | None:
    """The typed content of one document as a plain-text block, or None when the
    doc is absent or not content-bearing.

    Today that's the doc's title plus the typed field values OCR located ON that
    doc (nothing from any other doc). TODO(greennode): when the Phụ lục / BBNT body
    text is persisted per-doc during OCR, include it here — this stays the sole
    payload sent to GreenNode."""
    doc = next((d for d in manifest.get("docs", []) if d.get("id") == doc_id), None)
    if doc is None or doc.get("kind") not in CONTENT_BEARING_KINDS:
        return None
    lines: list[str] = []
    title = (doc.get("label") or doc.get("kind") or "").strip()
    if title:
        lines.append(title)
    for field in manifest.get("fields", []):
        for src in field.get("sources", []):
            if src.get("docId") == doc_id and (src.get("value") or "").strip():
                label = (field.get("label") or "").strip()
                lines.append(f"{label}: {src['value'].strip()}")
                break
    text = "\n".join(line for line in lines if line).strip()
    return text or None
```

- [ ] **Step 4: Create `server/greennode.py`**

```python
"""Seam for the GreenNode (VNG cloud) summariser. The recap endpoint calls
summarize() with ONLY the typed content region (see recap.content_region_for);
this module is the single place the live HTTP call drops in.

Until creds are wired (or the live call is implemented) summarize() raises
NotConfigured, which the endpoint surfaces as HTTP 503. The offline export never
reaches this path — it uses the canned recap baked into the synthetic packets."""
from __future__ import annotations

import os


class NotConfigured(Exception):
    """GreenNode isn't wired (no creds) or the live call isn't implemented yet."""


def is_configured() -> bool:
    return bool(os.environ.get("GREENNODE_API_URL") and os.environ.get("GREENNODE_API_KEY"))


def summarize(content: str) -> dict:
    """Summarise the typed content region into {"bullets": [...], "nhanDinh": "..."}.

    Raises NotConfigured until the live call is wired."""
    if not is_configured():
        raise NotConfigured(
            "GreenNode chưa cấu hình (đặt GREENNODE_API_URL + GREENNODE_API_KEY)."
        )
    # TODO(greennode): POST `content` to os.environ["GREENNODE_API_URL"] with a
    # Bearer os.environ["GREENNODE_API_KEY"] header, instructing the model to return
    # Vietnamese JSON {"bullets": [<2-3 strings>], "nhanDinh": "<one line>"} for a
    # payment-document recap; parse and return it. `content` (the typed content
    # region) is the ONLY thing sent — never the image or any other packet data.
    raise NotConfigured("GreenNode: lời gọi trực tiếp chưa được nối (TODO).")
```

- [ ] **Step 5: Run test to verify it passes**

Run: `cd server && python3 -m pytest recap_test.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add server/recap.py server/greennode.py server/recap_test.py
git commit -m "feat(recap): server content-region extractor + GreenNode client seam"
```

---

### Task 8: Server endpoint — POST /recap

Add the recap endpoint: load manifest → serve cached recap if present → extract typed region → `greennode.summarize` (503 on `NotConfigured`) → cache in manifest → return `{bullets, nhanDinh, disclaimer}`.

**Files:**
- Modify: `server/app.py`
- Test: `server/recap_test.py` (add endpoint tests)

- [ ] **Step 1: Write the failing endpoint tests**

Append to `server/recap_test.py`:

```python
import json
import os

from fastapi.testclient import TestClient
import app as appmod
from app import app


def _case_with_manifest(monkeypatch, tmp_path, manifest):
    monkeypatch.setattr(appmod, "store", appmod.CaseStore(str(tmp_path)))
    cid = appmod.store.create(name="c", pdf_name="c.pdf", roster_name=None,
                              now="2026-01-01T00:00:00Z")
    appmod.store.set_result(cid, summary=None, packets=[
        {"index": 0, "name": "P0", "pages": [0, 1],
         "confidence": "green", "flags": [], "labels": []}])
    d = os.path.join(appmod.store.case_dir(cid), "packets", "0")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False)
    return TestClient(app), cid


def test_recap_503_when_greennode_unconfigured(tmp_path, monkeypatch):
    monkeypatch.delenv("GREENNODE_API_URL", raising=False)
    monkeypatch.delenv("GREENNODE_API_KEY", raising=False)
    c, cid = _case_with_manifest(monkeypatch, tmp_path, MANIFEST)
    r = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "contract"})
    assert r.status_code == 503


def test_recap_returns_and_caches_when_wired(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fake_summarize(content):
        calls["n"] += 1
        assert "Hợp đồng dịch vụ" in content       # only the typed region reaches GreenNode
        assert "Nguyễn Văn A" not in content       # no other doc's data leaks
        return {"bullets": ["a", "b"], "nhanDinh": "ổn"}

    monkeypatch.setattr(appmod.greennode, "summarize", fake_summarize)
    c, cid = _case_with_manifest(monkeypatch, tmp_path, MANIFEST)
    r = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "contract"})
    assert r.status_code == 200
    body = r.json()
    assert body["bullets"] == ["a", "b"] and body["nhanDinh"] == "ổn"
    assert "quyết định cuối cùng do bạn" in body["disclaimer"]
    # cached: a second call returns the same recap without re-summarising
    r2 = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "contract"})
    assert r2.status_code == 200 and r2.json()["bullets"] == ["a", "b"]
    assert calls["n"] == 1


def test_recap_404_for_non_content_bearing_doc(tmp_path, monkeypatch):
    monkeypatch.setattr(appmod.greennode, "summarize",
                        lambda content: {"bullets": [], "nhanDinh": ""})
    c, cid = _case_with_manifest(monkeypatch, tmp_path, MANIFEST)
    r = c.post(f"/api/cases/{cid}/packets/0/recap", json={"docId": "idf"})
    assert r.status_code == 404


def test_recap_404_for_unknown_case(monkeypatch):
    monkeypatch.setattr(appmod.greennode, "summarize",
                        lambda content: {"bullets": [], "nhanDinh": ""})
    r = TestClient(app).post("/api/cases/nope/packets/0/recap", json={"docId": "contract"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && python3 -m pytest recap_test.py -q`
Expected: FAIL — endpoint 404 (route not defined) / `appmod.greennode` attribute missing.

- [ ] **Step 3: Wire the endpoint in `server/app.py`**

Add to the imports (near line 27, with `import checklist`):

```python
import checklist
import greennode
import recap
```

Add the endpoint (place after `put_review`, before `_load_manifests` — around line 141):

```python
class RecapBody(BaseModel):
    docId: str


@app.post("/api/cases/{cid}/packets/{i}/recap")
async def post_recap(cid: str, i: int, body: RecapBody):
    """AI recap of one content-bearing doc. Sends ONLY that doc's typed content
    region to GreenNode (see recap.content_region_for); caches the result in the
    manifest so repeat views are instant. 503 when GreenNode isn't wired — the
    offline export uses the canned recap instead."""
    case = store.get(cid)
    if case is None:
        raise HTTPException(status_code=404, detail="case not found")
    path = os.path.join(store.case_dir(cid), "packets", str(i), "manifest.json")
    if not os.path.isfile(path):
        raise HTTPException(status_code=404, detail="manifest not found")
    with open(path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    cached = (manifest.get("recaps") or {}).get(body.docId)
    if cached:
        return cached

    region = recap.content_region_for(manifest, body.docId)
    if region is None:
        raise HTTPException(status_code=404, detail="no typed content region for this doc")

    try:
        out = greennode.summarize(region)  # ONLY the typed content region is sent
    except greennode.NotConfigured as e:
        raise HTTPException(status_code=503, detail=str(e))

    result = {"bullets": out.get("bullets", []),
              "nhanDinh": out.get("nhanDinh", ""),
              "disclaimer": recap.DISCLAIMER}
    manifest.setdefault("recaps", {})[body.docId] = result
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    return result
```

- [ ] **Step 4: Run the full server suite**

Run: `cd server && python3 -m pytest -q`
Expected: PASS (101 existing + new recap tests).

- [ ] **Step 5: Commit**

```bash
git add server/app.py server/recap_test.py
git commit -m "feat(recap): POST /recap endpoint — typed region → GreenNode, cached"
```

---

### Task 9: Live wiring — api client + UploadFlow

**Files:**
- Modify: `src/upload/api.ts`
- Modify: `src/components/UploadFlow.tsx`

- [ ] **Step 1: Add `fetchDocRecap` to `src/upload/api.ts`**

Extend the re-export line (line 7) to include `DocRecap`:

```ts
export type { CheckItem, CheckTier, CheckKind, CheckAutoStatus, DocRecap } from '../ctv/types'
```

Add near `fetchPacketManifest` (end of file):

```ts
// POST the doc id; the server sends only that doc's typed content region to GreenNode
// and returns the recap (or 503 when GreenNode isn't wired — surfaced as the popover error).
export async function fetchDocRecap(caseId: string, index: number, docId: string): Promise<DocRecap> {
  const res = await fetch(`${API_BASE}/api/cases/${caseId}/packets/${index}/recap`, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify({ docId }),
  })
  if (!res.ok) {
    let detail = ''
    try { detail = (await res.json())?.detail ?? '' } catch { /* non-JSON body */ }
    throw new Error(detail || `Không tạo được bản tóm tắt (HTTP ${res.status}).`)
  }
  return res.json()
}
```

You must add a `DocRecap` type import for the function signature. Add to the top import block:

```ts
import type { CtvFolder, DocRecap } from '../ctv/types'
```

(Replace the existing `import type { CtvFolder } from '../ctv/types'` line.)

- [ ] **Step 2: Wire the live resolver in `src/components/UploadFlow.tsx`**

Add `fetchDocRecap` to the api import (line 3):

```ts
import { listCases, getCase, createCase, setReview, deleteCase, fetchPacketManifest, fetchDocRecap } from '../upload/api'
```

In the `screen === 'review'` branch, pass `getRecap` to `<FolderReview>` (around line 197). `caseId` and `packetIndex` are in scope and non-null here (guarded by `screen === 'review' && folder`), but assert for the type:

```tsx
        <FolderReview
          key={packetIndex ?? folder.id}
          folder={folder}
          review={review}
          matchedBy={meta?.matchedBy ?? 'no-roster'}
          ocrIdentity={meta?.ocrIdentity ?? { cccd: '', name: '' }}
          rosterIdentity={meta?.rosterIdentity ?? null}
          getRecap={caseId && packetIndex != null
            ? doc => fetchDocRecap(caseId, packetIndex, doc.id)
            : undefined}
          onReview={r => { setReviewState(r); flushReview(r) }}
        />
```

- [ ] **Step 3: Typecheck + tests**

Run: `npx tsc --noEmit && npx vitest run`
Expected: no type errors; all tests pass.

- [ ] **Step 4: Commit**

```bash
git add src/upload/api.ts src/components/UploadFlow.tsx
git commit -m "feat(recap): live server-backed recap resolver in UploadFlow"
```

---

### Task 10: Showcase the Phụ lục path offline (C1 → appendix)

Add a synthetic Phụ lục (appendix) doc to one demo folder so the offline export actually shows C1 opening the Phụ lục with an AI recap on it. Synthetic, PII-free.

**Files:**
- Create: `public/folders/le-thi-mai-anh/appendix.svg`
- Modify: `src/ctv/folders.ts`

- [ ] **Step 1: Create the synthetic Phụ lục SVG**

Create `public/folders/le-thi-mai-anh/appendix.svg` — a simple typed SOW/KPI/period table (A4 1010×1400, matching `A4`). Model it on the existing `public/folders/le-thi-mai-anh/bbnt.svg` for styling (read that file first, reuse its font/header markup). Content (all synthetic):

```
PHỤ LỤC HỢP ĐỒNG — ĐÁNH GIÁ SOW/KPI
Kỳ: Quý I/2026 · Sản phẩm: Crossfire: Legends
Hạng mục | Chỉ tiêu (KPI) | Thực hiện (Actual)
Nội dung 1 | 100 | 100
Nội dung 2 | 30 ngày | 28 ngày
Kết luận: Hoàn thành đúng phạm vi & thời gian.
```

Keep it a valid standalone `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1010 1400" width="1010" height="1400">...</svg>` with `<text>` elements. Verify it opens in a browser (valid XML).

- [ ] **Step 2: Add the appendix doc + recap to `le-thi-mai-anh` in `src/ctv/folders.ts`**

Add an appendix recap builder near the other recap builders:

```ts
const appendixRecap = (product: string): DocRecap => ({
  bullets: [
    `Phụ lục đánh giá SOW/KPI cho sản phẩm ${product}, kỳ Quý I/2026.`,
    'Các hạng mục KPI đều đạt chỉ tiêu; khối lượng thực hiện khớp cam kết.',
    'Thời gian thực hiện nằm trong kỳ nghiệm thu.',
  ],
  nhanDinh: 'Nội dung Phụ lục phù hợp phạm vi hợp đồng; thời gian khớp — hỗ trợ xác nhận C1.',
  disclaimer: RECAP_DISCLAIMER,
})
```

Change the `le-thi-mai-anh` folder's `docs:` to spread `docsFor(...)` and append the appendix:

```ts
    docs: [
      ...docsFor('le-thi-mai-anh', { contract: contractRecap('Crossfire: Legends'), bbnt: bbntRecap('Crossfire: Legends') }),
      { id: 'appendix', kind: 'appendix', label: 'Phụ lục (SOW/KPI)', recap: appendixRecap('Crossfire: Legends'),
        pages: [{ src: '/folders/le-thi-mai-anh/appendix.svg', ...A4 }] },
    ],
```

(Leave the other two folders as plain `docsFor(id, {...})` — they demo the BBNT-fallback path.)

- [ ] **Step 3: Typecheck + tests**

Run: `npx tsc --noEmit && npx vitest run`
Expected: no type errors; all tests pass. (`demoChecklist` now routes C1 → `appendix` for this folder — the existing routing test already covers the logic.)

- [ ] **Step 4: Commit**

```bash
git add public/folders/le-thi-mai-anh/appendix.svg src/ctv/folders.ts
git commit -m "feat(recap): synthetic Phụ lục doc on demo folder — showcases C1→appendix + recap"
```

---

### Task 11: Full verification + offline export

Run the whole gate, rebuild the single-file export, refresh `~/Downloads/Reviewer-v2.0.html`, and prove the canned recap renders offline with no network.

**Files:** none (verification only).

- [ ] **Step 1: Full test gate**

Run:
```bash
npx tsc --noEmit
npx vitest run
cd server && python3 -m pytest -q && cd ..
```
Expected: tsc clean; vitest all pass; pytest all pass.

- [ ] **Step 2: Build the single-file export**

Run: `npm run build:single`
Expected: writes `AP-Review-Prototype.html` at repo root, logs size + inlined-asset count (the new `appendix.svg` should be among them).

- [ ] **Step 3: Refresh the Downloads copy**

Run: `cp AP-Review-Prototype.html ~/Downloads/Reviewer-v2.0.html`
Expected: no error.

- [ ] **Step 4: Prove the canned recap renders offline (no network)**

Open the built file in the browser preview via `preview_start` with `{url: "file:///Users/lap16603/Downloads/Reviewer-v2.0.html"}` (or navigate to it). Then:
- Open a demo packet (e.g. Lê Thị Mai Anh).
- Select the C1 row "Nội dung & thời gian khớp BBNT" → confirm the scan pane opens the **Phụ lục (SOW/KPI)** doc.
- Click the ✨ "AI tóm tắt" button in the doc toolbar → confirm the popover shows the spinner briefly, then **Tóm tắt** bullets + **Nhận định** + the footer disclaimer.
- Switch to the Hợp đồng and BBNT tabs → confirm ✨ is available there too; open on id_front/pit tabs → confirm ✨ is **absent** (not content-bearing).
- Confirm `read_network_requests` shows **no** outbound API calls for the recap (fully offline/canned).
- Take a screenshot of the open popover as proof.

- [ ] **Step 5: Final commit (if any verification tweaks were needed)**

```bash
git add -A
git commit -m "chore(recap): batch-2 verification — offline export renders canned recap"
```

---

## Self-Review

**Spec coverage (docs/review-ui-content-checks.md):**
- C1 single confirm check, not split → Tasks 2 (routing unchanged from confirm/detail; no split). ✓
- C1 opens BBNT/Phụ lục; content in Phụ lục when present, else BBNT; no side-by-side → Task 2 (routing), Task 10 (Phụ lục demo). ✓
- General "AI recap this doc" button on content-bearing docs (contract, BBNT, Phụ lục, cam-kết) → Task 4 (`isContentBearing` gate) + Task 1 (`CONTENT_BEARING_KINDS`). ✓
- Popover: Tóm tắt (2–3 bullets) + Nhận định (tentative, never auto-marks/flags) + footer disclaimer → Task 3 (RecapPopover, pure display). ✓
- Generated on demand (spinner) then cached → Task 4 (loading state + `recapCache`), Task 8 (manifest cache). ✓
- Two sources behind one popover: live GreenNode server endpoint sending only the typed region + canned baked into synthetic packets → Tasks 6–9 (seam: DemoFlow canned / UploadFlow server; `content_region_for`; `greennode.summarize`). ✓
- GreenNode creds may be unwired → canned + seam + clear TODO, no block → Task 7 (`NotConfigured` + TODO), Task 8 (503). ✓
- D1 parked, untouched → not modified anywhere (checklist.py D1 row unchanged; no D1 tasks). ✓
- Constraints: only typed region leaves (Task 7 `content_region_for` + tests asserting no cross-doc leak); offline renders no-network (Task 11 verify); Vietnamese UI (all strings); tsc/vitest/pytest + rebuild (Task 11). ✓

**Placeholder scan:** every code step contains complete, compilable code; no TBD/TODO-as-work-item except the deliberate, spec-sanctioned `TODO(greennode)` live-call marker in `greennode.py`.

**Type consistency:** `DocRecap { bullets, nhanDinh, disclaimer }` used identically in types.ts, RecapPopover, DemoFlow, folders.ts, api.ts, and the server result dict. `getRecap: (doc: EvidenceDoc) => Promise<DocRecap>` identical in EvidenceViewer, FolderReview, DemoFlow, UploadFlow. `content_region_for(manifest, doc_id)` / `greennode.summarize(content)` signatures match their call sites and tests. `CONTENT_BEARING_KINDS` mirrored front (recap.ts) and back (recap.py). Endpoint `POST /api/cases/{cid}/packets/{i}/recap` body `{docId}` matches `fetchDocRecap`.
