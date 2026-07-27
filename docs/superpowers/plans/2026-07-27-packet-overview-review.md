# Packet Overview Review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a clean, presentation-only `Tổng quan` landing state for every v1 packet while preserving detailed-field review, rejection, completion, status, progress, and report behavior.

**Architecture:** Introduce a small typed renderer-local selection model that distinguishes Overview from real fields. `FolderReview` owns selection and focus transitions, `FolderFieldsPanel` renders the virtual Overview row without counting it as a field, and `EvidenceViewer` receives an explicit Overview presentation mode that resets to the approved 100% two-page preset and suppresses field overlays.

**Tech Stack:** React 18, TypeScript 5.5, Vitest 2, React server rendering tests, Vite 5, FastAPI/Pytest regression suite.

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`.
- Do not modify `/Users/lap16603/Documents/New project/work/CTV_APReview`.
- Keep v1 frontend port `5174` and backend port `8001`.
- Do not push.
- Do not add a backend endpoint, persisted Overview field, review property, display status, report item, or manifest mutation.
- Overview must not mark a field seen, alter `review.done`, affect counts, or affect packet lifecycle.
- Normal acceptance remains `✓ Xong` and still requires every real field to be seen.
- Reuse the existing rejection dialog, save queue, persistence contract, derived status, and reports.
- Keep tests, fixtures, docs, and QA evidence free of copied real PII.
- Write each production change only after its focused test has been observed failing.

---

### Task 1: Typed Overview and Field Selection Model

**Files:**
- Create: `src/logic/reviewSelection.ts`
- Create: `src/logic/reviewSelection.test.ts`

**Interfaces:**
- Consumes: real field keys as `string[]`.
- Produces:
  - `type ReviewSelection = { kind: 'overview' } | { kind: 'field'; key: string; sourceIndex: number }`
  - `overviewSelection(): ReviewSelection`
  - `fieldSelection(key: string, sourceIndex?: number): ReviewSelection`
  - `selectedFieldKey(selection: ReviewSelection): string | null`
  - `moveVerticalSelection(selection: ReviewSelection, fieldKeys: string[], direction: 'up' | 'down'): ReviewSelection`

- [ ] **Step 1: Write the failing selection tests**

Create `src/logic/reviewSelection.test.ts`:

```ts
import { describe, expect, it } from 'vitest'
import {
  fieldSelection,
  moveVerticalSelection,
  overviewSelection,
  selectedFieldKey,
} from './reviewSelection'

describe('review selection', () => {
  const fieldKeys = ['name', 'cccd', 'fee']

  it('represents Overview without borrowing a field key', () => {
    expect(overviewSelection()).toEqual({ kind: 'overview' })
    expect(selectedFieldKey(overviewSelection())).toBeNull()
    expect(selectedFieldKey(fieldSelection('cccd', 1))).toBe('cccd')
  })

  it('moves down from Overview into the first real field', () => {
    expect(moveVerticalSelection(
      overviewSelection(),
      fieldKeys,
      'down',
    )).toEqual(fieldSelection('name'))
  })

  it('moves up from the first field back to Overview', () => {
    expect(moveVerticalSelection(
      fieldSelection('name'),
      fieldKeys,
      'up',
    )).toEqual(overviewSelection())
  })

  it('keeps normal field-to-field navigation and endpoint clamping', () => {
    expect(moveVerticalSelection(
      fieldSelection('cccd', 1),
      fieldKeys,
      'down',
    )).toEqual(fieldSelection('fee'))
    expect(moveVerticalSelection(
      fieldSelection('cccd', 1),
      fieldKeys,
      'up',
    )).toEqual(fieldSelection('name'))
    expect(moveVerticalSelection(
      fieldSelection('fee'),
      fieldKeys,
      'down',
    )).toEqual(fieldSelection('fee'))
    expect(moveVerticalSelection(
      overviewSelection(),
      fieldKeys,
      'up',
    )).toEqual(overviewSelection())
  })

  it('stays on Overview when there are no real fields', () => {
    expect(moveVerticalSelection(
      overviewSelection(),
      [],
      'down',
    )).toEqual(overviewSelection())
  })
})
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
npm test -- src/logic/reviewSelection.test.ts
```

Expected: FAIL because `src/logic/reviewSelection.ts` does not exist.

- [ ] **Step 3: Implement the minimal typed selection model**

Create `src/logic/reviewSelection.ts`:

```ts
export type ReviewSelection =
  | { kind: 'overview' }
  | { kind: 'field'; key: string; sourceIndex: number }

