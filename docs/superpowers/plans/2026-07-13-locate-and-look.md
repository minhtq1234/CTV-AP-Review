# "Locate & look" — field navigable on every document (#004) — Plan

> **For agentic workers:** REQUIRED SUB-SKILL: superpowers:test-driven-development for pure logic; UI verified in the browser. Steps use checkbox (`- [ ]`).

**Guiding principle:** The reviewer validates with their own eyes. The tool's job
is to **locate every occurrence of each field across the packet's documents and
guide the eye there** — the OCR'd value and auto-verdict are hints, never the
decision. Locating a **label** ("Ngày sinh", "CCCD số", "MSTTNCN", "TK số", "Số
tài khoản") is far more reliable than reading a handwritten value, so lean on it.

**Goal:** Each field shows a navigable source **per document where its label
appears** — readable (typed) occurrences carry a value + hint verdict; unreadable
(handwritten) occurrences show as **"cần xem"** pointing at the region. The kê khai
value leads as the reference; unread occurrences never hard-fail a field.

---

## Behaviour change (before → after)

- **Before:** a field gets a source only where OCR matched a value pattern.
  Handwritten occurrences (e.g. Ngày sinh on the contract) produce no source → not
  navigable.
- **After:** a field gets **one source per document whose label is present**.
  - typed/read → `value` + bbox + confidence (hint verdict as today);
  - handwritten/unread → `value: ""`, bbox = the region after the label,
    confidence 0 → rendered as **"cần xem"** (navigable, neutral).
  - Field verdict = worst of the **readable** sources; if none readable →
    `review` ("cần xem"). Unread sources are listed as navigable "cần xem" chips
    and **do not** turn a matching field red.

---

## Server — `server/ocr_extract.py`

- [ ] **Add `locate_field(lines, spec) -> list[hit]`** (pure; unit-test in `ocr_extract_test.py`):
  for each line whose text contains the field's label/anchor (accent-insensitive
  via existing `norm`), produce a hit: `{value, bbox, confidence}` where
  - if the field's value pattern matches on/after the label → value + union bbox +
    min-conf (as the current `find_in_lines`);
  - else (label present, value unreadable) → `value=""`, `bbox` = the region from
    just after the last label word to the end of the line (fallback: the label
    words' bbox), `confidence=0.0`.
  Tests: (a) typed line → value populated; (b) label present but no value pattern →
  value "" with a non-degenerate region bbox; (c) no label → no hit.
- [ ] **Rewrite `extract_fields`** to emit **one source per document** per field:
  run `locate_field` across each doc's lines; pick the best hit per doc (prefer a
  read value; else the located-only hit); build a `CtvSource` per doc that has the
  label. Keep `expected` from the roster. If a field's label appears in no document,
  emit a single empty source so it still shows as "cần xem".
- [ ] Keep `classify_page`/`segment_docs`, identity (`cccd`) extraction, and the
  manifest shape unchanged. Update existing tests to the new per-doc behaviour.
- [ ] Commit `feat(ocr): locate each field on every document (read or "cần xem")`.

## Frontend — verdict + rendering

- [ ] **`src/ctv/checks.ts` (+ its test):** add an `'unread'` source result and a
  field-level `'review'` state. A source with empty `value` → `'unread'`. Field
  verdict = worst over **readable** sources (existing match/fuzzy/mismatch/low_conf);
  if there are no readable sources → `'review'`. Order-of-severity for
  `orderFields`/ranking: put `mismatch` and `review` before matches (exceptions +
  "needs eyes" surface first). Unit-test: field with [readable match + unread] →
  overall match, but the unread source is still present/flagged; field with only
  unread sources → `review`.
- [ ] **`src/components/FolderFieldsPanel.tsx`:** for each field, keep the kê khai
  (expected) value leading, then a row of **per-document source chips** — one per
  document — labeled with the document; readable chips colored by their verdict
  (green/amber/red hint), unread chips shown neutral as **"cần xem · <doc>"**.
  All chips remain clickable via the existing `onFocusSource` (loupe jump).
- [ ] **`src/components/EvidenceViewer.tsx`:** unchanged if it already focuses a
  `bbox`; confirm an empty-value source still focuses its region (the located bbox).
- [ ] Ensure a field-level `'review'` renders a clear neutral "cần xem" pill (like
  the exception styling but neutral, not red). `npx tsc -b` clean; `npx vitest run`
  green (update snapshots/expectations as needed).
- [ ] Commit `feat(review): per-document "cần xem" sources; value is a hint, not the gate`.

## Verify (browser, against the real backend)
- [ ] Rebuild is code-only; restart backend (uvicorn :8000) so it serves the new
  extraction, POST the real PDF + v3 roster, open a packet (e.g. Nguyễn Hoàng Phúc).
- [ ] Confirm: **Ngày sinh now shows a source on both Hợp đồng and Biên bản** — the
  Biên bản one read/verdicted, the Hợp đồng one as "cần xem"; clicking each makes the
  loupe land on that document's Ngày sinh region. Same for CCCD/MST/TK across the 3
  docs. Confirm an all-match field isn't turned red by an unread copy. Screenshot.
- [ ] PII: real data stays in the backend temp dir / scratch; commit code only.

## Notes
- Do not remove value-matching — it stays as the hint/priority cue for typed reads.
- Keep the existing synthetic CTV folders working (they have real values + bboxes;
  they'll simply have no "cần xem" sources).
