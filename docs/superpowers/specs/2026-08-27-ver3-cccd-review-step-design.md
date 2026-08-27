# Design — ver 3 step 1: the CCCD review step

**Date:** 2026-08-27
**Status:** approved in brainstorming, not yet planned
**Branch base:** `stable/2026-08-25-cccd-idp` @ `f4258bb`
**Scope:** one new screen and its flow wiring. No backend change, no edits to
`CaseDetail`, `PacketTable` or `FolderReview`.

## Why this is small

Ver 3 rebuilds the flow as: case list + upload → **CCCD review** → packet list → packet
detail. Three of those four screens already exist on this branch:

| flow step | already built |
|---|---|
| a. case list + Upload button | `CaseList` (via `UploadFlow`) |
| b. upload screen | `UploadScreen` — already takes pdf + roster + `cccd.xlsx` |
| c2. list view of all packets | `CaseDetail` → `PacketTable` (`d660a8a`, 27 Aug) |
| c3. per-packet detail grid | `FolderReview` → `CriteriaMatrix` + `PacketGrid` |

Only **c1** is missing. CCCD mapping exists today only as `CccdCardPicker` *inside*
`FolderReview` — per-packet, reachable solely after opening a packet. There is no
case-level view of what mapped and what did not.

The GreenNode IDP pipeline is preserved untouched: this step reads the mappings ingest
already produced and does not re-run OCR, matching or extraction.

## Decisions taken (and what each one rules out)

| # | decision | rules out |
|---|---|---|
| 1 | **Insert the step only.** The packet list and packet detail are not rebuilt. | Re-doing `PacketTable`, which shipped 27 Aug; re-doing the mature `FolderReview` |
| 2 | **CCCD cards only.** The reviewer attaches, detaches and reassigns cards. | Correcting a packet's roster identity; confirming page boundaries — both need backend work |
| 3 | **Always first, dismissible.** Every processed case with a workbook opens on the step; "Tiếp tục" dismisses it, remembered per case in `localStorage`. | A hard gate (needs a persisted "no card exists" marker) and a purely derived gate |
| 4 | **Exceptions first, rest collapsed.** Rows needing action on top; everything already attached behind a collapsed section. | A 41-thumbnail screen scrolled on every visit; a pure worklist that hides wrong auto-attaches |

Decision 2 is what keeps this a frontend-only change. Decision 4 preserves the one thing a
pure worklist would lose: a wrong `exact` auto-attach is still findable, just one click away.

## What the backend already provides (verified at `f4258bb`)

No new endpoint, model or migration. The three existing routes cover every action:

- `GET /api/cases/{cid}/cccd-cards` → `{cards: CccdCard[]}`, every card in workbook order:
  `{cardId, state, attachedPacketIndex, number, issues, sides[]}`
- `PUT /api/cases/{cid}/cccd-cards/{cardId}` with `{packetIndex: number | null}` →
  attach, **move**, or **detach** when null. `cccd_manual.assign_card` detaches before
  attaching, so a moved card leaves no evidence behind, and `reconcile_owned_evidence`
  rewrites the affected packet manifests either way. Returns `{cards, cccdSummary}`.
- `GET /api/cases/{cid}/cccd-cards/{cardId}/image/{side}` → the card image

Two properties this design leans on, both confirmed in the code rather than assumed:

- **`assign_card` has no state guard.** Any unattached card may be attached to any packet;
  the only rejection is `packet-already-has-card` (409) and `unknown-packet` (409). So a
  `conflict` card is manually assignable — the reviewer is the authority.
- **`CccdCardPicker` filters the pool on `attachedPacketIndex === null` alone**, not on
  state, so it already offers `suggested` / `manual` / `conflict` cards.

Client-side types already exist too: `CaseDetail.cccdSummary: CccdSummary | null` with
`{status, candidates, attached, unresolved}`, so the gate condition and the header counts
need no new API surface.

## Flow

`UploadFlow`'s `Screen` union gains `'cccd'`:

```
'list' | 'upload' | 'cccd' | 'detail' | 'review'
```

In `openCase(id)`, after the existing `status === 'processing'` early-return:

```
if (d.cccdSummary && !localStorage.getItem(`cccd-reviewed:${id}`)) → setScreen('cccd')
else                                                               → setScreen('detail')
```

A case uploaded without `cccd.xlsx` has `cccdSummary === null` and never sees the step.
"Tiếp tục →" writes the flag and moves to `'detail'`. The packet list gets one **"Thẻ
CCCD"** link back to the step, which does not clear the flag. `'review'` is unchanged, and
`FolderReview` keeps its own in-packet picker.

