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

// The five states cccd_matching can resolve to, plus `assigned` for a card a
// reviewer named. Only `exact` and `assigned` carry evidence into a packet.
export const CCCD_STATE_LABELS: Record<string, string> = {
  exact: 'Tự động khớp',
  assigned: 'Người dùng gán',
  suggested: 'Gợi ý theo tên',
  manual: 'Cần gán tay',
  conflict: 'Xung đột',
}

// Every issue code the server can attach to a mapping. Grouped by origin:
// cccd_pairing.py decides sides, cccd_matching.py resolves identity, and
// cccd_ingest.py attaches the result to a packet. An unmapped code still falls
// through to its raw value below — this map only decides what a reviewer reads.
export const CCCD_ISSUE_LABELS: Record<string, string> = {
  // Sides and pairing (cccd_pairing.py)
  'missing-front': 'Thiếu ảnh mặt trước',
  'missing-back': 'Thiếu ảnh mặt sau',
  'unknown-side': 'Không xác định được mặt thẻ',
  'side-inferred-front': 'Mặt trước được suy đoán',
  'layout-side-conflict': 'Bố cục hai mặt không khớp',
  'ambiguous-pair': 'Không ghép được mặt trước/sau',
  // Reading and identity (cccd_matching.py)
  'no-front': 'Không có mặt trước',
  'no-number-region': 'Không tìm được vùng số',
  'unreadable-identity': 'Không đọc được số',
  'low-cccd-confidence': 'Số CCCD đọc được với độ tin cậy thấp',
  'non-12-digit-cccd': 'Số trên thẻ không đủ 12 chữ số',
  'no-exact-roster-match': 'Số không khớp bảng kê',
  'conflicting-identity': 'Danh tính trên thẻ không thống nhất',
  'competing-candidate': 'Có ảnh khác cùng tranh gói này',
  'duplicate-cccd': 'Trùng số CCCD',
  'duplicate-name': 'Trùng họ tên',
  // Attaching to a packet (cccd_ingest.py)
  'packet-target-not-found': 'Không tìm được gói tương ứng',
  'non-unique-packet-target': 'Nhiều gói cùng khớp',
  'invalid-roster-key': 'Khóa bảng kê không hợp lệ',
  'non-12-digit-roster-cccd': 'Số trong bảng kê không đủ 12 chữ số',
  'attachment-failed': 'Gắn ảnh vào gói thất bại',
  'cleanup-failed': 'Dọn ảnh cũ thất bại',
}

/** State then issues, in Vietnamese. An unmapped code renders as itself so a
 *  new backend code shows up in the UI instead of disappearing. */
export function describeCard(card: CccdCard): string {
  return [
    CCCD_STATE_LABELS[card.state] ?? card.state,
    ...card.issues.map(issue => CCCD_ISSUE_LABELS[issue] ?? issue),
  ].join(' · ')
}