export function overviewSelection(): ReviewSelection {
  return { kind: 'overview' }
}

export function fieldSelection(
  key: string,
  sourceIndex = 0,
): ReviewSelection {
  return { kind: 'field', key, sourceIndex }
}

export function selectedFieldKey(
  selection: ReviewSelection,
): string | null {
  return selection.kind === 'field' ? selection.key : null
}

export function moveVerticalSelection(
  selection: ReviewSelection,
  fieldKeys: string[],
  direction: 'up' | 'down',
): ReviewSelection {
  if (fieldKeys.length === 0) return overviewSelection()

  if (selection.kind === 'overview') {
    return direction === 'down'
      ? fieldSelection(fieldKeys[0])
      : overviewSelection()
  }

  const currentIndex = fieldKeys.indexOf(selection.key)
  if (currentIndex <= 0 && direction === 'up') return overviewSelection()
  if (currentIndex < 0) return overviewSelection()

  const nextIndex = direction === 'down'
    ? Math.min(currentIndex + 1, fieldKeys.length - 1)
    : Math.max(currentIndex - 1, 0)

  return fieldSelection(fieldKeys[nextIndex])
}
```

- [ ] **Step 4: Run the focused test and verify GREEN**

Run:

```bash
npm test -- src/logic/reviewSelection.test.ts
```

Expected: 5 tests pass.

- [ ] **Step 5: Run the TypeScript production build**

Run:

```bash
npm run build
```

Expected: TypeScript and Vite build succeed.

- [ ] **Step 6: Commit the selection model**

```bash
git add src/logic/reviewSelection.ts src/logic/reviewSelection.test.ts
git commit -m "feat(review): model packet overview selection"
```

---

### Task 2: Overview Row, Initial Selection, and Review Navigation

**Files:**
- Modify: `src/components/FolderFieldsPanel.tsx:1-105`
- Modify: `src/components/FolderReview.tsx:1-195`
- Modify: `src/components/reviewPresentation.test.tsx:1-228`
- Modify: `src/styles.css:580-644`

**Interfaces:**
- Consumes from Task 1:
  - `ReviewSelection`
  - `overviewSelection()`
  - `fieldSelection(key, sourceIndex)`
  - `selectedFieldKey(selection)`
  - `moveVerticalSelection(selection, fieldKeys, direction)`
- Produces:
  - `FolderFieldsPanel` props `selection`, `onSelectOverview`, and `onSelectField`
  - an initial Overview render that creates no review update
  - a compact Overview rejection entry and persisted rejection summary
  - vertical keyboard navigation that includes Overview

- [ ] **Step 1: Update the panel test harness and add failing Overview presentation tests**

In `src/components/reviewPresentation.test.tsx`, import the new selection helpers:

```ts
import {
  fieldSelection,
  overviewSelection,
  type ReviewSelection,
} from '../logic/reviewSelection'
```

Change `renderPanel` to accept an explicit selection while preserving a selected
field as the default for existing flag-editor tests:

```tsx
const renderPanel = (
  review: PacketReview,
  rows: RankedCtv[] = ranked,
  selection: ReviewSelection = fieldSelection('field-a'),
) => renderToStaticMarkup(
  <FolderFieldsPanel
    ranked={rows}
    selection={selection}
    onSelectOverview={() => undefined}
    onSelectField={() => undefined}
    review={review}
    onToggleFlag={() => undefined}
    onOpenPacketRejection={() => undefined}
  />,
)
```

Replace the existing large-rejection-entry test with:

```ts
it('renders selected Overview first without changing field totals', () => {
  const html = renderPanel(
    { done: false, fields: {}, rejection: null },
    ranked,
    overviewSelection(),
  )

  expect(html).toContain('data-review-selection="overview"')
  expect(html).toContain('Tổng quan')
  expect(html).toContain('Xem nhanh toàn bộ chứng từ')
  expect(html).toContain('Từ chối hồ sơ')
  expect(html.indexOf('Tổng quan')).toBeLessThan(html.indexOf('Trường mẫu'))
  expect(html).toContain('1 mục kiểm tra')
  expect(html).toContain('0/1 đã xem')
  expect(html).not.toContain('Từ chối gói hồ sơ')
})
```

Update the panel invocation in `selects a row before opening its flag editor`:

```tsx
const tree = FolderFieldsPanel({
  ranked,
  selection: fieldSelection('field-a'),
  onSelectOverview: () => undefined,
  onSelectField: key => { selectedKey = key },
  review: { done: false, fields: {}, rejection: null },
  onToggleFlag: key => { flaggedKey = key },
  onOpenPacketRejection: () => undefined,
})
```

Add an initial-review presentation test. Import `vi` from Vitest and use the
existing synthetic field and document:

```tsx
it('opens on Overview without publishing a field review', () => {
  const onReview = vi.fn()
  const html = renderToStaticMarkup(
    <FolderReview
      folder={{
        id: 'synthetic-overview',
        name: 'Synthetic CTV',
        product: 'Synthetic Product',
        status: 'pending',
        exempt: false,
        docs: [{
          id: 'contract',
          kind: 'contract',
          label: 'Synthetic contract',
          pages: [{ src: '/synthetic.svg', width: 1000, height: 1400 }],
        }],
        fields: [ranked[0].field],
      }}
      review={{ done: false, fields: {}, rejection: null }}
      onReview={onReview}
      onCommitReview={async () => undefined}
    />,
  )

  expect(onReview).not.toHaveBeenCalled()
  expect(html).toContain('data-review-selection="overview"')
  expect(html).toContain('0/1 đã xem')
  expect(html).not.toContain('roster-callout')
})
```

Change the existing currency integration expectation because the initial
Overview intentionally suppresses the bbox callout:

```ts
expect(html.match(/6\.111\.111 ₫/g)).toHaveLength(1)
expect(html).not.toContain('roster-callout')
```

- [ ] **Step 2: Run the focused component tests and verify RED**

Run:

```bash
npm test -- src/components/reviewPresentation.test.tsx
```

Expected: FAIL because `FolderFieldsPanel` does not accept the Overview props,
does not render `Tổng quan`, and `FolderReview` still initializes the first
field.

- [ ] **Step 3: Render the virtual Overview row and move rejection inside it**

In `src/components/FolderFieldsPanel.tsx`, replace `selectedKey` and `onSelect`
with:

```ts
selection: ReviewSelection
onSelectOverview: () => void
onSelectField: (key: string) => void
```

Import `ReviewSelection`:

```ts
import type { ReviewSelection } from '../logic/reviewSelection'
```

Immediately after `.fields-summary`, render:

```tsx
<section
  className={`overview-row${selection.kind === 'overview' ? ' sel' : ''}`}
  data-review-selection={selection.kind === 'overview' ? 'overview' : undefined}
  onClick={onSelectOverview}
