# Ver 3 Step 1 — CCCD Review Step Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Insert a case-level CCCD review step between processing and the packet list, so a reviewer sees what mapped, fixes what did not, and only then opens the packet list.

**Architecture:** One pure logic module (`src/logic/cccdReview.ts`) inverts the card-centric API list into packet-shaped rows and buckets them into "needs action" and "already attached". One new component file holds a presentational view (`CccdReviewView`, pure props, static-render tested) and its container (`CccdReviewScreen`, which fetches and mutates). `UploadFlow` gains a `'cccd'` screen and a localStorage-backed dismissal. No backend change: the three existing `/api/cases/{cid}/cccd-cards` routes cover list, attach, move and detach.

**Tech Stack:** React 18 · TypeScript · Vite · Vitest (node env by default, `jsdom` opt-in per file) · no testing-library — interaction tests use `act` from `react` + `createRoot` from `react-dom/client`

**Spec:** [`docs/superpowers/specs/2026-08-27-ver3-cccd-review-step-design.md`](../specs/2026-08-27-ver3-cccd-review-step-design.md)

**Branch base:** `stable/2026-08-25-cccd-idp` @ `faf5ccc`. This is the **stable** lineage at
`/Users/lap16603/Documents/New project/work/CTV_APReview-stable`. `main` is a different lineage
(no criteria engine, `review.items` instead of `review.fields`) — never verify anything against it.

**Sandbox note:** the `npm`/`npx` wrappers throw `EPERM: uv_cwd` here. Call binaries directly:
`node_modules/.bin/vitest`, `node_modules/.bin/tsc`. Python is `python3`, and pytest must run
with `server/` as the cwd because server modules import by bare name.

---

## File Structure

| File | Responsibility |
|---|---|
| `src/logic/cccdReview.ts` **(create)** | Pure: invert cards→packets, bucket rows, count, label states and issues, and the gate predicate. No IO, no React. |
| `src/logic/cccdReview.test.ts` **(create)** | Unit tests for all of the above (node env). |
| `src/components/CccdReviewScreen.tsx` **(create)** | Exports `CccdReviewView` (presentational, pure props) and default `CccdReviewScreen` (fetches cards, owns assign/detach). Mirrors how `CaseDetail.tsx` exports its inner views for static tests. |
| `src/components/cccdReviewScreen.test.tsx` **(create)** | Static-render tests of `CccdReviewView` (node env). |
| `src/components/CccdReviewScreen.interaction.test.tsx` **(create)** | jsdom tests of the container: assign, detach, error, continue. |
| `src/components/UploadFlow.cccdGate.test.tsx` **(create)** | jsdom test of the routing: workbook + no flag → the step, flag → the list, no workbook → the list, continue → flag written. |
| `src/components/UploadFlow.tsx` **(modify)** | `'cccd'` in the `Screen` union, the gate in `openCase`, the render branch, the dismissal write. |
| `src/components/CaseDetail.tsx` **(modify)** | One optional prop `onOpenCccd?` rendering a "Xem thẻ CCCD" button inside the CCCD banner it already shows. |
| `src/styles.css` **(modify)** | `cccd-review-*` classes. |

**Deviation from the spec, deliberate:** the spec listed `CaseDetail` as out of scope, then also
asked for a link back to the step from the packet list. `CaseDetail` already renders a
`cccd-summary` banner (`CaseDetail.tsx:71-75`), which is the only honest home for that link, so
Task 7 adds one **optional** prop rather than a nav strip bolted above the case header. Nothing
else in `CaseDetail` changes and the prop is optional, so existing call sites and tests keep working.

**Second deviation:** the spec said each mutation would refresh rows and header from the
`{cards, cccdSummary}` response. That holds for detach, which this screen issues itself, but
`CccdCardPicker` discards its response and only calls `onAssigned()` — and editing the picker
would force an edit to `FolderReview`'s call site. So after an assign the container **refetches**
`listCccdCards`. One extra GET, and all counts derive from one source (the cards list) instead of
two that could disagree.

**Task order rationale:** Tasks 1–2 build the pure core (no React, fastest feedback). Task 3
renders it. Tasks 4–6 add behaviour under jsdom. Tasks 7–8 wire the flow. Tasks 9–10 are the link
back, the styles, and a full green run.

---

## Task 1: The pure join — cards → packet rows

**Files:**
- Create: `src/logic/cccdReview.ts`
- Create: `src/logic/cccdReview.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// src/logic/cccdReview.test.ts
import { describe, expect, it } from 'vitest'
import type { CccdCard, PacketMeta } from '../upload/api'
import { buildCccdReview, packetDisplayName } from './cccdReview'

function packet(index: number, name: string | null,
                overrides: Partial<PacketMeta> = {}): PacketMeta {
  return {
    index,
    name,
    pages: [index * 2, index * 2 + 1],
    n_pages: 2,
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: 'synthetic', name: name ?? '' },
    rosterIdentity: { cccd: 'synthetic', name: name ?? '' },
    review: { done: false, fields: {}, rejection: null },
    reviewFieldCount: 6,
    ...overrides,
  }
}

function card(cardId: string, attachedPacketIndex: number | null,
              overrides: Partial<CccdCard> = {}): CccdCard {
  return {
    cardId,
    state: attachedPacketIndex === null ? 'conflict' : 'exact',
    attachedPacketIndex,
    number: '',
    issues: [],
    sides: [{ side: 'front', width: 1059, height: 668 }],
    ...overrides,
  }
}

describe('buildCccdReview', () => {
  it('puts a packet with a card in `attached` and one without in `needsAction`', () => {
    const review = buildCccdReview(
      [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')],
      [card('card-00', 0)],
    )
    expect(review.attached.map(r => r.packetIndex)).toEqual([0])
    expect(review.attached[0].card?.cardId).toBe('card-00')
    expect(review.needsAction).toEqual([
      { kind: 'packet', packetIndex: 1, name: 'Synthetic B', card: null },
    ])
  })

  it('lists an unattached card after the packets that need one', () => {
    const review = buildCccdReview(
      [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')],
      [card('card-00', 0), card('card-09', null)],
    )
    expect(review.needsAction.map(r => r.kind)).toEqual(['packet', 'card'])
    expect(review.needsAction[1]).toEqual({ kind: 'card', card: card('card-09', null) })
  })

  it('counts packets without a card apart from unattached cards', () => {
    const review = buildCccdReview(
      [packet(0, 'A'), packet(1, 'B')],
      [card('card-00', 0), card('card-08', null), card('card-09', null)],
    )
    expect(review.counts).toEqual({
      candidates: 3,
      attached: 1,
      packetsWithoutCard: 1,
      unattachedCards: 2,
    })
  })

  it('treats a card pointing at a packet that is not here as unattached', () => {
    const review = buildCccdReview([packet(0, 'A')], [card('card-77', 41)])
    expect(review.attached).toEqual([])
    expect(review.needsAction.map(r => r.kind)).toEqual(['packet', 'card'])
    expect(review.counts.attached).toBe(0)
    expect(review.counts.unattachedCards).toBe(1)
  })

  it('keeps rows in packet order', () => {
    const review = buildCccdReview(
      [packet(2, 'C'), packet(0, 'A'), packet(1, 'B')],
      [card('card-00', 0), card('card-02', 2)],
    )
    expect(review.attached.map(r => r.packetIndex)).toEqual([0, 2])
  })

  it('is empty for a case with no cards at all', () => {
    const review = buildCccdReview([], [])
    expect(review).toEqual({
      needsAction: [],
      attached: [],
      counts: { candidates: 0, attached: 0, packetsWithoutCard: 0, unattachedCards: 0 },
    })
  })
})

describe('packetDisplayName', () => {
  it('prefers the roster name, then the packet name, then the OCR name', () => {
    expect(packetDisplayName(packet(0, 'Packet Name'))).toBe('Packet Name')
    expect(packetDisplayName(packet(0, 'Packet Name', {
      rosterIdentity: { cccd: 'x', name: 'Roster Name' },
    }))).toBe('Roster Name')
    expect(packetDisplayName(packet(0, null, {
      rosterIdentity: null,
      ocrIdentity: { cccd: 'x', name: 'Ocr Name' },
    }))).toBe('Ocr Name')
  })

  it('falls back to the same unmatched label the packet table uses', () => {
    expect(packetDisplayName(packet(0, null, {
      rosterIdentity: null,
      ocrIdentity: { cccd: '', name: '' },
    }))).toBe('chưa khớp bảng kê')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/logic/cccdReview.test.ts
```
Expected: FAIL — `Failed to resolve import "./cccdReview"`