## The screen — `src/components/CccdReviewScreen.tsx`

**Header.** Case name plus three counts, kept distinct because they answer different
questions: `40/42 thẻ đã gán · 2 thẻ chưa gán · 1 gói chưa có thẻ`. The first two come from
`cccdSummary` (`attached` / `candidates` / `unresolved`); the third is packets minus attached
packet indices, and is the number that actually decides whether work remains.

**Cần xử lý.** Two row kinds, both read-only about *why*, with the action always on the
packet:

1. **A packet with no card** — STT, họ và tên, and "Gán thẻ", which opens the existing
   `CccdCardPicker` unchanged (`caseId`, `packetIndex`, `packetLabel`). The reviewer picks
   by eye from the unattached pool, which is the correct stance: OCR already failed on
   these cards, so the image is the evidence and the number is a hint at best.
2. **An unattached card** — thumbnail, whatever OCR read, its state and its issues in
   Vietnamese. **Informational only.** Every assignment flows packet → card, so no
   packet-chooser UI is needed anywhere. When all packets have cards and some remain
   unattached, they are duplicates or extras and there is nothing to do — which the row
   says plainly.

**Đã gán (40).** A collapsed `<details>`: STT, họ và tên, card thumbnail, OCR number, state
badge, and **Gỡ** (`PUT {packetIndex: null}`). Moving a card to a *free* packet is a single
call — `assign_card` detaches and re-attaches internally — but moving it onto a packet that
already holds a card needs Gỡ on that packet first, since the attach returns
`packet-already-has-card`. This section is how a wrong `exact` attach gets caught.

**Footer.** "Tiếp tục →".

After every action the `{cards, cccdSummary}` response refreshes rows and header together —
no refetch, no chance of the two disagreeing.

### Label vocabulary

| state | label |
|---|---|
| `exact` | Tự động khớp |
| `assigned` | Người dùng gán |
| `suggested` | Gợi ý theo tên |
| `manual` | Cần gán tay |
| `conflict` | Xung đột |

**Corrected 2026-08-27** after implementation review. This table first listed seven codes,
taken from `cccd_matching.py` alone. Issues are in fact appended in three modules, and reading
`mapping["issues"]` out of all 13 real cases in `server/data/cases` found **twelve** distinct
codes in use, of which eight were unlabelled — including `packet-target-not-found` (27
occurrences) and `non-unique-packet-target` (10), the second and fourth most common. Three of
the original seven (`duplicate-cccd`, `duplicate-name`, `ambiguous-pair`) never occur in real
data at all. Unlabelled codes fall through to raw English, so the first version would have put
`packet-target-not-found` in front of a Vietnamese reviewer on most exception rows.

Sides and pairing — `cccd_pairing.py`:

| issue | label |
|---|---|
| `missing-front` | Thiếu ảnh mặt trước |
| `missing-back` | Thiếu ảnh mặt sau |
| `unknown-side` | Không xác định được mặt thẻ |
| `side-inferred-front` | Mặt trước được suy đoán |
| `layout-side-conflict` | Bố cục hai mặt không khớp |
| `ambiguous-pair` | Không ghép được mặt trước/sau |

Reading and identity — `cccd_matching.py`:

| issue | label |
|---|---|
| `no-front` | Không có mặt trước |
| `no-number-region` | Không tìm được vùng số |
| `unreadable-identity` | Không đọc được số |
| `low-cccd-confidence` | Số CCCD đọc được với độ tin cậy thấp |
| `non-12-digit-cccd` | Số trên thẻ không đủ 12 chữ số |
| `no-exact-roster-match` | Số không khớp bảng kê |
| `conflicting-identity` | Danh tính trên thẻ không thống nhất |
| `competing-candidate` | Có ảnh khác cùng tranh gói này |
| `duplicate-cccd` | Trùng số CCCD |
| `duplicate-name` | Trùng họ tên |

Attaching to a packet — `cccd_ingest.py`:

| issue | label |
|---|---|
| `packet-target-not-found` | Không tìm được gói tương ứng |
| `non-unique-packet-target` | Nhiều gói cùng khớp |
| `invalid-roster-key` | Khóa bảng kê không hợp lệ |
| `non-12-digit-roster-cccd` | Số trong bảng kê không đủ 12 chữ số |
| `attachment-failed` | Gắn ảnh vào gói thất bại |
| `cleanup-failed` | Dọn ảnh cũ thất bại |

