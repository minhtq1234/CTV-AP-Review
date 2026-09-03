# Cell-to-Document Popup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** In the 25-criteria matrix and the Dạng bảng grid, clicking a ✓ / ✗ / ? / ! opens the document that cell refers to, full-page, in a popup — with no autofocus on the value.

**Architecture:** One pure map from criteria column name to manifest document kind (they are not the same thing today), then `PacketDocsDialog` — already built and shipped — gains the ability to open on a named document instead of the first, and both views mount it.

**Tech Stack:** React 18 · TypeScript · Vite · Vitest. No backend change, no new endpoint.

**Scope note:** template-aware workbook reading is a separate plan — `2026-08-28-template-aware-workbook.md`. The two share no code and can be done in either order.

---

## Before you start

**This repo has three divergent lineages sharing filenames with different APIs.** Verify every
symbol against *this* checkout (`stable/2026-08-25-cccd-idp`). Never `main`, never `ver1`.

**Environment quirks observed on the author's machine** — check whether they apply to yours:

- the `npm` and `npx` wrappers throw `EPERM: uv_cwd`; call `node_modules/.bin/vitest` and
  `node_modules/.bin/tsc` directly
- `tsconfig.json` sets `noUnusedLocals` and `noUnusedParameters`, so an unused import or local is a
  build error — introduce each one in the task that first uses it
- `zsh` eats unquoted glob-ish arguments; quote `--include='*.tsx'`

**Test conventions here are not testing-library** (it is not a dependency):

- static render tests use `renderToStaticMarkup` from `react-dom/server` in the default `node`
  environment — `src/components/cccdReviewScreen.test.tsx` is the model
- interaction tests put `// @vitest-environment jsdom` on line 1 and use `act` from `react` with
  `createRoot` from `react-dom/client`, stubbing `IS_REACT_ACT_ENVIRONMENT` in `beforeEach` —
  `src/components/CccdReviewScreen.interaction.test.tsx` is the model
- **`vi.spyOn(window.localStorage, …)` silently does nothing here** — jsdom's `Storage` is a legacy
  platform object, so a spy on the instance is never called. Spy on `Storage.prototype`.

**Green before every commit:** `node_modules/.bin/tsc -b` and `node_modules/.bin/vitest run`. At
the time of writing that is **334 passing across 33 files**; establish your own baseline first and
compare against that.

---

## The decision this implements, and the one it overturns

The reviewer asked: clicking a status glyph should open the relevant document, full view, no
autofocus. Recorded in `docs/ver3-scope.md` §2, along with four decisions:

1. the `Excel` cell does **nothing** — it is the reference value, not a document
2. the `Bảng Kê Thu Mua` cell **navigates to the Tổng hợp tab** — it is roster-level, and the
   criterion's own note already says to check it there
3. `CCCD/Passport` opens the **front**, with the back reachable through the viewer's own tabs
4. "no autofocus" applies to **this popup only** — the packet-review screen keeps its
   bounding-box highlight, which is useful where a value actually exists

**What this overturns.** The matrix cell button is already taken.
`src/components/CriteriaMatrix.tsx` (around line 229) has it open the *detail row*, with a comment
giving the reason:

> Opens the detail row, not a popover: the table scrolls horizontally so a popover anchored to a
> cell would clip — and a reviewer should read the note and the value before deciding, not decide
> from a glyph.

That reasoning is sound and must not simply be discarded. **The popup carries the cell's note and
value in its header**, so the note is still read before deciding — in the popup rather than in a
detail row. Task 3 covers this explicitly; do not skip it.

Similarly, the Dạng bảng grid already opens documents on click:
`src/components/PacketGrid.tsx` line 68 calls `onOpenEvidence(row.fieldKey, cell.sourceIndex)`,
which focuses the value's bounding box. For that view this is a **change of behaviour**, not an
addition.

---

## The mapping — the one genuinely new piece

The matrix's columns are criteria column names (`server/criteria.py:35-42`). The packet's
documents have kinds and labels (`manifest.json` → `docs[].kind`). They are not the same thing and
nothing maps between them today.