- [ ] **Step 3: Implement the module**

```ts
// src/logic/cccdReview.ts
// The CCCD review step's model. The API lists CARDS (each knowing which packet
// claimed it); this screen is about PACKETS (each needing a card). That
// inversion is the only real logic here, so it lives in one pure function.
import type { CccdCard, PacketMeta } from '../upload/api'
import { NO_NAME } from './packetTable'

export interface CccdPacketRow {
  kind: 'packet'
  packetIndex: number
  name: string
  /** The card attached to this packet, or null when it still needs one. */
  card: CccdCard | null
}

export interface CccdCardRow {
  kind: 'card'
  card: CccdCard
}

export type CccdReviewRow = CccdPacketRow | CccdCardRow

export interface CccdReviewCounts {
  candidates: number
  attached: number
  packetsWithoutCard: number
  unattachedCards: number
}

export interface CccdReview {
  /** Packets missing a card first, then cards nothing has claimed. */
  needsAction: CccdReviewRow[]
  attached: CccdPacketRow[]
  counts: CccdReviewCounts
}

/** The same fallback chain the packet table uses, so the two screens agree. */
export function packetDisplayName(packet: PacketMeta): string {
  return packet.rosterIdentity?.name
    || packet.name
    || packet.ocrIdentity?.name
    || NO_NAME
}

export function buildCccdReview(
  packets: PacketMeta[],
  cards: CccdCard[],
): CccdReview {
  const known = new Set(packets.map(p => p.index))
  const byPacket = new Map<number, CccdCard>()
  const floating: CccdCard[] = []
  for (const card of cards) {
    const index = card.attachedPacketIndex
    // A card claiming a packet that is not in this case would otherwise render
    // nowhere. Show it as unclaimed rather than dropping it silently.
    if (index !== null && known.has(index)) byPacket.set(index, card)
    else floating.push(card)
  }

  const ordered = [...packets].sort((a, b) => a.index - b.index)
  const needsAction: CccdReviewRow[] = []
  const attached: CccdPacketRow[] = []
  for (const packet of ordered) {
    const row: CccdPacketRow = {
      kind: 'packet',
      packetIndex: packet.index,
      name: packetDisplayName(packet),
      card: byPacket.get(packet.index) ?? null,
    }
    if (row.card) attached.push(row)
    else needsAction.push(row)
  }
  for (const card of floating) needsAction.push({ kind: 'card', card })

  return {
    needsAction,
    attached,
    counts: {
      candidates: cards.length,
      attached: byPacket.size,
      packetsWithoutCard: ordered.length - attached.length,
      unattachedCards: floating.length,
    },
  }
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/logic/cccdReview.test.ts
```
Expected: PASS (8 passed)

- [ ] **Step 5: Commit**

```bash
git add src/logic/cccdReview.ts src/logic/cccdReview.test.ts
git commit -m "feat(cccd): invert the card list into packet-shaped review rows"
```

---

## Task 2: Vietnamese labels for state and issues

The API's `state` and `issues` are codes. The screen must say why a card did not attach, and an
unrecognised code must render as itself rather than vanish.

**Files:**
- Modify: `src/logic/cccdReview.ts`
- Modify: `src/logic/cccdReview.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// append to src/logic/cccdReview.test.ts
import { CCCD_ISSUE_LABELS, CCCD_STATE_LABELS, describeCard } from './cccdReview'

describe('describeCard', () => {
  it('names the state on its own when there are no issues', () => {
    expect(describeCard(card('card-00', 0, { state: 'exact' }))).toBe('Tự động khớp')
    expect(describeCard(card('card-01', 0, { state: 'assigned' }))).toBe('Người dùng gán')
  })

  it('appends every issue after the state', () => {
    expect(describeCard(card('card-02', null, {
      state: 'conflict',
      issues: ['duplicate-cccd', 'duplicate-name'],
    }))).toBe('Xung đột · Trùng số CCCD · Trùng họ tên')
  })

  it('passes an unknown state or issue through as itself', () => {
    expect(describeCard(card('card-03', null, {
      state: 'brand-new-state',
      issues: ['brand-new-issue'],
    }))).toBe('brand-new-state · brand-new-issue')
  })

  it('labels every state and issue the backend can emit', () => {
    expect(Object.keys(CCCD_STATE_LABELS).sort()).toEqual(
      ['assigned', 'conflict', 'exact', 'manual', 'suggested'],
    )
    expect(Object.keys(CCCD_ISSUE_LABELS).sort()).toEqual([
      'ambiguous-pair',
      'duplicate-cccd',
      'duplicate-name',
      'no-exact-roster-match',
      'no-front',
      'no-number-region',
      'unreadable-identity',
    ])
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/logic/cccdReview.test.ts -t describeCard
```
Expected: FAIL — `No "describeCard" export is defined on the module`

