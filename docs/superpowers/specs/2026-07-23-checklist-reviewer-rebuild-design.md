# Design — checklist reviewer rebuild

**Date:** 2026-07-23
**Status:** draft for review
**Inputs:** [`review-checklist.md`](../../review-checklist.md) (the coded checks),
the Claude-generated reviewer mockup ("Reviewer (offline)"), and the scope decisions
in that discussion.

## Goal

Replace the reviewer's **flat 6-field list** with the **two-tier coded checklist** the
Acc team actually works: a **Preconditions (gates)** group pinned on top and a
**Detail checks** group below, each row a coded check item with a status, rendered in
the cleaner visual direction from the mockup — while keeping the **real scanned
document** as the evidence pane.

## Non-goals (deferred — explicit)

- **Mode B — the 3-way consistency view** (C3, E1). Backlog. C3/E1 do not appear as
  first-class checks in v1.
- **Gate-fail special flow.** A failed gate needs no dedicated send-back path; the
  reviewer flags it and uses the normal report/export. (Reviewer's call.)
- **CV / detection** for signatures, seals, templates. All such checks are
  locate-and-look (navigate to the document/region; the human confirms).
- **Pixel-precise region location** for checks we don't already extract (signature
  blocks, specific date fields). v1 routes those to the **right document tab**; tighter
  region anchoring is a later refinement.
- **VNG brand** palette. Use a calm, considered accent now (not the mockup's random
  pink); brand can be swapped later.
- **A3** (bank vs. history — needs Acc DB) and **F1** (ZA calc) remain out.

## The checklist model (data)

A packet's manifest gains a **`checks: CheckItem[]`** array (built by a new backend
**checklist builder** from the existing per-packet OCR fields + match key + segmented
documents). The reviewer renders `checks` grouped by tier; the old flat `fields` stay
in the manifest as the raw source the builder reads.

```ts
type CheckTier = 'gate' | 'detail'
type CheckKind =
  | 'value'      // has a reference (roster) value + a located source on a doc; auto match hint
  | 'identity'   // driven by the match key (G-ID)
  | 'confirm'    // locate-and-look: navigate to a doc/region, human marks Đạt or flags

interface CheckItem {
  code: string            // 'G-DOC' | 'G-ID' | 'D3' | 'B3' | 'C2' | 'A1' | 'A2' | 'B1' | 'B2' | 'C1' | ...
  label: string           // Vietnamese, e.g. "Hợp đồng đủ chữ ký & con dấu"
  tier: CheckTier
  kind: CheckKind
  evidenceDocId: string    // which document tab this check lives on
  reference?: string       // roster ("bảng kê") value, for kind 'value'
  source?: CtvSource | null // located value+bbox on the doc, for kind 'value' (reuse existing shape)
  autostatus?: 'match' | 'mismatch' | 'review'  // hint for 'value'/'identity' (never a verdict)
}
```

**Per-check review state** (replaces the field-keyed version). Keyed by **check code**:

```jsonc
"review": {
  "done": false,
  "items": { "<code>": { "seen": true, "flag": null | { "reason": "", "note": "" } } }
}
```

- `seen` — set when the reviewer focuses the check (same auto-on-focus behavior).
- `flag` — the check is marked "cần gửi lại" with reason + note.
- Derived per-check status shown in the row: **Đạt/Khớp** (seen, no flag, autostatus not mismatch) · **Cần xem** (unseen, or value autostatus=review) · **Đã đánh dấu** (flagged) · **Lệch** (autostatus=mismatch, pre-flag hint).
- Packet outcomes unchanged in spirit: **Clear** (all seen, no flags) / **Send back** (any flag). "Seen everything" still gates *Clear* only.

## v1 checklist (which checks, and where their data comes from)

**Tier 1 — Preconditions (gates):**

| Code | Label (VN) | Kind | Evidence tab | Data source |
|------|-----------|------|--------------|-------------|
| G-DOC | Đủ chứng từ bắt buộc | confirm | (packet) | segmented doc set — reviewer confirms none missing |
| G-ID | Đúng người — CCCD & tên khớp | identity | Hợp đồng | match key (`matchedBy` + OCR/roster identity) |
| D3 | Cam kết TNCN đúng mẫu năm hiện hành | confirm | Bản cam kết | navigate to cam-kết; human confirms current-year template |
| B3 | Hợp đồng đủ chữ ký & con dấu | confirm | Hợp đồng | navigate to contract signature area |
| C2 | BBNT đủ chữ ký, con dấu & giáp lai | confirm | BBNT | navigate to BBNT signature area |

**Tier 2 — Detail checks** (reuse existing extracted fields where possible):

