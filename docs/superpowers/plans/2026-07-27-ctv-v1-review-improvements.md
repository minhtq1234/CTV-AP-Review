# CTV v1 Review Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the five approved historical-v1 review-screen improvements while preserving its field-keyed data and backend behavior.

**Architecture:** Keep review state and evidence-source navigation in `FolderReview`, move packet context into a compact reusable header, and replace transform-only single-page rendering with a scroll-native page layout. Pure document-layout helpers provide deterministic grouping, clamping, and overlay geometry; focused server-rendered component tests cover the user-visible contracts.

**Tech Stack:** React 18, TypeScript 5, CSS, Vitest 2, React DOM server rendering, Vite 5.

## Global Constraints

- Work only in `/Users/lap16603/Documents/New project/work/CTV_APReview-v1`, detached at `b474102a0a73a3898bc04dd11fb676881d3d65e9`.
- Do not modify `/Users/lap16603/Documents/New project/work/CTV_APReview`.
- Preserve the existing uncommitted `src/upload/api.ts` change that points v1 to backend port 8001.
- V1 frontend is 5174; v2 remains 5173/8000.
- Preserve `review.fields`, ranking, evidence sources, completion/report behavior, keyboard shortcuts, flags, autosave, backend contracts, and processed cases.
- Do not expose or copy real PII.
- Do not push.

---

### Task 1: Lock the document-layout behavior with pure tests

**Files:**
- Create: `src/logic/documentView.test.ts`
- Create: `src/logic/documentView.ts`

**Interfaces:**
- Produces: `DocumentViewMode = 'single' | 'paired'`
- Produces: `DOCUMENT_VIEW_MODES`
- Produces: `groupPageIndexes(pageCount, mode): number[][]`
- Produces: `clampPageIndex(page, pageCount): number`
- Produces: `bboxPercentStyle(bbox, width, height): { left; top; width; height }`

- [ ] **Step 1: Write failing tests**

Test literal mode labels `1 trang` and `2 trang`, complete one-page grouping
`[[0], [1], [2]]`, complete paired grouping `[[0, 1], [2]]`, stale-page
clamping, and hand-derived bbox percentages.

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/logic/documentView.test.ts`

Expected: FAIL because `./documentView` does not exist.

- [ ] **Step 3: Add the minimal pure helpers**

Implement the exact interfaces above without React or DOM dependencies.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- src/logic/documentView.test.ts`

Expected: all document-view tests pass.

### Task 2: Lock field-panel, mapping-pill, and compact-header presentation

**Files:**
- Create: `src/components/ReviewHeader.tsx`
- Create: `src/components/reviewPresentation.test.tsx`
- Modify: `vite.config.ts`
- Modify: `src/components/FolderFieldsPanel.tsx`
- Modify: `src/components/MatchKeyStrip.tsx`

**Interfaces:**
- `MatchKeyStrip({ matchedBy })` renders exactly one mapping pill.
- `ReviewHeader` consumes folder identity, `[start, end]` packet pages, packet
  position/count, back/previous/next callbacks, and mapping status.
- `FolderFieldsPanel` keeps `onSelect` but no longer consumes or renders source
  focus buttons.

- [ ] **Step 1: Enable `.test.tsx` discovery and write failing static-render tests**

Use `renderToStaticMarkup` with synthetic fixtures. Assert:

- no `Đối chiếu` or source document pills;
- selected field rows still render;
- `⚑ Đánh dấu` and `Bỏ đánh dấu` appear in their respective states;
- each `MatchedBy` value produces its exact approved label;
- mapping markup contains no table;
- the compact header contains `HỒ SƠ CTV`, product/range, and packet controls.

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/components/reviewPresentation.test.tsx`

Expected: FAIL on old source chips, old flag labels, old name-match copy, identity
table, or missing compact header.

- [ ] **Step 3: Implement minimal presentation changes**

Remove only the visual source block and obsolete props. Expand the flag target and
conditional label. Make `MatchKeyStrip` pill-only. Add `ReviewHeader`.

- [ ] **Step 4: Verify GREEN**

Run: `npm test -- src/components/reviewPresentation.test.tsx`

Expected: all presentation tests pass.

### Task 3: Build the complete scroll-native document viewer

**Files:**
- Create: `src/components/evidenceViewer.test.tsx`
- Modify: `src/components/EvidenceViewer.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- `EvidenceViewer` retains its existing external focus, document-tab, lock,
  roster, and shortcut props.