>
  <div className="overview-row-head">
    <div>
      <strong>Tổng quan</strong>
      <span>Xem nhanh toàn bộ chứng từ</span>
    </div>
    {!review.rejection && (
      <button
        type="button"
        className="overview-rejection-open"
        onClick={event => {
          event.stopPropagation()
          onSelectOverview()
          onOpenPacketRejection()
        }}
      >
        Từ chối hồ sơ
      </button>
    )}
  </div>
  {review.rejection && (
    <div className="packet-rejection-summary" aria-label="Đã từ chối">
      <div className="packet-rejection-summary-head">
        <strong>Đã từ chối</strong>
        <button
          type="button"
          onClick={event => {
            event.stopPropagation()
            onSelectOverview()
            onOpenPacketRejection()
          }}
        >
          Sửa lý do
        </button>
      </div>
      <ul>
        {PACKET_REJECTION_OPTIONS
          .filter(option => review.rejection?.reasons.includes(option.value))
          .map(option => <li key={option.value}>{option.label}</li>)}
      </ul>
      {review.rejection.note && (
        <p className="packet-rejection-summary-note">
          {review.rejection.note}
        </p>
      )}
    </div>
  )}
</section>
```

Delete the old standalone `.packet-rejection-entry` / rejection-summary block.
Keep the ranked-field map immediately after the Overview section. A field is
selected only when:

```ts
const sel = selection.kind === 'field'
  && r.field.key === selection.key
