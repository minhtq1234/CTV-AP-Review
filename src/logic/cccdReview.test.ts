// src/logic/cccdReview.test.ts
import { describe, expect, it } from 'vitest'
import type { CccdCard, PacketMeta } from '../upload/api'
import { buildCccdReview, CCCD_ISSUE_LABELS, CCCD_STATE_LABELS, describeCard } from './cccdReview'

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

  it('exposes the attached bucket\'s card without a null check', () => {
    const review = buildCccdReview([packet(0, 'Synthetic A')], [card('card-00', 0)])
    expect(review.attached.map(row => row.card.cardId)).toEqual(['card-00'])
  })
})

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