- [ ] **Step 3: Implement the labels**

```ts
// add to src/logic/cccdReview.ts

// The five states cccd_matching can resolve to, plus `assigned` for a card a
// reviewer named. Only `exact` and `assigned` carry evidence into a packet.
export const CCCD_STATE_LABELS: Record<string, string> = {
  exact: 'Tự động khớp',
  assigned: 'Người dùng gán',
  suggested: 'Gợi ý theo tên',
  manual: 'Cần gán tay',
  conflict: 'Xung đột',
}

export const CCCD_ISSUE_LABELS: Record<string, string> = {
  'no-front': 'Không có mặt trước',
  'unreadable-identity': 'Không đọc được số',
  'no-number-region': 'Không tìm được vùng số',
  'no-exact-roster-match': 'Số không khớp bảng kê',
  'duplicate-cccd': 'Trùng số CCCD',
  'duplicate-name': 'Trùng họ tên',
  'ambiguous-pair': 'Không ghép được mặt trước/sau',
}

/** State then issues, in Vietnamese. An unmapped code renders as itself so a
 *  new backend code shows up in the UI instead of disappearing. */
export function describeCard(card: CccdCard): string {
  return [
    CCCD_STATE_LABELS[card.state] ?? card.state,
    ...card.issues.map(issue => CCCD_ISSUE_LABELS[issue] ?? issue),
  ].join(' · ')
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/logic/cccdReview.test.ts
```
Expected: PASS (12 passed)

- [ ] **Step 5: Commit**

```bash
git add src/logic/cccdReview.ts src/logic/cccdReview.test.ts
git commit -m "feat(cccd): Vietnamese labels for card state and issues"
```

---

## Task 3: The presentational view

`CccdReviewView` takes everything as props so it can be static-rendered, the way
`CaseDetail.tsx` exports `PacketCard` and `PacketDashboardView` for its own tests.

**Files:**
- Create: `src/components/CccdReviewScreen.tsx`
- Create: `src/components/cccdReviewScreen.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/components/cccdReviewScreen.test.tsx
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { CccdCard, PacketMeta } from '../upload/api'
import { buildCccdReview } from '../logic/cccdReview'
import { CccdReviewView } from './CccdReviewScreen'

function packet(index: number, name: string): PacketMeta {
  return {
    index,
    name,
    pages: [index * 2, index * 2 + 1],
    n_pages: 2,
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: 'synthetic', name },
    rosterIdentity: { cccd: 'synthetic', name },
    review: { done: false, fields: {}, rejection: null },
    reviewFieldCount: 6,
  }
}

function card(cardId: string, attachedPacketIndex: number | null,
              overrides: Partial<CccdCard> = {}): CccdCard {
  return {
    cardId,
    state: attachedPacketIndex === null ? 'conflict' : 'exact',
    attachedPacketIndex,
    number: '',
    issues: [],
    sides: [{ side: 'front', width: 1059, height: 668 }],
    ...overrides,
  }
}

const packets = [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')]

function render(cards: CccdCard[]) {
  return renderToStaticMarkup(
    <CccdReviewView
      caseId="case-1"
      caseName="FA-SYNTHETIC.pdf"
      review={buildCccdReview(packets, cards)}
      busy={false}
      error={null}
      onAssign={() => {}}
      onDetach={() => {}}
      onContinue={() => {}}
    />,
  )
}

describe('CccdReviewView', () => {
  it('shows all three counts, kept apart', () => {
    const html = render([card('card-00', 0), card('card-09', null)])
    expect(html).toContain('1 đã gắn')
    expect(html).toContain('1 chưa ghép')
    expect(html).toContain('1 gói chưa có thẻ')
  })

  it('lists a packet needing a card with an assign button', () => {
    const html = render([card('card-00', 0)])
    expect(html).toContain('Synthetic B')
    expect(html).toContain('Gán thẻ')
  })

  it('shows an unattached card with its reason, and no assign button of its own', () => {
    const html = render([
      card('card-00', 0),
      card('card-09', null, { state: 'conflict', issues: ['duplicate-cccd'] }),
    ])
    expect(html).toContain('Xung đột · Trùng số CCCD')
    expect(html).toContain('card-09')
  })

  it('renders attached packets inside a collapsed details element', () => {
    const html = render([card('card-00', 0), card('card-01', 1)])
    expect(html).toContain('<details')
    expect(html).not.toContain('<details open')
    expect(html).toContain('Đã gán (2)')
    expect(html).toContain('Gỡ')
  })

  it('says so plainly when nothing needs action', () => {
    const html = render([card('card-00', 0), card('card-01', 1)])
    expect(html).toContain('Mọi gói đều đã có thẻ CCCD.')
  })

  it('always offers the way forward', () => {
    expect(render([])).toContain('Tiếp tục')
  })

  it('surfaces an error when one is passed', () => {
    const html = renderToStaticMarkup(
      <CccdReviewView
        caseId="case-1"
        caseName="FA-SYNTHETIC.pdf"
        review={buildCccdReview(packets, [])}
        busy={false}
        error="Gói này đã có ảnh CCCD. Gỡ ảnh cũ trước."
        onAssign={() => {}}
        onDetach={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('Gỡ ảnh cũ trước')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/cccdReviewScreen.test.tsx
```
Expected: FAIL — `Failed to resolve import "./CccdReviewScreen"`

- [ ] **Step 3: Implement the view**

