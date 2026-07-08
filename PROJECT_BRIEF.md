# Accounts Payable (AP) Review Prototype — Project Brief

> Captured from a brainstorming session on **2026-07-08**. This is a **separate project** from
> `paperlabelannotate` (the reference product), spun off into its own folder. This file is the
> complete, self-contained context — a fresh session should read it first, finish the design,
> then plan and build.

---

## The problem

At VNG, an employee submits a **payment request** (e.g. a reimbursement) with supporting
evidence — receipts, photos, an email. The **ACC (accounting) team** then has to review the
submission and **verify the numbers match the evidence** before approving. Today that
cross-checking is manual and slow: a reviewer reads each attachment, finds the relevant value,
and mentally compares it to what was claimed.

## The goal

A prototype that shows the same core behavior we built into the reference product, applied to AP:

> **AI finds the data, extracts each value, and marks its position. The ACC reviewer sees each
> value with the document auto-focusing on where it came from, and approves or rejects — spending
> attention only on what doesn't match.**

## The concept in one paragraph

A **case** = a typed **request form** (the employee's claimed / *expected* values) + one **merged
multi-page document** (request + receipts + photos + email, stitched into a single paginated image
surface). **AI predictions** arrive as **JSON** — for each field: the extracted value, page,
bounding box, and confidence (pre-computed; nothing calls a model live in the review loop, exactly
like the reference product ingests predictions). The app **matches** each expected value from the
form against the AI-extracted value → a per-field **verdict**. **ACC** reviews exception-first:
flagged fields surface at the top; the reviewer clicks a field, the document **auto-focuses** its
box, they confirm or note it, then hit **Approve** or **Reject**.

---

## Decisions locked (from brainstorming)

| Question | Decision | Why |
|---|---|---|
| **Core check** | **Match request fields vs. receipts** (field-level, not just a total) | Multiple values to verify → the click-to-auto-focus UX earns its keep. |
| **Submission** | **Typed request form** is the *expected* side; AI only extracts from the attachments | Clean, unambiguous "expected" values; only one side needs extraction. |
| **AI verdict** | **Auto-verdict + exception-based review** | Biggest time-saver: reviewer blows past matches, focuses on flags. |
| **Verdict rules** | ✓ exact match on **numbers & dates**, ~ fuzzy on **names/text**, ⚠ **low-confidence** | Trust the math; don't over-trust fuzzy string matching. |
| **Lifecycle** | **Approve / Reject only** (terminal; no send-back / correction loop) | Simplest lifecycle; no submitter app or resubmit plumbing. |
| **Evidence model** | **Single merged multi-page document**; fields point to page + box | Simplest viewer — reuses the reference product's paginated surface almost verbatim. |
| **Build strategy** | **C — throwaway clickable mock** (fastest pitch artifact) | See the note below. |

### Build-strategy note (important)

The chosen build strategy is **C — a throwaway clickable mock**: one page, seeded cases, fake
predictions, no backend. It's the fastest way to a demo, but the tradeoff is that it **fakes the
extraction**, so it validates the *UX and workflow*, not real AI accuracy.

Crucially, **the data model, verdict logic, and review UX are all independent of the A/B/C choice.**
So if the mock earns buy-in it can graduate without a redesign:

- **A — Fork the full product**: add an `ap_review` mode/route inside `paperlabelannotate`,
  reusing its auth/backend/viewer in place. Most production-ready; drags in Keycloak/docker/migrations.
- **B — Standalone lean prototype**: a fresh small Vite+React app that *copies* the proven
  DocViewer / BoxLayer / auto-focus / fields-panel patterns, seeds cases with real prediction JSON,
  and uses a thin/in-memory backend. Credible, interactive, shows real extraction output — without
  the infra drag. **This is the natural "graduate the mock" target.**

---

## Reference material

- **Reference product (same product line):** `paperlabelannotate` at
  `/Users/lap16603/Desktop/DAta extraction 2/paperlabelannotate`. It's a single-document
  data-extraction / annotation tool. Its **review surface is the UX model** for the AP review
  screen: a document viewer + a box layer, click-a-field → the doc auto-focuses the box, per-field
  keyboard navigation, a ⌘K jump palette, and a Review list. Predictions come in as JSON.
- **Mock template:** the reference repo contains a single-file React mock at
  `paperlabelannotate/scratchpad/de-anno-real-app.jsx` — a good structural template for a
  throwaway clickable mock (option C).

---

## Out of scope (v1)

- No live model calls — predictions are **seeded JSON**.
- No submitter / employee app and no correction loop — **Approve / Reject only**.
- No auth / backend / Keycloak / docker — it's a mock.
- No multi-source field mapping — single merged doc, **one box per field**.

---

## The review screen (design sketch to finish)

Two panes, mirroring the reference product:

- **Left — Fields panel.** Each row: field label · **expected** value (from the form) ·
  **actual** value (AI-extracted) · **verdict** chip (✓ / ~ / ⚠). Ordered **exception-first**
  (⚠ and mismatches on top). Clicking a row selects the field.
- **Right — Document viewer.** The merged multi-page image with a box layer. Selecting a field
  **auto-focuses** (pans/zooms) to that field's box on the right page and highlights it.
- **Action bar** — **Approve** / **Reject** (Reject may capture a short reason). Approve is gated
  on the reviewer having looked at the flags (define exactly how in the design step).

---

## Suggested next steps (in the new session)

1. **Finish the design** — lock the review-screen layout above, exception-first ordering rule, and
   the exact Approve gate; write it up as a short spec.
2. **Define the case JSON schema** — request-form fields (expected) + predictions (value, page,
   box, confidence) + computed verdicts. This schema is the contract even for the mock.
3. **Seed 2–3 realistic AP cases** — one clean (all ✓), one with a mismatch (a ✗), one with a
   low-confidence field (⚠) — so the demo shows every verdict state.
4. **Build the mock** — single-page React following the `de-anno-real-app.jsx` template: fields
   panel + document viewer with auto-focus + approve/reject.

> Recommended flow for the new session: run the **brainstorming** skill briefly to confirm the
> screen design against this brief, then **writing-plans** to produce the task-by-task plan, then
> build.
