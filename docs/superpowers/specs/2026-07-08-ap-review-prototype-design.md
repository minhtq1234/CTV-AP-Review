# AP Review Prototype — Design Spec

- **Date:** 2026-07-08
- **Status:** Design approved; ready for planning
- **Read first:** [`PROJECT_BRIEF.md`](../../../PROJECT_BRIEF.md) — full background, problem, and locked decisions. This spec extends it with the decisions confirmed in the design session and the concrete contracts the build needs.

---

## 1. Goal

Show the reference product's core behavior, applied to Accounts Payable:

> AI finds each claimed value in the evidence, extracts it, and marks its position. The ACC
> reviewer sees every value with the document auto-focusing where it came from, and approves or
> rejects — spending attention only on what doesn't match.

## 2. Scope

A **throwaway clickable prototype** (build strategy C): single-page app, seeded cases, fake
(seeded) AI predictions, **no backend, no auth**. It validates the *UX and workflow*, not real
extraction accuracy. The data model, verdict logic, and review UX are built so they could graduate
to a real app (option B) without a redesign — but that graduation is explicitly out of scope here.

## 3. Decisions confirmed this session (on top of the brief)

| Decision | Choice |
|---|---|
| **Approve gate** | **None.** Approve and Reject are always enabled; exception-first ordering does the nudging. |
| **Document rendering** | Generated **crisp receipt/invoice/form image files** (Vietnamese text, VND amounts), loaded via `<img>`. Boxes hand-placed in each image's natural-pixel space. |
| **Verdict states** | **Four** — the brief's `✓ / ~ / ⚠` plus an explicit `✗ mismatch`. |
| **Stack** | **Vite + React + TypeScript**, in-memory seeded cases, run with `npm run dev`. Throwaway, but shaped like the option-B graduation target. |

## 4. The review screen

Two panes plus a top header and a bottom action bar (see the approved mockup):

- **Header** — case id, requester, expense category, status pill.
- **Left — fields panel.** A summary line (`N trường · X lệch · Y tin cậy thấp`) then one row per
  field: verdict chip · label · `expected → actual` values · confidence. Ordered **exception-first**.
  Clicking a row selects that field.
- **Right — document viewer.** The merged multi-page document on a neutral mat. Selecting a field
  auto-focuses (pans/zooms) to its box on the correct page and highlights it. A floating zoom
  toolbar (fit / − / % / + / spotlight) sits bottom-left; a page indicator top-right.
- **Action bar** — `Từ chối` (Reject) and `Phê duyệt` (Approve). Both always enabled. Approve is
  the accent CTA.

Layout note: brief specifies **left = fields, right = document** (the reference product is flipped;
irrelevant). The document pane is the wider of the two.

## 5. Interaction — mirror the reference product

Copied from the reference `data-entry` surface so the feel is identical:

- **Click a field → auto-focus.** Reuse the reference's `loupeFrame(bbox, natural, viewport)`:
  - No box → fit the whole page at `min(vp.w/nat.w, vp.h/nat.h) * 0.92`, centered.
  - With a box → magnify so the box height ≈ 14% of viewport height, clamped `[1.1, 2.5]`, but not
    past the scale that fits the box (`min(vp.w/bw, vp.h/bh) * 0.92`); center the box's midpoint in
    the viewport. Apply as a CSS `translate(tx,ty) scale(s)` transform from the top-left origin.
  - The highlight rectangle is drawn in viewport space: `left = tx + bbox.x*s`, etc.
- **Keyboard:** `↑` / `↓` = previous / next field; `⌘K` = jump-to-field palette (search + click to
  jump); a spotlight/lock toggle on the toolbar freezes the frame across field changes.
- **Boxes** are stored in **natural image pixels**, one box per field, on the page where the AI
  found the value. Coordinate math and transforms come from the reference verbatim.

## 6. Verdict model

Four verdicts, computed at load time by one **pure function** (kept separate so it survives
graduation):

| Verdict | Chip | Rule |
|---|---|---|
| Match | `✓` green | number / date / text value is exactly equal |
| Fuzzy | `~` gray | name/text is normalized-equal or highly similar but not identical (case, spacing, `Cty`/`Công ty`, diacritics) |
| Mismatch | `✗` red | a number / date / text value is **not** equal — the money catch |
| Low confidence | `⚠` amber | AI confidence `< 0.7` |

**`compareField(expected, prediction, kind) → Verdict`:**