```tsx
// src/components/CccdReviewScreen.tsx
// Ver 3 step 1: the reviewer confirms which CCCD card belongs to which packet
// before opening the packet list. Exceptions first; everything already attached
// sits behind a collapsed section, so a wrong automatic match is still findable.
import { cccdCardImageUrl } from '../upload/api'
import type { CccdCard } from '../upload/api'
import {
  describeCard,
  type CccdPacketRow,
  type CccdReview,
} from '../logic/cccdReview'

export interface CccdReviewViewProps {
  caseId: string
  caseName: string
  review: CccdReview
  busy: boolean
  error: string | null
  onAssign: (packetIndex: number, packetLabel: string) => void
  onDetach: (cardId: string) => void
  onContinue: () => void
}

function CardThumb({ caseId, card }: { caseId: string; card: CccdCard }) {
  const front = card.sides.find(side => side.side === 'front') ?? card.sides[0]
  if (!front) return <span className="cccd-review-nothumb">Không có ảnh</span>
  return (
    <img
      className="cccd-review-thumb"
      src={cccdCardImageUrl(caseId, card.cardId, front.side)}
      alt={`Ảnh CCCD ${card.cardId}`}
      loading="lazy"
    />
  )
}

function AttachedRow({ caseId, row, busy, onDetach }: {
  caseId: string
  row: CccdPacketRow
  busy: boolean
  onDetach: (cardId: string) => void
}) {
  const card = row.card
  if (!card) return null
  return (
    <li className="cccd-review-row">
      <span className="cccd-review-stt">{row.packetIndex + 1}</span>
      <span className="cccd-review-name">{row.name}</span>
      <CardThumb caseId={caseId} card={card} />
      <span className="cccd-review-number">{card.number || 'Không đọc được số'}</span>
      <span className="cccd-review-state">{describeCard(card)}</span>
      <button type="button" disabled={busy} onClick={() => onDetach(card.cardId)}>Gỡ</button>
    </li>
  )
}

export function CccdReviewView({
  caseId,
  caseName,
  review,
  busy,
  error,
  onAssign,
  onDetach,
  onContinue,
}: CccdReviewViewProps) {
  const { needsAction, attached, counts } = review
  return (
    <div className="cccd-review">
      <div className="case-detail-head">
        <h2>{caseName}</h2>
      </div>

      <div className="banner result-banner">
        <b>Ghép ảnh CCCD</b>
        <span>
          {counts.attached} đã gắn · {counts.unattachedCards} chưa ghép ·{' '}
          {counts.packetsWithoutCard} gói chưa có thẻ
        </span>
      </div>

      {error && <p className="cccd-review-error" role="alert">{error}</p>}

      <section className="cccd-review-section" aria-label="Cần xử lý">
        <h3>Cần xử lý</h3>
        {needsAction.length === 0 && (
          <p className="cccd-review-empty">Mọi gói đều đã có thẻ CCCD.</p>
        )}
        <ul className="cccd-review-list">
          {needsAction.map(row => (
            row.kind === 'packet' ? (
              <li className="cccd-review-row" key={`packet-${row.packetIndex}`}>
                <span className="cccd-review-stt">{row.packetIndex + 1}</span>
                <span className="cccd-review-name">{row.name}</span>
                <span className="cccd-review-state">Chưa có thẻ CCCD</span>
                <button
                  type="button"
                  disabled={busy}
                  onClick={() => onAssign(row.packetIndex, row.name)}
                >
                  Gán thẻ
                </button>
              </li>
            ) : (
              <li className="cccd-review-row cccd-review-orphan" key={`card-${row.card.cardId}`}>
                <CardThumb caseId={caseId} card={row.card} />
                <span className="cccd-review-number">
                  {row.card.number || 'Không đọc được số'}
                </span>
                <span className="cccd-review-state">{describeCard(row.card)}</span>
                <span className="cccd-review-cardid">{row.card.cardId}</span>
                <span className="cccd-review-hint">
                  Gán từ dòng của gói cần thẻ.
                </span>
              </li>
            )
          ))}
        </ul>
      </section>

      <details className="cccd-review-section">
        <summary>Đã gán ({attached.length})</summary>
        <ul className="cccd-review-list">
          {attached.map(row => (
            <AttachedRow
              key={`attached-${row.packetIndex}`}
              caseId={caseId}
              row={row}
              busy={busy}
              onDetach={onDetach}
            />
          ))}
        </ul>
      </details>

      <div className="cccd-review-foot">
        <button className="btn primary" type="button" onClick={onContinue}>
          Tiếp tục →
        </button>
      </div>
    </div>
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/components/cccdReviewScreen.test.tsx
```
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/components/CccdReviewScreen.tsx src/components/cccdReviewScreen.test.tsx
git commit -m "feat(cccd): the review step's view — exceptions first, attached collapsed"
```

---

## Task 4: The container — load the cards

**Files:**
- Modify: `src/components/CccdReviewScreen.tsx`
- Create: `src/components/CccdReviewScreen.interaction.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// src/components/CccdReviewScreen.interaction.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CccdCard, PacketMeta } from '../upload/api'

const listCccdCards = vi.fn()
const assignCccdCard = vi.fn()

vi.mock('../upload/api', () => ({
  listCccdCards: (...args: unknown[]) => listCccdCards(...args),
  assignCccdCard: (...args: unknown[]) => assignCccdCard(...args),
  cccdCardImageUrl: (caseId: string, cardId: string, side: string) => (
    `/api/cases/${caseId}/cccd-cards/${cardId}/image/${side}`
  ),
}))

const CccdReviewScreen = (await import('./CccdReviewScreen')).default

function packet(index: number, name: string): PacketMeta {
  return {
    index,
    name,
    pages: [index * 2, index * 2 + 1],
    n_pages: 2,
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: 'synthetic', name },
    rosterIdentity: { cccd: 'synthetic', name },
    review: { done: false, fields: {}, rejection: null },
    reviewFieldCount: 6,
  }
}

function card(cardId: string, attachedPacketIndex: number | null): CccdCard {
  return {
    cardId,
    state: attachedPacketIndex === null ? 'conflict' : 'exact',
    attachedPacketIndex,
    number: '',
    issues: [],
    sides: [{ side: 'front', width: 1059, height: 668 }],
  }
}

