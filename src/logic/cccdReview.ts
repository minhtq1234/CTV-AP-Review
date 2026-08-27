// src/logic/cccdReview.ts
// The CCCD review step's model. The API lists CARDS (each knowing which packet
// claimed it); this screen is about PACKETS (each needing a card). That
// inversion is the only real logic here, so it lives in one pure function.
import type { CccdCard, PacketMeta } from '../upload/api'
// The name-fallback chain lives in packetTable.ts so this screen and the
// packet table cannot silently disagree about what a packet is called.
import { packetDisplayName } from './packetTable'

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

/** A packet row in the `attached` bucket: the card is there by construction. */
export interface CccdAttachedRow extends CccdPacketRow {
  card: CccdCard
}

export interface CccdReviewCounts {
  candidates: number
  attached: number
  packetsWithoutCard: number
  unattachedCards: number
}

export interface CccdReview {
  /** Packets missing a card first, then cards nothing has claimed. */
  needsAction: CccdReviewRow[]
  attached: CccdAttachedRow[]
  counts: CccdReviewCounts
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
  const attached: CccdAttachedRow[] = []
  for (const packet of ordered) {
    const card = byPacket.get(packet.index) ?? null
    const base = {
      kind: 'packet' as const,
      packetIndex: packet.index,
      name: packetDisplayName(packet),
    }
    if (card) attached.push({ ...base, card })
    else needsAction.push({ ...base, card: null })
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