1. `prediction == null` (AI found nothing) → `mismatch`.
2. Compute a **base** verdict by `kind`:
   - `number` — strip separators/₫/spaces, compare numerically → `match` | `mismatch`.
   - `date` — normalize to `DD/MM/YYYY`, compare → `match` | `mismatch`.
   - `text` — trimmed exact compare → `match` | `mismatch`.
   - `name` — normalize (lowercase, collapse whitespace, strip company suffixes/diacritics); exact
     → `match`; else similarity ≥ threshold → `fuzzy`; else → `mismatch`.
3. Apply **precedence** (most severe wins): `mismatch > low_conf > fuzzy > match`. So a matching but
   low-confidence field shows `⚠`; a wrong low-confidence field shows `✗`.

**Exception-first ordering:** sort by verdict severity `✗ → ⚠ → ~ → ✓`, ties broken by page then
box position (top-to-bottom).

## 7. Actions

- **No gate** — both actions always enabled.
- **Reject** opens a small **optional** reason field.
- **Terminal** — a case moves to `approved` / `rejected`; no send-back or correction loop.

## 8. Case JSON schema (the contract)

The same shape drives the mock and any future real app. Verdicts are **derived, never stored**.

```ts
type Verdict   = 'match' | 'fuzzy' | 'mismatch' | 'low_conf'
type FieldKind = 'number' | 'date' | 'text' | 'name'

interface Prediction {                 // the AI side (seeded JSON)
  value: string
  page: number                         // 0-based page index
  bbox: { x: number; y: number; width: number; height: number }  // natural px
  confidence: number                   // 0..1
}

interface CaseField {
  key: string
  label: string                        // Vietnamese field label
  kind: FieldKind
  expected: string                     // typed request-form value
  prediction: Prediction | null        // null = AI found nothing
}

interface DocPage {
  src: string                          // image asset path
  width: number                        // natural px
  height: number                       // natural px
  label?: string                       // e.g. "Đề nghị", "Hóa đơn", "Ảnh chụp"
}

interface Case {
  id: string
  title: string
  requester: string
  category: string
  status: 'pending' | 'approved' | 'rejected'
  pages: DocPage[]
  fields: CaseField[]
}
```

## 9. Seed cases (every verdict state gets demonstrated)

Fields per case: `Nhà cung cấp` (name), `Số hóa đơn` (text), `Ngày hóa đơn` (date),
`Tiền hàng` (number), `Thuế GTGT` (number), `Tổng cộng` (number).

1. **Clean** — catering / office-supplies receipt. All `✓`, with the vendor as a `~` fuzzy pass
   (e.g. `Highlands` vs `CÔNG TY CP HIGHLANDS COFFEE`). Shows the reviewer blowing past matches.
2. **Mismatch** — the Grab travel case: claimed `Tổng cộng` 2.500.000₫ vs receipt 2.050.000₫ → `✗`;
   `Số hóa đơn` low confidence 0.52 → `⚠`; vendor `~`; date / subtotal / VAT `✓`. The money catch.
3. **Low confidence** — a crumpled/handwritten receipt where the amount **does** match but AI
   confidence is ~0.5 → `⚠`, forcing the reviewer to eyeball the source.

Each case is 2 pages (request form + receipt); the mismatch case gets a 3rd page to exercise
multi-page navigation. All content Vietnamese, VND.

## 10. Documents

- Generated as crisp image files (one per page) at fixed natural-pixel dimensions.
- Field boxes are authored in the **same** natural-pixel coordinate space, so `loupeFrame` lands
  exactly.
- One clean **image-swap point**: the case seed references `DocPage.src` + natural size, so real
  scanned images could replace the generated ones later with no code change.

## 11. Out of scope (v1)

- No live model calls — predictions are seeded JSON.
- No submitter/employee app, no correction loop — Approve / Reject only.
- No auth / backend / Keycloak / docker.
- No multi-source field mapping — single merged document, one box per field.

## 12. Structure

Single-page Vite + React + TS app. Suggested modules (final layout decided in the plan):

- `data/cases.ts` — the seeded `Case[]` (the contract in action).
- `logic/verdict.ts` — `compareField` + ordering (pure, unit-testable).
- `logic/loupe.ts` — `loupeFrame` + frame math (pure, unit-testable).
- `components/FieldsPanel`, `DocViewer`, `FieldPalette`, `ActionBar`, and the screen shell.
- `assets/` — generated document images.

Pure logic (`verdict`, `loupe`) is isolated from React so it's trivially testable and portable —
this is the part that would graduate to a real app unchanged.