const packets = [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')]

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  listCccdCards.mockReset()
  assignCccdCard.mockReset()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

async function mount(onContinue = () => {}) {
  await act(async () => {
    root.render(
      <CccdReviewScreen
        caseId="case-1"
        caseName="FA-SYNTHETIC.pdf"
        packets={packets}
        onContinue={onContinue}
      />,
    )
  })
}

function button(text: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')]
    .find(el => el.textContent?.includes(text))
  if (!found) throw new Error(`no button matching ${text}: ${host.textContent}`)
  return found as HTMLButtonElement
}

describe('CccdReviewScreen', () => {
  it('loads the cards for the case and renders the buckets', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0), card('card-09', null)])
    await mount()
    expect(listCccdCards).toHaveBeenCalledWith('case-1')
    expect(host.textContent).toContain('Synthetic B')
    expect(host.textContent).toContain('1 gói chưa có thẻ')
  })

  it('shows a load failure instead of an empty screen', async () => {
    listCccdCards.mockRejectedValue(new Error('boom'))
    await mount()
    expect(host.textContent).toContain('Không tải được danh sách ảnh.')
  })

  it('hands "Tiếp tục" straight through', async () => {
    listCccdCards.mockResolvedValue([])
    const onContinue = vi.fn()
    await mount(onContinue)
    await act(async () => { button('Tiếp tục').click() })
    expect(onContinue).toHaveBeenCalledOnce()
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/CccdReviewScreen.interaction.test.tsx
```
Expected: FAIL — `The requested module './CccdReviewScreen' does not provide an export named 'default'`

- [ ] **Step 3: Implement the container**

`tsconfig.json` sets **`noUnusedLocals`** and **`noUnusedParameters`**, so every import and
every local must be used in the same step that introduces it. That is why `busy` state and
`assignCccdCard` arrive in Task 5, not here.

Add the React and logic imports, and extend the existing `CccdCard` type import in place:

Both api lines **replace** the ones Task 3 wrote — do not add a second import from
`'../upload/api'`, which would redeclare `cccdCardImageUrl`:

```tsx
// at the top of src/components/CccdReviewScreen.tsx
import { useCallback, useEffect, useState } from 'react'
import { cccdCardImageUrl, listCccdCards } from '../upload/api'      // was: cccdCardImageUrl only
import type { CccdCard, PacketMeta } from '../upload/api'            // was: CccdCard only
import { buildCccdReview } from '../logic/cccdReview'
```

```tsx
// add at the end of src/components/CccdReviewScreen.tsx

const LOAD_ERROR = 'Không tải được danh sách ảnh.'

interface Props {
  caseId: string
  caseName: string
  packets: PacketMeta[]
  onContinue: () => void
}

export default function CccdReviewScreen({
  caseId,
  caseName,
  packets,
  onContinue,
}: Props) {
  const [cards, setCards] = useState<CccdCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    try {
      setCards(await listCccdCards(caseId))
    } catch {
      setError(LOAD_ERROR)
    }
  }, [caseId])

  useEffect(() => { void load() }, [load])

  return (
    <CccdReviewView
      caseId={caseId}
      caseName={caseName}
      review={buildCccdReview(packets, cards ?? [])}
      busy={cards === null}
      error={error}
      onAssign={() => {}}
      onDetach={() => {}}
      onContinue={onContinue}
    />
  )
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/components/CccdReviewScreen.interaction.test.tsx
node_modules/.bin/tsc -b
```
Expected: PASS (3 passed); `tsc -b` exits 0 with no output

- [ ] **Step 5: Commit**

```bash
git add src/components/CccdReviewScreen.tsx src/components/CccdReviewScreen.interaction.test.tsx
git commit -m "feat(cccd): review step container loads the case's cards"
```

---

## Task 5: Detach a wrong card

Detach is the action this screen issues itself, so it can use the `{cards}` the API returns
rather than refetching.

**Files:**
- Modify: `src/components/CccdReviewScreen.tsx`
- Modify: `src/components/CccdReviewScreen.interaction.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// append inside the `describe('CccdReviewScreen', ...)` block

  it('detaches with a null packetIndex and re-renders from the response', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0), card('card-01', 1)])
    assignCccdCard.mockResolvedValue({
      cards: [card('card-00', 0), card('card-01', null)],
      cccdSummary: { status: 'partial', candidates: 2, attached: 1, unresolved: 1 },
    })
    await mount()
    await act(async () => { button('Gỡ').click() })
    expect(assignCccdCard).toHaveBeenCalledWith('case-1', 'card-00', null)
    expect(host.textContent).toContain('1 gói chưa có thẻ')
    // The response is authoritative — no second GET.
    expect(listCccdCards).toHaveBeenCalledOnce()
  })

  it('translates a rejected detach into its Vietnamese message', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    assignCccdCard.mockRejectedValue(new Error('card-not-found'))
    await mount()
    await act(async () => { button('Gỡ').click() })
    expect(host.textContent).toContain('Không tìm thấy ảnh này.')
  })
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/CccdReviewScreen.interaction.test.tsx -t detaches
```
Expected: FAIL — `no button matching Gỡ` (the attached section renders no working button yet), or `assignCccdCard` not called

- [ ] **Step 3: Implement detach**

Three edits: widen the api import, add the `busy` state now that something sets it, and add
the error map plus the handler.

```tsx
// widen the existing api import
import { assignCccdCard, cccdCardImageUrl, listCccdCards } from '../upload/api'
```

```tsx
// alongside the other state in CccdReviewScreen
  const [busy, setBusy] = useState(false)
```

```tsx
// add near LOAD_ERROR in src/components/CccdReviewScreen.tsx
// Same codes CccdCardPicker maps, same wording — one vocabulary for one API.
const ERROR_TEXT: Record<string, string> = {
  'packet-already-has-card': 'Gói này đã có ảnh CCCD. Gỡ ảnh cũ trước.',
  'card-not-found': 'Không tìm thấy ảnh này.',
  'unknown-packet': 'Không tìm thấy gói hồ sơ.',
  'no-cccd-workbook': 'Hồ sơ này không có file CCCD.',
}

const MUTATE_ERROR = 'Không cập nhật được ảnh. Vui lòng thử lại.'
```

```tsx
// inside CccdReviewScreen, after `load`
  const detach = async (cardId: string) => {
    setBusy(true)
    setError(null)
    try {
      const result = await assignCccdCard(caseId, cardId, null)
      setCards(result.cards)
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : ''
      setError(ERROR_TEXT[code] ?? MUTATE_ERROR)
    } finally {
      setBusy(false)
    }
  }
```

Then pass it down and let the new state reach the view:

```tsx
      busy={busy || cards === null}
      onDetach={cardId => { void detach(cardId) }}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/components/CccdReviewScreen.interaction.test.tsx
```
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/components/CccdReviewScreen.tsx src/components/CccdReviewScreen.interaction.test.tsx
git commit -m "feat(cccd): detach a wrongly attached card from the review step"
```

---

## Task 6: Assign a card, reusing the existing picker

`CccdCardPicker` already offers the unclaimed pool as images and filters on
`attachedPacketIndex === null` only — so `suggested`, `manual` and `conflict` cards are all
offered, and `cccd_manual.assign_card` carries no state guard to refuse them. It discards its
own response and calls `onAssigned()`, so the container refetches.

**Files:**
- Modify: `src/components/CccdReviewScreen.tsx`
- Modify: `src/components/CccdReviewScreen.interaction.test.tsx`

- [ ] **Step 1: Write the failing test**

```tsx
// add to the vi.mock factory for '../upload/api' — nothing else changes there.
// Then add a mock for the picker so this test stays about wiring, not the picker:

vi.mock('./CccdCardPicker', () => ({
  default: ({ packetIndex, packetLabel, onAssigned, onCancel }: {
    packetIndex: number
    packetLabel: string
    onAssigned: () => void
    onCancel: () => void
  }) => (
    <div data-testid="picker">
      <span>{`picker:${packetIndex}:${packetLabel}`}</span>
      <button type="button" onClick={onAssigned}>mock-assigned</button>
      <button type="button" onClick={onCancel}>mock-cancel</button>
    </div>
  ),
}))
```