| criteria column | manifest kind |
|---|---|
| `Hợp đồng` | `contract` |
| `BBNT` | `bbnt` |
| `Phụ lục/KPI` | `appendix` |
| `Cam kết PIT` | `commitment` |
| `Website tra cứu MST` | **`pit`** — the column names MST, the kind is `pit`. This is the easy mistake. |
| `CCCD/Passport` | `id_front` (front first; `id_back` via the viewer's tabs) |
| `Excel` | — none |
| `Bảng Kê Thu Mua` | — none, roster-level |

The kind vocabulary is closed — `src/ctv/types.ts:7`:

```ts
export type EvidenceKind = 'id_front' | 'id_back' | 'contract' | 'commitment' | 'pit' | 'bbnt' | 'appendix'
```

and the column names are `server/criteria.py:35-42`, reaching the browser verbatim inside the
criteria payload. Both were checked against this checkout while writing the plan.

## Seams already verified — do not re-derive these

- `CriterionCell` is declared in **`src/upload/api.ts:470`**, not in `src/ctv/types.ts`. It carries
  `status`, `document`, `note`, `value`, and `evidence[]`.
- The matrix cell's existing `aria-label` is `` `${row.label} · ${cell.document}: ${status.label}` ``
  — Task 3's popup label follows the same shape on purpose.
- **`PacketDocsDialog` already satisfies the "no autofocus" decision with no work.** Its doc comment
  says `focusBbox` stays `null` and `lockView` stays `false` for the dialog's whole life, because
  there is no field selection inside it to focus a value against. Read that comment before changing
  anything — the behaviour the reviewer asked for is the behaviour it already has.
- **The grid's columns are the packet's own documents**, not criteria columns:
  `src/logic/packetGrid.ts:12` types them `{ docId: string; label: string }` and line 42 builds them
  from `folder.docs`. Task 4 therefore does **not** need the Task 1 map.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/logic/criteriaDocument.ts` **(create)** | Pure: criteria column name → manifest document kind, and whether a cell is openable at all. |
| `src/logic/criteriaDocument.test.ts` **(create)** | Unit tests, node environment. |
| `src/components/PacketDocsDialog.tsx` **(modify)** | Optional `initialDocKind` to open on a named document; optional `onOpenPacket` and an optional note/value header. |
| `src/components/CriteriaMatrix.tsx` **(modify)** | Cell click asks its parent to open a document. |
| `src/components/FolderReview.tsx` **(modify)** | Owns the dialog state for the matrix and the grid, and mounts the dialog. |
| `src/components/PacketGrid.tsx` **(modify)** | Cell click opens the same popup instead of focusing evidence. |

---

## Task 1: The column-to-document map

**Files:**
- Create: `src/logic/criteriaDocument.ts`
- Create: `src/logic/criteriaDocument.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// src/logic/criteriaDocument.test.ts
import { describe, expect, it } from 'vitest'
import { documentKindForColumn, cellAction } from './criteriaDocument'

describe('documentKindForColumn', () => {
  it('maps every column that has a document behind it', () => {
    expect(documentKindForColumn('Hợp đồng')).toBe('contract')
    expect(documentKindForColumn('BBNT')).toBe('bbnt')
    expect(documentKindForColumn('Phụ lục/KPI')).toBe('appendix')
    expect(documentKindForColumn('Cam kết PIT')).toBe('commitment')
  })

  it('maps the MST lookup column to the pit kind, not to an mst kind', () => {
    // The column is named for MST; the document is the tax-lookup page, whose
    // kind is `pit`. Getting this wrong opens the wrong document.
    expect(documentKindForColumn('Website tra cứu MST')).toBe('pit')
  })

  it('maps the identity column to the card front', () => {
    // The back is reachable through the viewer's own tabs, so the click does
    // not have to choose between them.
    expect(documentKindForColumn('CCCD/Passport')).toBe('id_front')
  })

  it('has no document for the reference columns', () => {
    expect(documentKindForColumn('Excel')).toBeNull()
    expect(documentKindForColumn('Bảng Kê Thu Mua')).toBeNull()
  })

  it('returns null for a column it has never heard of', () => {
    expect(documentKindForColumn('Cột Mới')).toBeNull()
  })
})

describe('cellAction', () => {
  it('opens the document for an ordinary cell', () => {
    expect(cellAction('Hợp đồng', 'no')).toEqual({ kind: 'open', docKind: 'contract' })
  })

  it('does nothing for the Excel column', () => {
    expect(cellAction('Excel', 'ok')).toEqual({ kind: 'none' })
  })

  it('sends the roster-level column to Tổng hợp', () => {
    expect(cellAction('Bảng Kê Thu Mua', 'pending')).toEqual({ kind: 'summary' })
  })

  it('does nothing for a cell that does not apply', () => {
    // `na` means the criterion does not apply to this document at all -- there
    // is nothing to look at, and the note already says so.
    expect(cellAction('Phụ lục/KPI', 'na')).toEqual({ kind: 'none' })
  })

  it('still opens a document for a missing or pending cell', () => {
    // `missing` is a claim about a document; the reviewer may well want to look
    // at what IS in the packet to confirm it. The dialog handles the case where
    // the document genuinely is not there.
    expect(cellAction('BBNT', 'missing')).toEqual({ kind: 'open', docKind: 'bbnt' })
    expect(cellAction('BBNT', 'pending')).toEqual({ kind: 'open', docKind: 'bbnt' })
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/logic/criteriaDocument.test.ts
```
Expected: FAIL — `Failed to resolve import "./criteriaDocument"`

- [ ] **Step 3: Implement**

```ts
// src/logic/criteriaDocument.ts
// The matrix's columns are criteria column names (server/criteria.py:35-42).
// A packet's documents have kinds (manifest.json -> docs[].kind). They are not
// the same vocabulary and nothing mapped between them before this.
import type { EvidenceKind } from '../ctv/types'

/** Criteria column name -> the document kind that column refers to. */
const KIND_BY_COLUMN: Record<string, EvidenceKind> = {
  'Hợp đồng': 'contract',
  'BBNT': 'bbnt',
  'Phụ lục/KPI': 'appendix',
  'Cam kết PIT': 'commitment',
  // Named for MST, but the document is the tax-lookup page and its kind is
  // `pit`. The two names disagree; the kind is what the manifest holds.
  'Website tra cứu MST': 'pit',
  // The front. The back is one tab away inside the viewer, so the click does
  // not have to decide between them.
  'CCCD/Passport': 'id_front',
}

/** `Excel` is the reference value and `Bảng Kê Thu Mua` spans the whole bảng
 *  kê, so neither has a document in this packet. */
export function documentKindForColumn(column: string): EvidenceKind | null {
  return KIND_BY_COLUMN[column] ?? null
}

export type CellAction =
  | { kind: 'open'; docKind: EvidenceKind }
  | { kind: 'summary' }
  | { kind: 'none' }

/** What clicking this cell should do. `na` never opens anything: the criterion
 *  does not apply to that document, so there is nothing to look at and the
 *  cell's note already explains why. */
export function cellAction(column: string, status: string): CellAction {
  if (status === 'na') return { kind: 'none' }
  if (column === 'Bảng Kê Thu Mua') return { kind: 'summary' }
  const docKind = documentKindForColumn(column)
  return docKind ? { kind: 'open', docKind } : { kind: 'none' }
}
```

- [ ] **Step 4: Run the tests**

```bash
node_modules/.bin/vitest run src/logic/criteriaDocument.test.ts
node_modules/.bin/tsc -b
```
Expected: PASS (11 passed); `tsc -b` exits 0

- [ ] **Step 5: Commit**

```bash
git add src/logic/criteriaDocument.ts src/logic/criteriaDocument.test.ts
git commit -m "feat(criteria): map a matrix column to the document it refers to"
```

---

## Task 2: Let the dialog open on a named document

`PacketDocsDialog` currently opens on the first document and always shows a `Mở gói hồ sơ` button.
Opened from inside the packet-review screen, that button would navigate to where the reviewer
already is.

**Files:**
- Modify: `src/components/PacketDocsDialog.tsx`
- Modify: `src/components/PacketDocsDialog.interaction.test.tsx`

- [ ] **Step 1: Read the component first**

Read `PacketDocsDialog.tsx` in full before editing. Note how it picks the initially-active
document and how it passes `docs` into `EvidenceViewer`. Write down the current props in your
report.

- [ ] **Step 2: Write the failing test**

Add to `src/components/PacketDocsDialog.interaction.test.tsx`, following the mocking already in
that file:

```tsx
  it('opens on the requested document kind rather than the first', async () => {
    // The manifest's first doc is the contract; ask for the BBNT and assert the
    // viewer starts there.
    await mountDialog({ initialDocKind: 'bbnt' })
    const active = host.querySelector('.ev-tab.active, [aria-selected="true"]')
    expect(active?.textContent).toContain('Biên bản')
  })

  it('falls back to the first document when that kind is not in this packet', async () => {
    await mountDialog({ initialDocKind: 'appendix' })   // fixture has no appendix
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()
    const active = host.querySelector('.ev-tab.active, [aria-selected="true"]')
    expect(active?.textContent).toContain('Hợp đồng')
  })

  it('omits the open-packet button when no handler is given', async () => {
    await mountDialog({ onOpenPacket: undefined })
    const buttons = [...host.querySelectorAll('button')].map(b => b.textContent)
    expect(buttons.some(t => t?.includes('Mở gói hồ sơ'))).toBe(false)
  })
```

You will need a `mountDialog(overrides)` helper in that file if one does not exist; write it in
the style of the existing mount helpers. **Check the actual class names** the viewer renders for
its tabs before asserting on `.ev-tab` — read `EvidenceViewer.tsx` and use what is really there.

- [ ] **Step 3: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/PacketDocsDialog.interaction.test.tsx
```
Expected: FAIL — the prop does not exist, so the dialog opens on the first document.

- [ ] **Step 4: Implement**

Add two optional props. Both are optional so every existing call site keeps working untouched:

```tsx
interface Props {
  caseId: string
  packetIndex: number
  packetName: string
  onClose: () => void
  /** Absent when the dialog is opened from inside the packet itself — there is
   *  nowhere to go, and a button that navigates to where you already are is a
   *  lie. */
  onOpenPacket?: (index: number) => void
  /** Open on this document rather than the first. Falls back to the first when
   *  the packet has no document of that kind. */
  initialDocKind?: EvidenceKind
  /** The cell's own note and value, shown in the header. The matrix cell used
   *  to open a detail row so the reviewer read these before deciding; carrying
   *  them here keeps that, rather than dropping it. */
  context?: { label: string; note?: string; value?: string } | null
}
```

Resolve the initial document by finding the first `doc` whose `kind` matches `initialDocKind`,
falling back to `docs[0]`. Render `context` in the dialog header when present. Render the
`Mở gói hồ sơ` button only when `onOpenPacket` is given.

- [ ] **Step 5: Run the tests**

```bash
node_modules/.bin/vitest run src/components/PacketDocsDialog.interaction.test.tsx
node_modules/.bin/tsc -b
```
Expected: PASS; `tsc -b` exits 0

- [ ] **Step 6: Commit**

```bash
git add src/components/PacketDocsDialog.tsx src/components/PacketDocsDialog.interaction.test.tsx
git commit -m "feat(packets): open the docs dialog on a named document, with the cell's note"
```

---

## Task 3: The matrix cell opens the document

**Files:**
- Modify: `src/components/CriteriaMatrix.tsx`
- Modify: `src/components/FolderReview.tsx`
- Modify: `src/components/criteriaMatrix.test.tsx`

- [ ] **Step 1: Write the failing test**

Add to `src/components/criteriaMatrix.test.tsx`, in that file's existing style:

```tsx
  it('asks to open the document for the column the cell sits in', () => {
    const opened: Array<{ docKind: string; label: string }> = []
    // render the matrix with onOpenDocument={(docKind, context) => opened.push(...)}
    // click the cell in the `Hợp đồng` column of criterion #2
    // expect opened[0].docKind === 'contract'
  })

  it('does nothing when the Excel cell is clicked', () => {
    // click the `Excel` cell; expect onOpenDocument not to have been called
  })

  it('asks for the summary tab when the roster-level cell is clicked', () => {
    // click the `Bảng Kê Thu Mua` cell; expect onShowSummary to have been called
  })
```

Fill these in against the file's real fixtures — read it first and follow how it already renders
the matrix and finds cells. Do not invent a rendering helper that is not there.

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/criteriaMatrix.test.tsx
```
Expected: FAIL — the props do not exist.

- [ ] **Step 3: Implement**

`CriteriaMatrix` gains two optional props:

```tsx
  onOpenDocument?: (docKind: EvidenceKind, context: { label: string; note?: string; value?: string }) => void
  onShowSummary?: () => void
```

In the cell's `onClick`, call `cellAction(cell.document, cell.status)` from Task 1 and dispatch:
`open` → `onOpenDocument(docKind, { label: `${row.label} · ${cell.document}`, note: cell.note, value: cell.value })`;
`summary` → `onShowSummary?.()`; `none` → do nothing.

**Decide what happens to the detail row and say which you chose in your report.** The safe option
is to keep it: the caret still opens it, and the glyph now opens the document. The other option is
to retire it, since the popup now carries the note and value. Either is defensible; a silent choice
is not.

`FolderReview` owns the state and mounts the dialog, since it is what renders `CriteriaMatrix`
(line 273) and already has `caseId` and `packetIndex`:

```tsx
const [docPopup, setDocPopup] = useState<{ docKind: EvidenceKind; context: … } | null>(null)
```

Mount `PacketDocsDialog` when `docPopup` is set, passing `initialDocKind`, `context`, and **no**
`onOpenPacket` — the reviewer is already in this packet.

- [ ] **Step 4: Run the tests**

```bash
node_modules/.bin/vitest run
node_modules/.bin/tsc -b
```
Expected: your baseline plus the new tests; `tsc -b` exits 0

- [ ] **Step 5: Commit**

```bash
git add src/components/CriteriaMatrix.tsx src/components/FolderReview.tsx src/components/criteriaMatrix.test.tsx
git commit -m "feat(criteria): open a cell's document from the matrix"
```

---

## Task 4: The Dạng bảng grid does the same

This one **replaces** existing behaviour rather than adding to it. `src/components/PacketGrid.tsx`
line 68 currently calls `onOpenEvidence(row.fieldKey, cell.sourceIndex!)`, which opens the evidence
viewer focused on the value's bounding box. The decision is full document, no autofocus.

Two facts, both checked, that make this smaller than it looks:

- The grid already knows which document each column is — `grid.columns[columnIndex].docId`. Pass it
  straight through. **Do not import `criteriaDocument.ts` here.**
- A cell with no `sourceIndex` already renders a plain `<span>`, not a button, so `na` cells are
  unclickable today and stay unclickable. That matches Task 1's rule for `na` without any extra code.

**Files:**
- Modify: `src/components/PacketGrid.tsx`
- Modify: `src/components/PacketDocsDialog.tsx`
- Modify: `src/components/FolderReview.tsx`
- Modify: `src/components/PacketGrid.test.tsx`

- [ ] **Step 1: Check this is still wanted before deleting the old path**

Read every use of `onOpenEvidence` in `FolderReview.tsx` and see what else reaches the focused
viewer. **If removing the grid's call is the only way a reviewer can get a value's bounding box
highlighted, stop and report it** — the reviewer asked for a full-document popup here, not for the
loss of bbox focus everywhere. Say in your report which it turned out to be.

- [ ] **Step 2: Write the failing test**

Add to `src/components/PacketGrid.test.tsx`, in that file's existing style:

```tsx
  it('asks to open the document for the column the cell sits in', () => {
    const opened: string[] = []
    // render the grid with onOpenDocument={docId => opened.push(docId)}
    // click a status button in the second column
    // expect opened to equal [grid.columns[1].docId]
  })

  it('leaves a cell with no source unclickable', () => {
    // an `na` cell renders a <span>, never a <button> -- assert that is still true
  })
```

Fill these in against the file's real fixtures — read it first and follow how it already builds a
`PacketGridModel` and finds cells. Do not invent a helper that is not there.

- [ ] **Step 3: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/PacketGrid.test.tsx
```
Expected: FAIL — `onOpenDocument` does not exist, so nothing is pushed.

- [ ] **Step 4: Implement**

`PacketGrid` swaps `onOpenEvidence` for:

```tsx
  onOpenDocument: (docId: string) => void
```

and the cell's `onClick` becomes `onClick={() => onOpenDocument(grid.columns[columnIndex].docId)}`.
Keep the `title` accurate — it already says `mở chứng từ`, which is now literally true.

`PacketDocsDialog` gains one more optional prop, introduced here because this is the task that first
uses it (`noUnusedLocals` makes an unused prop added early a build error):

```tsx
  /** Open on this exact document. Wins over `initialDocKind` when both are
   *  given; falls back to the first document when the id is not in the packet. */
  initialDocId?: string
```

`FolderReview` reuses the same `docPopup` state Task 3 added, setting `initialDocId` instead of
`initialDocKind`.

- [ ] **Step 5: Run the tests**

```bash
node_modules/.bin/vitest run
node_modules/.bin/tsc -b
```
Expected: your baseline plus the new tests; `tsc -b` exits 0

- [ ] **Step 6: Commit**

```bash
git add src/components/PacketGrid.tsx src/components/PacketDocsDialog.tsx src/components/FolderReview.tsx src/components/PacketGrid.test.tsx
git commit -m "feat(grid): open the document from a Dạng bảng cell"
```

---

## When you are done

Say plainly:

- which of the four recorded decisions you implemented, and whether any turned out to be wrong once
  on screen
- what you did about the detail row in Task 3
- whether Task 4 cost the reviewer anything that had no replacement
- your real test numbers, and the baseline you compared them against

---

## Outcome — completed 2026-08-29

**All four tasks landed and met the stated goal.** Task 1 `3944442`; Task 2 `ed49ef9`;
Task 3 `0b51a5d`; Task 4 `4adafa3`. Clicking a ✓ / ✗ / ? / ! in the matrix and in the Dạng bảng grid
opens that cell's document full-page, carrying the cell's note and value into the popup header, with
no autofocus on the value.

**The seams section was right, and one plan later the seam it names had to be split.** It records
that `PacketDocsDialog` "already satisfies the no-autofocus decision with no work", because
`focusBbox` stays `null` and `lockView` stays `false` for the dialog's whole life. Correct, and
correct for this plan's scope: nothing here needed a box, only the right document.

The signature-anchor work that followed did need one, and found that `EvidenceViewer` conflated two
things under `overviewMode` — *do not jump to the value* and *do not outline it*. Since the
packet-docs popup runs `overviewMode` permanently, every anchor computed for #21–#25 reached nobody:
the right document opened on the right page with no box on it. Fixed in `50b5627` by adding
`showFocusInOverview`, which draws the outline without scrolling, leaving `docs/ver3-scope.md` §2's
no-autofocus decision intact rather than reverting it. Asserted both ways — the outline appears, and
`scrollIntoView` is not called.

Recorded here because a reader of this plan would otherwise conclude the popup can never show a box,
which was true when it was written and is no longer.

**Baseline.** Green at `eb05f7d`: **380 frontend across 38 files**, **864 backend**
(`cwd=server/`). The plan's stated 821 was never reproducible in this checkout.
