# Design brief — AP payment-review UI

**For:** a product/visual designer redesigning the reviewer interface.
**Companion:** [`review-checklist.md`](review-checklist.md) — the canonical coded list
of *what* gets checked (A1…F1, tiers, evidence, scope). This brief is the *how*.

---

## 1. What this product is

An internal tool for **VNG's Accounts Payable (AP/Acc) team** to review payments to
collaborators (**CTV** — cộng tác viên). Each period a CTV's paperwork arrives as a
**scanned PDF packet** (contract, liquidation record / BBNT, PIT commitment, no-invoice
statement, tax lookup, appendix, CCCD scan — mostly *handwritten* forms), alongside a
**roster spreadsheet (bảng kê)** of what each CTV claims. One submission bundles
**~30 CTVs**, one 7–9-page packet each. The tool splits the PDF into per-CTV packets,
OCRs them, locates each data field on the scans, and matches each packet to its roster
row. **This brief is about the UI only** — the pipeline is built and stays as-is.

## 2. Who uses it and the core job

- **User:** an AP/accounting reviewer. Detail-oriented, high volume, wants speed.
  Power user — keyboard-driven is welcome.
- **The job:** *"For each CTV, confirm with my own eyes that the documents are valid and
  agree with each other and the roster; where they don't, note exactly what's wrong so
  I can send it back for correction."*
- **Philosophy (keep this):** **"Locate & look."** The tool's value is finding *where*
  each thing lives on each scan and guiding the reviewer's eye there; the reviewer
  validates by eye. **Spend attention only on what doesn't reconcile.**
- The reviewer does **not** approve/reject and does **not** edit data. They **flag**
  problems with a note, then **export a report** to send back to the CTV for
  resubmission.

## 3. The screens today

1. **Case list** — every uploaded submission (name, date, status, progress).
2. **Case detail** — a grid of packet cards (one per CTV): name, page range, status
   badge, match badge; a submission summary + an export-report button.
3. **Reviewer** (core, two panes): left = a flat list of ~6 fields (roster value + per-
   document chips, a "seen" dot + flag ⚑, a progress meter); right = the scanned
   document auto-zoomed to the selected field with a highlight, doc tabs, a floating
   roster-value callout, zoom/pan tools; top-right = a match-key strip; bottom = a Done
   button gated on having seen every field.
4. Keyboard: ↑/↓ fields, ←/→ documents, F flag, B box, V roster value, ⌥P pan, ? help.

*(Screenshots + a walkthrough recording available from the reviewer.)*

## 4. What's wrong today (reviewer, please confirm/expand)

1. **Everything has equal weight** — a mismatch or unread field doesn't stand out from
   fields that are fine; triage is slow.
2. **The left panel is a dense wall of text** — repeated "Kê khai (Excel): …" + near-
   identical doc chips; noisy, low hierarchy.
3. **The roster callout fights the document** — the big pill overlaps and hides parts of
   the scan it's meant to help compare.
4. **The match-key strip is easy to miss** — yet "same name, different CCCD" is one of
   the highest-value catches.
5. **Weak, generic visual language** — system font, hairline greys, no type scale or
   rhythm; small, low-affordance controls.