```tsx
// append inside the `describe('CccdReviewScreen', ...)` block

  it('opens the picker for the packet whose row was clicked', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    expect(host.textContent).toContain('picker:1:Synthetic B')
  })

  it('refetches after the picker reports an assignment, and closes it', async () => {
    listCccdCards
      .mockResolvedValueOnce([card('card-00', 0)])
      .mockResolvedValueOnce([card('card-00', 0), card('card-09', 1)])
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    await act(async () => { button('mock-assigned').click() })
    expect(listCccdCards).toHaveBeenCalledTimes(2)
    expect(host.querySelector('[data-testid="picker"]')).toBeNull()
    expect(host.textContent).toContain('0 gói chưa có thẻ')
  })

  it('closes the picker on cancel without refetching', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    await act(async () => { button('mock-cancel').click() })
    expect(host.querySelector('[data-testid="picker"]')).toBeNull()
    expect(listCccdCards).toHaveBeenCalledOnce()
  })
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/CccdReviewScreen.interaction.test.tsx -t picker
```
Expected: FAIL — the picker never renders, so `picker:1:Synthetic B` is absent

- [ ] **Step 3: Implement the assign flow**

```tsx
// add to the imports in src/components/CccdReviewScreen.tsx
import CccdCardPicker from './CccdCardPicker'
```

```tsx
// inside CccdReviewScreen, alongside the other state
  const [picking, setPicking] = useState<{ packetIndex: number; label: string } | null>(null)
```

```tsx
// wrap the returned view
  return (
    <>
      <CccdReviewView
        caseId={caseId}
        caseName={caseName}
        review={buildCccdReview(packets, cards ?? [])}
        busy={busy || cards === null}
        error={error}
        onAssign={(packetIndex, label) => { setPicking({ packetIndex, label }) }}
        onDetach={cardId => { void detach(cardId) }}
        onContinue={onContinue}
      />
      {picking && (
        <CccdCardPicker
          caseId={caseId}
          packetIndex={picking.packetIndex}
          packetLabel={picking.label}
          onCancel={() => setPicking(null)}
          onAssigned={() => {
            // The picker keeps its own response, so reload rather than guess.
            setPicking(null)
            setError(null)
            void load()
          }}
        />
      )}
    </>
  )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/components/CccdReviewScreen.interaction.test.tsx
node_modules/.bin/tsc -b
```
Expected: PASS (8 passed); `tsc -b` exits 0

- [ ] **Step 5: Commit**

```bash
git add src/components/CccdReviewScreen.tsx src/components/CccdReviewScreen.interaction.test.tsx
git commit -m "feat(cccd): assign a card from the review step via the existing picker"
```

---

## Task 7: The gate predicate

Pure, so it is testable in the default node environment. `UploadFlow` does the `localStorage`
read; this function only decides.

**Files:**
- Modify: `src/logic/cccdReview.ts`
- Modify: `src/logic/cccdReview.test.ts`

- [ ] **Step 1: Write the failing test**

```ts
// append to src/logic/cccdReview.test.ts
import { cccdReviewSeenKey, shouldOpenCccdReview } from './cccdReview'

describe('shouldOpenCccdReview', () => {
  const summary = { status: 'partial' as const, candidates: 42, attached: 40, unresolved: 2 }

  it('opens for a case that has a workbook and has not been seen', () => {
    expect(shouldOpenCccdReview(summary, false)).toBe(true)
  })

  it('skips a case whose step was already dismissed', () => {
    expect(shouldOpenCccdReview(summary, true)).toBe(false)
  })

  it('skips a case uploaded without a CCCD workbook', () => {
    expect(shouldOpenCccdReview(null, false)).toBe(false)
  })

  it('keys the dismissal per case', () => {
    expect(cccdReviewSeenKey('abc123')).toBe('cccd-reviewed:abc123')
  })
})
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/logic/cccdReview.test.ts -t shouldOpenCccdReview
```
Expected: FAIL — `No "shouldOpenCccdReview" export is defined on the module`

- [ ] **Step 3: Implement the predicate**

```ts
// add to src/logic/cccdReview.ts — extend the api import with CccdSummary
import type { CccdCard, CccdSummary, PacketMeta } from '../upload/api'
```

```ts
// add at the end of src/logic/cccdReview.ts

/** Per-case, per-browser: the step is shown once and then dismissed. */
export function cccdReviewSeenKey(caseId: string): string {
  return `cccd-reviewed:${caseId}`
}

/** A case with no workbook has nothing to review, and a dismissed one has been
 *  looked at. Everything else opens on the step. */
export function shouldOpenCccdReview(
  cccdSummary: CccdSummary | null,
  seen: boolean,
): boolean {
  return cccdSummary !== null && !seen
}
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/logic/cccdReview.test.ts
```
Expected: PASS (16 passed)

- [ ] **Step 5: Commit**

```bash
git add src/logic/cccdReview.ts src/logic/cccdReview.test.ts
git commit -m "feat(cccd): the gate predicate for the review step"
```

---

## Task 8: Wire the step into UploadFlow

**Files:**
- Modify: `src/components/UploadFlow.tsx:24` (the `Screen` union)
- Modify: `src/components/UploadFlow.tsx:66-75` (`openCase`)
- Modify: `src/components/UploadFlow.tsx:208` (the render branches)

- [ ] **Step 1: Widen the `Screen` union**

Replace line 24:

```ts
type Screen = 'list' | 'upload' | 'detail' | 'review'
```

with:

```ts
type Screen = 'list' | 'upload' | 'cccd' | 'detail' | 'review'
```

- [ ] **Step 2: Add the imports**

Add after the `CaseDetail` import (line 19):

```ts
import CccdReviewScreen from './CccdReviewScreen'
```

and after the `reviewSaveQueue` import block (line 16):

```ts
import { cccdReviewSeenKey, shouldOpenCccdReview } from '../logic/cccdReview'
```

- [ ] **Step 3: Gate inside `openCase`**

Replace line 73:

```ts
      setCaseId(id); setDetail(d); setScreen('detail')
```

with:

```ts
      setCaseId(id); setDetail(d)
      // Ver 3 step 1: confirm the CCCD mapping before the packet list. Shown
      // once per case per browser — a case with no workbook never sees it.
      const seen = window.localStorage.getItem(cccdReviewSeenKey(id)) !== null
      setScreen(shouldOpenCccdReview(d.cccdSummary, seen) ? 'cccd' : 'detail')
```

- [ ] **Step 4: Add the render branch**

Insert immediately before the `if (screen === 'detail' && detail)` branch (line 208):