| Code | Label (VN) | Kind | Evidence | Data source |
|------|-----------|------|----------|-------------|
| B1 | Họ tên khớp bảng kê | value | Hợp đồng | existing `name` field |
| A1 | Số CCCD khớp giữa chứng từ | value | Hợp đồng ↔ CCCD | existing `cccd` field |
| A2 | Mã số thuế khớp bảng kê | value | Hợp đồng | existing `mst` field |
| B2 | Phí dịch vụ khớp bảng kê | value | Hợp đồng | existing `phi` field |
| BANK | Số tài khoản khớp bảng kê | value | Hợp đồng | existing `tk` field — *value-match only; A3 vs-history is pending* |
| INFO | Ngày sinh khớp hồ sơ | value | Hợp đồng | existing `ngaysinh` field — *supporting CTV info; not a distinct Acc code* |
| C1 | Nội dung & thời gian khớp BBNT | confirm | BBNT ↔ Hợp đồng | navigate to BBNT; human compares to contract |
| D1 | Thông tin & MST khớp cam kết | confirm | Bản cam kết | navigate to cam-kết; human confirms vs CTV file |

**Field ↔ code note:** our current extraction (`name, cccd, mst, tk, ngaysinh, phi`)
doesn't 1:1 cover the Acc codes — `tk`/`ngaysinh` have no canonical Acc code (shown as
`BANK`/`INFO`), and several Acc checks (C1, D1, the gates) have no extracted value so
they're `confirm` items. The builder maps what maps and routes the rest to the right
document tab. C3, E1 (content consistency) omitted in v1 (Mode B backlog); B4/D2
temporal checks can be added as `confirm` items later.

## Backend changes

- **New `server/checklist.py`** (pure): `build_checklist(fields, match, docs) ->
  list[CheckItem]` — maps the existing packet data into the coded, tiered check items
  above. Pure + unit-tested (no OCR/IO). The pipeline calls it and writes `checks` into
  each packet's `manifest.json` alongside `fields`.
- **`server/cases.py`:** review state keyed by check **code** under `review.items`
  (was `review.fields`); status/progress derive from `items`. Migration: existing
  cases' `review.fields` reset to `review.items = {}` (throwaway prototype).
- **`server/app.py`:** the `PUT …/review` body carries `{done, items}`; the report
  builder reads flagged **checks** (code + label + evidence + reason + note) instead of
  fields. Report endpoints otherwise unchanged.
- **Manifest URL rewrite** unaffected (checks reference existing docs/pages).

## Frontend changes (the two-tier reviewer)

Rebuild the reviewer around the mockup. Keep the existing **scan-based
`EvidenceViewer`** (real scanned page + highlight + roster callout + tabs + zoom) — the
document pane shows the **actual scan**, never a transcription. Apply the mockup's
inline mismatch callout *on* the scan.

- **Header:** back · "HỒ SƠ CTV · {name} · {product} · trang {range}" · **match-key
  badge** ("Danh tính khớp" / weak) · packet nav (Gói trước/sau · n/N).
- **Left — checklist pane:** progress meter ("k/N đã xem"); a **Preconditions card**
  (tinted, pinned top, with an "Đủ điều kiện" summary) listing the Tier-1 gates; then
  **"Kiểm tra chi tiết"** listing Tier-2 items. Each row: icon/status · label ·
  (for `value`) "Bảng kê: {reference}" + match hint · a flag button. Selected row
  drives the doc pane; focusing a row marks it seen.
- **Right — scan pane:** unchanged `EvidenceViewer`, focused to the selected check's
  evidence doc/region; roster callout shows the `reference` value for `value` checks.
- **Action bar:** "Gửi lại — lỗi chi tiết" + primary "Xuất & gửi lại"; hotkey hint row.
- **Hotkeys:** ↑↓ items · ←→ documents · F flag · B box · V roster value (unchanged).
- **Components:** refactor `FolderReview` + `FolderFieldsPanel` into a checklist-driven
  panel (`ChecklistPanel` with a `PreconditionsCard` + `DetailList`); `MatchKeyStrip`
  becomes the header badge; `ActionBar` unchanged in role.
- **Accent:** a calm considered accent (not pink); tokens so brand can swap later.
- **Offline export (DemoFlow):** update the synthetic folders to carry `checks` so the
  offline demo renders the same checklist.

## Testing

- **Pure (unit):** `build_checklist` (server) — correct tiers/kinds/codes/evidence from
  sample fields+match+docs; per-check status derivation + all-seen gate (frontend
  `review.ts`); report builder over flagged checks.
- **Browser:** open a packet → Preconditions card on top with the 5 gates; detail list
  below; focusing rows fills the meter and moves the scan pane to the right document;
  a `value` check shows the roster callout on the scan; flag a check → "Đã đánh dấu" →
  export report lists it by code+label. Confirm G-ID reflects a real match/mismatch
  (the name-only packet shows the weak badge).

## Migration / compatibility

Existing on-disk cases were OCR'd before `checks` existed. On load, if a packet lacks
`checks`, the backend builds them from its stored `fields`/match meta (no re-OCR
needed) and rewrites the manifest; `review` resets to the new `items` shape.

## Open items

- Tighter region anchoring for `confirm` gates (signature blocks, template band) —
  refinement after v1.
- B4/D2 temporal checks — add as `confirm` items if the Acc team wants them surfaced.
- VNG brand accent — swap when provided.