```

Replace row callbacks with `onSelectField(r.field.key)`.

- [ ] **Step 4: Add the Overview styling**

Replace the old full-width `.packet-rejection-entry` and
`.packet-rejection-open` rules in `src/styles.css` with:

```css
.overview-row {
  padding: 12px 13px;
  border-bottom: 1px solid var(--border);
  border-left: 4px solid transparent;
  background: var(--surface);
  cursor: pointer;
}
.overview-row.sel {
  border-left-color: var(--accent);
  background: #eaf1fb;
}
.overview-row-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.overview-row-head > div {
  display: grid;
  gap: 3px;
}
.overview-row-head > div > strong {
  font-size: 14px;
}
.overview-row-head > div > span {
  color: var(--text-muted);
  font-size: 12px;
}
.overview-rejection-open {
  flex: 0 0 auto;
  padding: 7px 10px;
  border: 1px solid var(--danger);
  border-radius: 8px;
  background: transparent;
  color: var(--danger);
  cursor: pointer;
  font: inherit;
  font-size: 12px;
  font-weight: 700;
}
.overview-rejection-open:hover {
  background: #fff5f4;
}
.overview-rejection-open:focus-visible,
.overview-row:focus-within {
  outline: 2px solid var(--accent);
  outline-offset: -2px;
}
.overview-row .packet-rejection-summary {
  margin: 10px 0 0;
}
```

Keep the existing rejection-summary and dialog rules unchanged.

- [ ] **Step 5: Make FolderReview initialize and navigate through Overview**

In `src/components/FolderReview.tsx`, import the Task 1 model:

```ts
import {
  fieldSelection,
  moveVerticalSelection,
  overviewSelection,
  selectedFieldKey,
  type ReviewSelection,
} from '../logic/reviewSelection'
```

Replace `selectedKey` and `srcIdx` state with:

```ts
const [selection, setSelection] = useState<ReviewSelection>(
  overviewSelection,
)
const [activeDocId, setActiveDocId] = useState(folder.docs[0]?.id ?? '')
const [activePage, setActivePage] = useState(0)
const [focusBbox, setFocusBbox] = useState<Bbox | null>(null)
```

Delete `const first = ranked[0]?.field`, the old `selectedKey` state, the old
`srcIdx` state, and the first-field mount-seed effect. Keep `markSeen`, but
update its comment so it refers only to explicit field focus.

Add the presentation reset:

```ts
const selectOverview = () => {
  setSelection(overviewSelection())
  setActiveDocId(folder.docs[0]?.id ?? '')
  setActivePage(0)
  setFocusBbox(null)
}
```

Update field focus:

```ts
const focusAt = (key: string, sourceIndex: number) => {
  setSelection(fieldSelection(key, sourceIndex))
  markSeen(key)
  const source = folder.fields
    .find(field => field.key === key)
    ?.sources[sourceIndex]
  if (source) {
    setActiveDocId(source.docId)
    setActivePage(source.page)
    setFocusBbox(source.bbox)
  } else {
    setFocusBbox(null)
  }
}
```

Update document-tab selection:

```ts
const onSelectDoc = (id: string) => {
  if (selection.kind === 'overview') {
    setActiveDocId(id)
    setActivePage(0)
    setFocusBbox(null)
    return
  }

  const sourceIndex = folder.fields
    .find(field => field.key === selection.key)
    ?.sources.findIndex(source => source.docId === id) ?? -1

  if (sourceIndex >= 0) focusAt(selection.key, sourceIndex)
  else {
    setActiveDocId(id)
    setActivePage(0)
    setFocusBbox(null)
  }
}
```

Replace vertical keyboard index arithmetic with:

```ts
const nextSelection = moveVerticalSelection(
  selection,
  ranked.map(row => row.field.key),
  e.key === 'ArrowDown' ? 'down' : 'up',
)
if (nextSelection.kind === 'overview') selectOverview()
else focusAt(nextSelection.key, nextSelection.sourceIndex)
```

For Arrow Left/Right, return immediately when `selection.kind === 'overview'`.
For a field, use `selection.key` and `selection.sourceIndex` in the existing
source-navigation calculation.

For the `F` shortcut, return immediately when `selection.kind === 'overview'`.
For a field, read and toggle `review.fields[selection.key]`.

Update the vertical/source keyboard effect dependency list to use
`[ranked, selection, folder]`. Update the `F` shortcut effect dependency list to
use `[review, selection]`.

Derive the selected field:

```ts
const selectedKey = selectedFieldKey(selection)
const selField = selectedKey
  ? folder.fields.find(field => field.key === selectedKey)
  : undefined