```tsx
  if (screen === 'cccd' && detail && caseId) {
    return (
      <CccdReviewScreen
        caseId={caseId}
        caseName={detail.name}
        packets={detail.packets}
        onContinue={() => {
          window.localStorage.setItem(cccdReviewSeenKey(caseId), new Date().toISOString())
          setScreen('detail')
        }}
      />
    )
  }
```

- [ ] **Step 5: Write the gate's own test**

The predicate is already tested in Task 7; this covers the wiring — that the three cases really
do route where they should. Child screens are mocked so the test is about routing only.

```tsx
// src/components/UploadFlow.cccdGate.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CaseDetail as CaseDetailT, CccdSummary } from '../upload/api'

const getCase = vi.fn()

vi.mock('../upload/api', () => ({
  listCases: () => Promise.resolve([]),
  getCase: (...args: unknown[]) => getCase(...args),
  createCase: () => Promise.resolve({ case_id: 'case-1' }),
  setReview: () => Promise.resolve({}),
  deleteCase: () => Promise.resolve(),
  fetchPacketManifest: () => Promise.resolve(null),
  normalizePacketReview: () => ({ done: false, fields: {}, rejection: null }),
}))

vi.mock('./CaseList', () => ({
  default: ({ onOpen }: { onOpen: (id: string) => void }) => (
    <button type="button" onClick={() => onOpen('case-1')}>open-case</button>
  ),
}))

vi.mock('./CaseDetail', () => ({ default: () => <p>DETAIL</p> }))

vi.mock('./CccdReviewScreen', () => ({
  default: ({ onContinue }: { onContinue: () => void }) => (
    <div>
      <p>CCCD-STEP</p>
      <button type="button" onClick={onContinue}>continue</button>
    </div>
  ),
}))

const UploadFlow = (await import('./UploadFlow')).default

const workbook: CccdSummary = {
  status: 'partial', candidates: 42, attached: 40, unresolved: 2,
}

function caseDetail(cccdSummary: CccdSummary | null): CaseDetailT {
  return {
    id: 'case-1',
    name: 'FA-SYNTHETIC.pdf',
    createdAt: null,
    status: 'ready',
    pdfName: 'FA-SYNTHETIC.pdf',
    rosterName: 'roster.xlsx',
    cccdName: cccdSummary ? 'cards.xlsx' : null,
    cccdSummary,
    summary: null,
    error: null,
    packets: [],
    progress: { done: 0, total: 0, flagged: 0 },
  }
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  getCase.mockReset()
  window.localStorage.clear()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

async function openTheCase() {
  await act(async () => { root.render(<UploadFlow />) })
  const open = [...host.querySelectorAll('button')]
    .find(el => el.textContent === 'open-case') as HTMLButtonElement
  await act(async () => { open.click() })
}

describe('the CCCD gate', () => {
  it('opens a case with a workbook on the review step', async () => {
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    expect(host.textContent).toContain('CCCD-STEP')
  })

  it('skips the step once it has been dismissed for that case', async () => {
    window.localStorage.setItem('cccd-reviewed:case-1', '2026-08-27T00:00:00.000Z')
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    expect(host.textContent).toContain('DETAIL')
    expect(host.textContent).not.toContain('CCCD-STEP')
  })

  it('never shows the step for a case uploaded without a workbook', async () => {
    getCase.mockResolvedValue(caseDetail(null))
    await openTheCase()
    expect(host.textContent).toContain('DETAIL')
  })

  it('records the dismissal when the reviewer continues', async () => {
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    const go = [...host.querySelectorAll('button')]
      .find(el => el.textContent === 'continue') as HTMLButtonElement
    await act(async () => { go.click() })
    expect(host.textContent).toContain('DETAIL')
    expect(window.localStorage.getItem('cccd-reviewed:case-1')).not.toBeNull()
  })
})
```

- [ ] **Step 6: Run it to verify it passes**

```bash
node_modules/.bin/vitest run src/components/UploadFlow.cccdGate.test.tsx
```
Expected: PASS (4 passed). A failure naming `CCCD-STEP` means the gate in Step 3 did not take;
a failure importing `../upload/api` means the mock factory is missing a function `UploadFlow`
imports — add it there rather than un-mocking.

- [ ] **Step 7: Verify types and the whole suite**

```bash
node_modules/.bin/tsc -b
node_modules/.bin/vitest run
```
Expected: `tsc -b` exits 0; vitest PASS with 239 + the new tests, 0 failures

- [ ] **Step 8: Commit**

```bash
git add src/components/UploadFlow.tsx src/components/UploadFlow.cccdGate.test.tsx
git commit -m "feat(cccd): open a processed case on the CCCD review step"
```

---

## Task 9: The way back from the packet list

`CaseDetail` already renders a CCCD banner when `detail.cccdName && detail.cccdSummary`
(`CaseDetail.tsx:71-75`). One optional prop turns it into the way back.

**Files:**
- Modify: `src/components/CaseDetail.tsx:20-30` (props) and `:71-75` (the banner)
- Modify: `src/components/UploadFlow.tsx` (pass the prop)

- [ ] **Step 1: Write the failing test**

```tsx
// append to src/components/caseDetail.test.tsx, inside the outermost describe
  it('offers a way back to the CCCD step only when a handler is given', () => {
    const detail: CaseDetailT = {
      ...baseDetail,
      cccdName: 'CCCD_T2.xlsx',
      cccdSummary: { status: 'partial', candidates: 42, attached: 40, unresolved: 2 },
    }
    const without = renderToStaticMarkup(
      <CaseDetail detail={detail} onOpenPacket={() => {}} onBack={() => {}}
        onExport={() => {}} />,
    )
    expect(without).not.toContain('Xem thẻ CCCD')

    const with_ = renderToStaticMarkup(
      <CaseDetail detail={detail} onOpenPacket={() => {}} onBack={() => {}}
        onExport={() => {}} onOpenCccd={() => {}} />,
    )
    expect(with_).toContain('Xem thẻ CCCD')
  })
```

`baseDetail` does not exist in that file — the existing `describe('CCCD aggregate summary')`
block builds its `detail` inline (`caseDetail.test.tsx:237-259`). Add this next to it, with the
same shape; note `CaseProgress` is `{done, total, flagged, candidates?}` — there is no
`rejected` field:

```tsx
const baseDetail: CaseDetailT = {
  id: 'synthetic-case',
  name: 'Synthetic Case',
  createdAt: null,
  status: 'ready',
  pdfName: 'packet.pdf',
  rosterName: 'roster.xlsx',
  cccdName: null,
  cccdSummary: null,
  summary: {
    found: packets.length,
    roster_n: packets.length,
    matched: packets.length,
    auto_merged: 0,
  },
  error: null,
  packets,
  progress: { done: 1, total: packets.length, flagged: 2 },
}
```