- It internally owns `DocumentViewMode`, zoom, highlight, roster, pan, and help
  state.
- Each page wrapper uses `data-page-index`; the focused wrapper receives
  `data-active-page="true"`.

- [ ] **Step 1: Write failing viewer markup tests**

Render a synthetic three-page document and assert both mode buttons, all three
images, all existing toolbar aria-labels, and the default `100%` value are
present.

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/components/evidenceViewer.test.tsx`

Expected: FAIL because the old viewer renders only one page and has no modes.

- [ ] **Step 3: Implement scroll layout and focus behavior**

Render all page groups from `groupPageIndexes`. Use page refs plus
`scrollIntoView({ block: 'center' })` on active document/page/focus changes when
unlocked. Apply bbox percentage styles to the active page highlight and roster
callout. Implement zoom-width scaling, 100% fit, and drag-to-scroll pan while
retaining all shortcut handlers and document tabs.

- [ ] **Step 4: Apply toolbar and responsive styling**

Create the floating white toolbar, 36 px targets, active states, one-column and
paired-row page layouts, vertical scroll container, sticky compact header, and
larger flag action. Add a desktop breakpoint that keeps header navigation usable
and collapses paired pages only when the viewport cannot support them.

- [ ] **Step 5: Verify GREEN**

Run: `npm test -- src/components/evidenceViewer.test.tsx src/logic/documentView.test.ts`

Expected: all viewer/layout tests pass.

### Task 4: Integrate the compact shell in live and offline flows

**Files:**
- Modify: `src/components/FolderReview.tsx`
- Modify: `src/components/UploadFlow.tsx`
- Modify: `src/components/DemoFlow.tsx`
- Modify: `src/styles.css`

**Interfaces:**
- `FolderReview` no longer renders a header or needs identity-match props.
- `UploadFlow` renders `ReviewHeader` from existing `PacketMeta.pages`,
  `matchedBy`, packet position, and navigation callbacks.
- `DemoFlow` renders the same header with synthetic folder data.

- [ ] **Step 1: Add failing integration expectations to presentation tests**

Assert only one header row owns back, packet identity, mapping, and previous/
current/next navigation; assert old expanded header markup is absent.

- [ ] **Step 2: Verify RED**

Run: `npm test -- src/components/reviewPresentation.test.tsx`

Expected: FAIL while the flows still contain the stacked bars.

- [ ] **Step 3: Wire the new header and preserve review behavior**

Replace `review-back-bar` plus `screen-head` with `ReviewHeader`; pass the packet
range from live metadata and a synthetic range in the offline demo. Keep
`flushReview`, `setReviewState`, field focus, flags, completion, and actions
unchanged.

- [ ] **Step 4: Verify focused suites**

Run: `npm test -- src/components/reviewPresentation.test.tsx src/components/evidenceViewer.test.tsx src/logic/documentView.test.ts`

Expected: all focused tests pass.

### Task 5: Full verification and browser QA

**Files:**
- Modify only if verification exposes a tested defect in the files above.

**Interfaces:**
- No new interfaces.

- [ ] **Step 1: Run the full v1 test suite**

Run: `npm test`

Expected: zero failed tests.

- [ ] **Step 2: Build v1**

Run: `npm run build`

Expected: TypeScript and Vite exit 0.

- [ ] **Step 3: Launch isolated services**

Run the v1 backend on `127.0.0.1:8001` and Vite on `127.0.0.1:5174`, without
stopping or changing v2 services.

- [ ] **Step 4: Browser QA**

At `http://127.0.0.1:5174/`, verify:

- both modes render and vertically scroll the complete active document;
- selected-field focus scrolls to the target page with highlight and roster callout;
- document tabs and source keyboard shortcuts still navigate;
- flag toggle copy, warning style, reason editor, and autosave interaction work;
- back/previous/current/next controls and mapping pill share one sticky row;
- desktop resizing retains usable panes/header/toolbar;
- browser console and page error collections are empty.

- [ ] **Step 5: Audit the final diff**

Run `git status --short`, `git diff --check`, and `git diff -- src/upload/api.ts`.
Confirm no v2 files changed and the 8001 edit is preserved.

## Plan Self-Review

- Spec coverage: Tasks 2–4 cover all five UI requirements; Task 5 covers every
  required verification and preservation check.
- Placeholder scan: no deferred implementation decisions or placeholder steps.
- Type consistency: `DocumentViewMode`, `ReviewHeader`, and retained
  `EvidenceViewer` props are named consistently throughout.