```

Pass the new panel props:

```tsx
<FolderFieldsPanel
  ranked={ranked}
  selection={selection}
  onSelectOverview={selectOverview}
  onSelectField={key => focusAt(key, 0)}
  review={review}
  onToggleFlag={toggleFlag}
  onOpenPacketRejection={() => {
    setRejectionError(null)
    setRejectionDialogOpen(true)
  }}
/>
```

- [ ] **Step 6: Run the focused component and selection tests**

Run:

```bash
npm test -- src/logic/reviewSelection.test.ts src/components/reviewPresentation.test.tsx
```

Expected: all focused tests pass.

- [ ] **Step 7: Run the current rejection and dashboard regressions**

Run:

```bash
npm test -- src/components/packetRejectionDialog.test.tsx src/logic/packetRejection.test.ts src/logic/packetDashboard.test.ts src/components/caseDetail.test.tsx
```

Expected: existing rejection, status, counts, and case-detail tests pass.

- [ ] **Step 8: Run the build**

Run:

```bash
npm run build
```

Expected: TypeScript and Vite build succeed.

- [ ] **Step 9: Commit the Overview selection UI**

```bash
git add \
  src/components/FolderFieldsPanel.tsx \
  src/components/FolderReview.tsx \
  src/components/reviewPresentation.test.tsx \
  src/styles.css
git commit -m "feat(review): add packet overview landing"
```

---

### Task 3: Clean 100% Two-Page Overview Viewer

**Files:**
- Modify: `src/components/EvidenceViewer.tsx:19-337`
- Modify: `src/components/FolderReview.tsx:157-167`
- Modify: `src/components/evidenceViewer.test.tsx:1-78`
- Modify: `src/components/reviewPresentation.test.tsx:201-228`

**Interfaces:**
- Consumes: `selection.kind === 'overview'` from Task 2.
- Produces:
  - required `EvidenceViewer` prop `overviewMode: boolean`
  - initial and re-entry Overview preset of paired pages at zoom `1`
  - no autofocus, bbox highlight, or roster callout in Overview
  - unchanged field-focused viewer behavior when `overviewMode` is false

- [ ] **Step 1: Add failing viewer tests for the clean Overview preset**

Update every existing `EvidenceViewer` test render to pass
`overviewMode={false}`.

In `src/components/evidenceViewer.test.tsx`, add:

```tsx
it('renders Overview at 100% in paired mode without field overlays', () => {
  const html = renderToStaticMarkup(
    <EvidenceViewer
      docs={docs}
      activeDocId="doc"
      activePage={1}
      focusBbox={{ x: 100, y: 200, width: 300, height: 40 }}
      lockView={false}
      overviewMode
      onSelectDoc={() => undefined}
      onToggleLock={() => undefined}
      rosterLabel="Synthetic field"
      rosterValue="Synthetic value"
    />,
  )

  expect(html).toContain('data-view-presentation="overview"')
  expect(html).toContain('class="ev-document paired"')
  expect(html).toContain('class="zoom-value">100%</span>')
  expect(html).not.toContain('document-focus-anchor')
  expect(html).not.toContain('doc-hl-fill')
  expect(html).not.toContain('roster-callout')
})