- [ ] **Step 2: Run it to verify it fails**

```bash
node_modules/.bin/vitest run src/components/caseDetail.test.tsx -t "way back"
```
Expected: FAIL — `Xem thẻ CCCD` is not in the markup

- [ ] **Step 3: Add the optional prop**

In the `Props` interface (after `onExport`):

```ts
  /** Ver 3: back to the CCCD review step. Absent in contexts without one. */
  onOpenCccd?: () => void
```

Add it to the destructure:

```ts
export default function CaseDetail({ detail, onOpenPacket, onBack, onExport, onOpenCccd }: Props) {
```

Replace the banner block:

```tsx
      {detail.cccdName && detail.cccdSummary && (
        <div className={`cccd-summary ${detail.cccdSummary.status}`}>
          {formatCccdSummary(detail.cccdSummary)}
        </div>
      )}
```

with:

```tsx
      {detail.cccdName && detail.cccdSummary && (
        <div className={`cccd-summary ${detail.cccdSummary.status}`}>
          {formatCccdSummary(detail.cccdSummary)}
          {onOpenCccd && (
            <button type="button" className="cccd-summary-link" onClick={onOpenCccd}>
              Xem thẻ CCCD
            </button>
          )}
        </div>
      )}
```

- [ ] **Step 4: Pass it from UploadFlow**

In the `screen === 'detail'` branch, extend the `CaseDetail` element:

```tsx
        <CaseDetail detail={detail} onOpenPacket={onOpenPacket} onBack={backToList}
          onExport={() => setShowReport(true)}
          onOpenCccd={detail.cccdSummary ? () => setScreen('cccd') : undefined} />
```

- [ ] **Step 5: Run the tests to verify they pass**

```bash
node_modules/.bin/vitest run src/components/caseDetail.test.tsx
node_modules/.bin/tsc -b
```
Expected: PASS; `tsc -b` exits 0

- [ ] **Step 6: Commit**

```bash
git add src/components/CaseDetail.tsx src/components/caseDetail.test.tsx src/components/UploadFlow.tsx
git commit -m "feat(cccd): reach the review step again from the case's CCCD banner"
```

---

## Task 10: Styles, then full green

The interaction suite reads `src/styles.css` (`FolderReview.interaction.test.tsx:12`), so classes
that exist in markup but not in CSS are a real gap here, not a cosmetic one.

**Files:**
- Modify: `src/styles.css`

- [ ] **Step 1: Add the styles**

Append to `src/styles.css`:

```css
/* Ver 3 step 1 — the CCCD review step. Rows are a fixed grid so the STT, name,
   thumbnail and action line up down the page in both sections. */
.cccd-review { padding: 16px 20px 32px; }
.cccd-review-section { margin-top: 18px; }
.cccd-review-section > summary { cursor: pointer; font-weight: 600; padding: 6px 0; }
.cccd-review-list { list-style: none; margin: 8px 0 0; padding: 0; }
.cccd-review-row {
  display: grid;
  grid-template-columns: 40px minmax(160px, 1fr) 96px 140px minmax(160px, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--line, #e4e4e7);
}
.cccd-review-orphan { grid-template-columns: 96px 140px minmax(160px, 1fr) 120px auto; }
.cccd-review-stt { color: #6b7280; font-variant-numeric: tabular-nums; }
.cccd-review-name { font-weight: 600; }
.cccd-review-number { font-variant-numeric: tabular-nums; }
.cccd-review-state { color: #6b7280; }
.cccd-review-cardid { color: #9ca3af; font-size: 12px; }
.cccd-review-hint { color: #6b7280; font-size: 12px; }
.cccd-review-thumb {
  width: 96px; height: 60px; object-fit: cover;
  border: 1px solid var(--line, #e4e4e7); border-radius: 4px; background: #f4f4f5;
}
.cccd-review-nothumb { color: #9ca3af; font-size: 12px; }
.cccd-review-empty { color: #6b7280; margin: 8px 0 0; }
.cccd-review-error { color: #b91c1c; margin: 10px 0 0; }
.cccd-review-foot { margin-top: 22px; display: flex; justify-content: flex-end; }
.cccd-summary-link {
  margin-left: 10px; background: none; border: 0; padding: 0;
  color: #1d4ed8; cursor: pointer; text-decoration: underline;
}
```

- [ ] **Step 2: Confirm every new class exists in both markup and CSS**

```bash
for c in cccd-review cccd-review-section cccd-review-list cccd-review-row \
         cccd-review-orphan cccd-review-stt cccd-review-name cccd-review-number \
         cccd-review-state cccd-review-cardid cccd-review-hint cccd-review-thumb \
         cccd-review-nothumb cccd-review-empty cccd-review-error cccd-review-foot \
         cccd-summary-link; do
  printf '%-24s tsx:%s css:%s\n' "$c" \
    "$(grep -rc "\"$c\"\|$c " src/components/CccdReviewScreen.tsx src/components/CaseDetail.tsx | awk -F: '{s+=$2} END {print s}')" \
    "$(grep -c "\.$c[ ,{:]" src/styles.css)"
done
```
Expected: every row has a non-zero `css:` count

- [ ] **Step 3: Run everything green**

```bash
cd server && python3 -m pytest -q; cd ..
node_modules/.bin/tsc -b
node_modules/.bin/vitest run
```
Expected: 775 passed in `server/`; `tsc -b` exits 0; vitest 239 + ~24 new tests passing, 0 failures

- [ ] **Step 4: Commit**

```bash
git add src/styles.css
git commit -m "style(cccd): the review step's row grid and banner link"
```

---

## Manual check before calling it done

Automated tests cannot see the real cards. With the API on 8002 and Vite on 5175:

- [ ] Open case `68ddc1f0…` (`-idp-namefix`). It should land on the CCCD step, not the packet
      list, showing `40 đã gắn · 2 chưa ghép · 1 gói chưa có thẻ` with one packet row needing a
      card and two `Xung đột` card rows.
- [ ] Assign a card to the packet that lacks one; the row moves into `Đã gán` and the counts
      change.
- [ ] Expand `Đã gán`, press `Gỡ` on that same packet, confirm it returns to `Cần xử lý`.
- [ ] Press `Tiếp tục →`, then reopen the case from the list: it goes straight to the packet
      list. The `Xem thẻ CCCD` link in the CCCD banner returns to the step.
- [ ] Open case `fixed0boundaries0jul2026000000001` (24 `exact`, 18 `manual`): 18 rows should
      appear under `Cần xử lý` without the layout breaking.
- [ ] Open a case with no `cccd.xlsx` and confirm it still opens straight on the packet list.