6. **Colour carries too little / ambiguous meaning** (an earlier version was "too many
   colours, can't tell what is what"). Needs a small, legible semantic palette.
7. **The flat 6-field list no longer matches the real work** — see §5: the Acc team
   works through a **structured, two-tier checklist**, not six fields.

## 5. The review structure to design for (the big change)

The real review (see [`review-checklist.md`](review-checklist.md)) is a **coded
checklist (A1…F1)** the reviewer works, **one packet at a time**, in **two tiers**:

**Tier 1 — Preconditions (gates), pinned to the TOP of each packet.** The reviewer does
these first; if any **fails**, they flag it and may **go straight to the next packet**
(finishing the rest is optional). A structurally-invalid packet isn't worth detail-
checking. The gates:
- **G-DOC** — all required documents present.
- **G-ID** — right person (identity match; a name-only/unmatched match is a gate).
- **D3** — PIT commitment uses the current year's template.
- **B3 / C2** — contract and BBNT are signed & sealed (incl. Legal giáp lai).

**Tier 2 — Detail checks** (only worth doing once gates pass): A1, A2, B1, B2, B4, C1,
C3, D1, D2, E1 — value, cross-document, and temporal checks.

**Packet outcomes:** *Clear* (gates pass, all seen, no flags) · *Send back —
precondition failed* · *Send back — detail issues*. The "seen everything" requirement
gates only the *Clear* path, **not** send-back-at-gate.

### Two review *modes* the screen must support

Different checks need different layouts — this is central to the redesign:

- **Mode A — single-document value check** (most items: A1, A2, B1, B2, B4, D1, D2, and
  the gates): one document focused, the reference value (roster / other doc) shown
  beside the field. *(Roughly what exists — but re-solved so the reference never
  obscures the scan.)*
- **Mode B — multi-document consistency check** (C3, E1; partly C1): the work content is
  free text across **contract ↔ bảng kê ↔ BBNT**, so there's no value to match. A
  **3-way comparison view** shows the three content regions **side by side**. Because
  the raw content is long/differently-worded, a **text LLM summarizes each into a short
  comparable form** (bullet-style), and **each summarized point links back to its
  source region on the scan**. The reviewer judges "same work?" and flags. **The summary
  is a reading aid, never the verdict.** *(This is a new UI pattern — design it fresh.)*

## 6. Redesign goals ("good" looks like…)

- **Gate-first triage.** Opening a packet, the reviewer immediately sees the Tier-1
  gates and can bail early; detail checks are clearly secondary.
- **Attention on what doesn't reconcile.** Fields that are fine recede; mismatches,
  unread items, and identity issues surface.
- **Effortless roster/reference-vs-document comparison** that never hides the evidence.
- **The identity match is first-class** — prominent when weak, quiet when clean.
- **A clear multi-document comparison** for the consistency checks (Mode B) with source-
  linked summaries.
- **A calm, professional visual system** — deliberate type + spacing + a restrained
  semantic palette (≤3 status colours with clear meaning). Trustworthy for finance.
- **Speed preserved** — high-volume power tool; dense-but-legible-and-ranked, not sparse;
  keyboard-first.

## 7. Constraints (don't break these)

- **Vietnamese UI throughout** (labels in the checklist doc are the real strings).
- **Two panes essential** — a checklist pane + a scanned-document pane. The document is
  the source of truth; keep it large and legible.
- **Content is scanned + handwritten**, variable quality, variable document set per CTV,
  multi-page. (The *contract/SOW content* used for C3/E1 is **typed**.)
- **Keyboard-first navigation** must survive.
- **Data & interaction model is fixed** (backend contract): the checklist items, per-
  document sources, the match key, review states (seen / flagged-with-reason-and-note /
  done), the two-tier gate logic, and the export-report action. Design the presentation
  and interaction, not the data.
- **Compute posture:** OCR is local; the **only** cloud/LLM piece is the C3/E1 content
  summary, on **GreenNode** (VNG's AI cloud, PII stays in-house). Everything else stays
  local. The reviewer also has a read-only **offline single-file export**, so the visual
  system must render without a network.
- **Target:** desktop/laptop widths (deskwork).

## 8. Deliverables we'd love

- **The reviewer screen**, end-to-end (highest priority), covering **both modes** (A:
  single-doc value check; B: 3-way consistency) and the **two-tier layout** — Tier-1
  gates pinned on top with a prominent "Gửi lại ngay" on failure, Tier-2 detail below.
- **Case list** and **case detail (packet grid)** to match.
- **A small visual system:** type scale, spacing, a restrained semantic palette, and the
  key components with their **states**:
  - check item: not-started / seen / **gate-failed** / flagged / passed;
  - identity: clean-match / name-only / unmatched;
  - the roster/reference indicator; the match-key strip; the **3-way comparison view**
    (summaries + source links); the action bar; packet status badges.
- Any fidelity (wireframes → hi-fi); Figma or annotated mockups both fine.

## 9. Success criteria

- Opening a packet, the reviewer sees the gates first and can send back a bad one in
  seconds without touching the detail checks.
- A field that needs attention is obvious without reading every row.
- Comparing a value to the document is one glance; the evidence is never obscured.
- The 3-way content check is genuinely easy — three tidy summaries, each traceable to
  the scan.
- A weak identity match is impossible to overlook.
- It looks like a polished, trustworthy finance tool and stays fast over dozens of
  packets.

## 10. Open questions for the reviewer

- Which §4 problems bite most in daily use — and did I miss any?
- Any **brand / visual references** (VNG brand? a tool that looks right)?
- **A3 (bank vs. history)** needs an Acc transfer database — is that coming?
- For **D3**, can we get the correct per-year PIT template as a reference?