it('keeps bbox and roster callout in field mode', () => {
  const html = renderToStaticMarkup(
    <EvidenceViewer
      docs={docs}
      activeDocId="doc"
      activePage={1}
      focusBbox={{ x: 100, y: 200, width: 300, height: 40 }}
      lockView={false}
      overviewMode={false}
      onSelectDoc={() => undefined}
      onToggleLock={() => undefined}
      rosterLabel="Phí dịch vụ"
      rosterValue="6.111.111 ₫"
    />,
  )

  expect(html).toContain('data-view-presentation="field"')
  expect(html).toContain('document-focus-anchor')
  expect(html).toContain('doc-hl-fill')
  expect(html).toContain('Bảng kê — Phí dịch vụ')
  expect(html).toContain('6.111.111 ₫')
})
```

- [ ] **Step 2: Run the viewer test and verify RED**

Run:

```bash
npm test -- src/components/evidenceViewer.test.tsx
```

Expected: FAIL because `EvidenceViewer` has no `overviewMode` prop, initializes
in single-page mode, and still renders field overlays.

- [ ] **Step 3: Add the explicit Overview presentation prop and preset**

In `src/components/EvidenceViewer.tsx`, add:

```ts
overviewMode: boolean
```

to `Props` and destructure it in the component.

Initialize the view mode from the presentation:

```ts
const [viewMode, setViewMode] = useState<DocumentViewMode>(
  overviewMode ? 'paired' : 'single',
)
```

Add an Overview-entry reset effect:

```ts
useEffect(() => {
  if (!overviewMode) return
  setViewMode('paired')
  setZoomLevel(1)
}, [overviewMode])
```

Add a separate first-page scroll reset that also runs when the active Overview
document changes, without resetting manual zoom or page mode:

```ts
useEffect(() => {
  if (!overviewMode) return
  const animationFrame = requestAnimationFrame(() => {
    scrollRef.current?.scrollTo({
      left: 0,
      top: 0,
      behavior: 'instant',
    })
  })
  return () => cancelAnimationFrame(animationFrame)
}, [overviewMode, activeDocId])
```

Suppress the inflated bbox:

```ts
const focusedBox = useMemo(() => {
  if (overviewMode || !focusBbox || !doc?.pages[pageIndex]) return null
  const page = doc.pages[pageIndex]
  return inflateBbox(focusBbox, 0.2, page.width, page.height)
}, [overviewMode, focusBbox, doc, pageIndex])
```

Return early from both autofocus and focus-scroll effects when
`overviewMode` is true. Keep their existing lock behavior for field mode.

Add the testable presentation marker:

```tsx
<section
  className="ev"
  data-view-presentation={overviewMode ? 'overview' : 'field'}
>
```

Guard both attached and corner roster callouts with `!overviewMode`. The bbox
anchor will already be absent because `focusedBox` is null.

- [ ] **Step 4: Connect FolderReview to the viewer presentation**

In `src/components/FolderReview.tsx`, pass:

```tsx
overviewMode={selection.kind === 'overview'}
```

Keep `rosterLabel` and `rosterValue` derived only from `selField`. They therefore
remain absent in Overview and resume automatically for a selected real field.

- [ ] **Step 5: Run the focused viewer and presentation tests**

Run:

```bash
npm test -- src/components/evidenceViewer.test.tsx src/components/reviewPresentation.test.tsx src/logic/documentView.test.ts
```

Expected: Overview and field presentation tests pass, and existing document
grouping, autofocus, geometry, and pan tests remain green.

- [ ] **Step 6: Run the complete frontend suite**

Run:

```bash
npm test
```

Expected: every Vitest file passes with zero failures.

- [ ] **Step 7: Run the production build**

Run:

```bash
npm run build
```

Expected: TypeScript and Vite build succeed.

- [ ] **Step 8: Commit the clean Overview viewer**

```bash
git add \
  src/components/EvidenceViewer.tsx \
  src/components/FolderReview.tsx \
  src/components/evidenceViewer.test.tsx \
  src/components/reviewPresentation.test.tsx