The eight codes raised as `CccdManualError` (`card-not-found`, `packet-already-has-card`,
`unknown-packet`, `no-cccd-workbook`, `side-not-found`, `card-has-no-image`, `attach-failed`,
`reconcile-failed`) are **API errors, not card issues** — they belong to the error map in the
screen, not here.

An unrecognised code renders as itself rather than being swallowed, so a new backend issue
shows up instead of disappearing.

## Logic — `src/logic/cccdReview.ts`

Pure, no IO, following the existing convention that logic modules are unit-tested and
components stay thin:

```ts
buildCccdReview(packets: PacketMeta[], cards: CccdCard[]): {
  needsAction: Array<PacketRow | CardRow>   // packets without a card, then unattached cards
  attached: PacketRow[]                     // packet + its card, in packet order
  counts: { packetsWithoutCard: number; unattachedCards: number }
}
```

It joins the card-centric list onto packets by `attachedPacketIndex` — the API list is
card-shaped, the screen is packet-shaped, and that inversion is the only real logic here.
Ordering is by packet index so the screen is stable across refreshes.

## Testing

- `src/logic/cccdReview.test.ts` — the join (card→packet inversion, over `PacketMeta`); a packet with no card
  lands in `needsAction`; an unattached card lands in `needsAction` as informational; a
  packet with a card lands in `attached`; both counts; unknown state and unknown issue codes
  pass through as themselves; the empty-workbook case yields empty buckets.
- `src/components/cccdReviewScreen.test.tsx` — exceptions render above the collapsed
  section; "Gán thẻ" opens the picker with the right `packetIndex`; a successful assign moves
  the row and updates the header from the response; "Gỡ" issues `{packetIndex: null}`;
  `packet-already-has-card` surfaces its message; "Tiếp tục" sets the flag and leaves.
- `UploadFlow` gate: a case with `cccdSummary` and no flag opens on `'cccd'`; with the flag
  set it opens on `'detail'`; `cccdSummary === null` opens on `'detail'`.

Green before commit, as always: `cd server && python3 -m pytest`, `node_modules/.bin/tsc -b`,
`node_modules/.bin/vitest run`.

## Out of scope

- Roster/identity correction and page-boundary confirmation (decision 2)
- Any criteria-engine change, including the Tier 4 criteria that render empty and the #15
  PIT threshold defect — both tracked in `handoff-ver3.md`, neither belongs in this step
- Edits to `CaseDetail`, `PacketTable`, `FolderReview` or `SummaryTab`
- A persisted "this person has no card" marker
- Re-ingest, re-OCR, or any change to the GreenNode IDP path

## Accepted costs

- **The dismissal flag is per-browser.** Another machine, or cleared site data, shows the
  step once more. Chosen deliberately over a persisted field, which would be backend work.
- **A genuinely missing card never clears.** If a collaborator never submitted a card, that
  packet stays in "Cần xử lý" for good, because nothing in this scope can record its
  absence. Visible, not silent — and the reviewer can always continue past it.
- **Two cards claiming one packet would hide one of them.** `buildCccdReview` indexes attached
  cards into a `Map` keyed by packet, so a second card claiming the same `attachedPacketIndex`
  would overwrite the first: the loser appears in neither bucket while still counting toward
  `counts.candidates`. Three separate reviewers raised this independently, so it is recorded
  rather than left implicit. **Accepted**, because the state is unreachable through the API —
  `cccd_manual.assign_card` scans the other mappings and raises `packet-already-has-card`
  before attaching, and ingest attaches at most one card per packet. Worth revisiting only if
  a future path can write mappings without going through `assign_card`.

## Measured state this is designed against

Case `68ddc1f0` (`-idp-namefix`, newest), read from `case.json` on 2026-08-27:

- 42 mappings: 39 `exact`, 1 `assigned`, 2 `conflict` → **40 attached**
- 41 packets, roster 41/41 matched → **1 packet without a card**
- So "Cần xử lý" holds ~3 rows today and "Đã gán" holds 40.

The frozen fallback `87844b89` (`-idp`) sits at 38 `exact` + 1 `manual` + 1 `suggested` +
2 `conflict` = 39 attached, which exercises `suggested` in the UI. The pre-IDP baseline
`fixed0boundaries0jul2026000000001` has 24 `exact` + 18 `manual`, i.e. 18 rows needing
action — a useful worst case for the exceptions section's layout.