git commit -m "feat(review): add clean packet overview viewer"
```

---

### Task 4: Full Regression Verification and Browser QA

**Files:**
- Verify only: no planned production file changes.

**Interfaces:**
- Consumes: completed Tasks 1–3.
- Produces: fresh command output and browser evidence proving the approved design
  and existing v1 behavior.

- [ ] **Step 1: Run all frontend tests**

Run:

```bash
npm test
```

Expected: all Vitest test files and tests pass with zero failures.

- [ ] **Step 2: Run all backend and splitter tests**

Run:

```bash
python3 -m pytest server splitter -q
```

Expected: all tests pass; existing third-party deprecation warnings are
acceptable, but failures are not.

- [ ] **Step 3: Build the production frontend**

Run:

```bash
npm run build
```

Expected: `tsc -b` and `vite build` exit successfully.

- [ ] **Step 4: Verify the patch and checkout boundaries**

Run:

```bash
git diff --check
git status --short --branch
git -C "/Users/lap16603/Documents/New project/work/CTV_APReview" status --short --branch
```

Expected:

- no whitespace errors;
- only intentional v1 commits;
- the v2 checkout remains unchanged;
- no push has occurred.

- [ ] **Step 5: Verify both v1 services**

Run:

```bash
curl -sS -o /dev/null -w "frontend HTTP %{http_code}\n" \
  http://127.0.0.1:5174/
curl -sS -o /dev/null -w "backend cases API HTTP %{http_code}\n" \
  http://127.0.0.1:8001/api/cases
```

Expected: both return HTTP 200. If a service is not running, launch only the v1
frontend on 5174 and backend on 8001 using the repository's existing commands.

- [ ] **Step 6: Browser QA the initial Overview**

At `http://127.0.0.1:5174/`, open an existing packet without recording its
identity or document contents. Verify:

- `Tổng quan` is the selected first row;
- the real-field count and seen count are unchanged by packet open;
- the first document opens at page one;
- `2 trang` is selected;
- zoom shows 100%;
- no bbox or roster callout appears;
- document tabs, wheel/trackpad scroll, pan, zoom, one-page/two-page, lock, and
  help remain usable.

- [ ] **Step 7: Browser QA detailed-field transitions**

Using the same packet:

- select a real field and confirm only that field becomes seen;
- confirm its document, page, bbox, roster callout, and autofocus return;
- press Arrow Up from the first field and confirm Overview resets cleanly;
- press Arrow Down and confirm the first field is selected again;
- confirm Arrow Left/Right and `F` do nothing while Overview is active;
- confirm existing source navigation and `F` work for a real field;
- confirm two-page horizontal panning still works after autofocus.

- [ ] **Step 8: Browser QA completion, rejection, and return-to-case regressions**

Verify:

- `✓ Xong` remains disabled until all real fields are seen;
- the compact `Từ chối hồ sơ` action opens the existing dialog;
- create, validation, retry-safe save behavior, `Sửa lý do`, and undo remain
  usable;
- reopening incomplete, completed, flagged, and rejected packets always starts
  on Overview;
- returning to case detail shows the existing mutually exclusive status and
  counts;
- packet rejection and field flags still produce the existing flagged status;
- the page is responsive at desktop widths;
- no console or page errors occur.

- [ ] **Step 9: Record exact completion evidence**

Record:

- final v1 branch and commit;
- exact changed files;
- frontend test count;
- backend/splitter test count;
- production build result;
- frontend/backend HTTP results;
- browser QA outcomes;
- v2 status confirmation;
- explicit confirmation that nothing was pushed and no real PII was copied.
