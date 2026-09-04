import type { CaseProgress, CaseResultSummary, PacketMeta } from '../upload/api'
import { PACKET_REJECTION_OPTIONS } from './packetRejection'

export type PacketDashboardStatus =
  | 'unseen'
  | 'reviewing'
  | 'completed'
  | 'flagged'

export type PacketDashboardFilter = 'all' | PacketDashboardStatus

export const PACKET_DASHBOARD_LABELS: Record<PacketDashboardStatus, string> = {
  unseen: 'Chưa xem',
  reviewing: 'Đang xem',
  completed: 'Đã xong',
  flagged: 'Cần gửi lại',
}

export function packetSeenCount(
  packet: Pick<PacketMeta, 'review'>,
): number {
  return Object.values(packet.review.fields)
    .filter(field => field.seen).length
}

export function packetFlagCount(
  packet: Pick<PacketMeta, 'review'>,
): number {
  return Object.values(packet.review.fields)
    .filter(field => field.flag != null).length
}

export function packetDashboardStatus(
  packet: Pick<PacketMeta, 'review'>,
): PacketDashboardStatus {
  if (packet.review.rejection || packetFlagCount(packet) > 0) return 'flagged'
  if (packet.review.done) return 'completed'
  return packetSeenCount(packet) > 0 ? 'reviewing' : 'unseen'
}

const KNOWN_PIPELINE_FLAGS = new Set([
  'auto-merged',
  'near-threshold',
  'length-out-of-range',
  'no-roster-match',
  'roster-unmatched',
  'duplicate-roster-identity',
])

export function attentionReasons(
  packet: Pick<PacketMeta, 'matchedBy' | 'flags'>,
): string[] {
  const reasons: string[] = []
  const add = (reason: string) => {
    if (!reasons.includes(reason)) reasons.push(reason)
  }

  if (packet.matchedBy === 'name') add('Chỉ khớp theo tên')
  if (packet.matchedBy === 'unmatched') add('Không khớp bảng kê')
  if (packet.flags.includes('auto-merged')) add('Cần xác nhận ranh giới')
  if (packet.flags.includes('near-threshold')) add('Ranh giới gần ngưỡng')
  if (packet.flags.includes('length-out-of-range')) add('Số trang bất thường')
  // The bảng kê lists each person once — one payment. Two packets claiming
  // the same row means only one of them should be paid.
  if (packet.flags.includes('duplicate-roster-identity')) {
    add('Trùng danh tính với gói khác')
  }
  if (
    packet.flags.includes('no-roster-match')
    || packet.flags.includes('roster-unmatched')
  ) {
    add('Không khớp bảng kê')
  }
  if (packet.flags.some(flag => flag && !KNOWN_PIPELINE_FLAGS.has(flag))) {
    add('Cần kiểm tra xử lý')
  }

  return reasons
}

export function packetDashboardCounts(
  packets: ReadonlyArray<Pick<PacketMeta, 'review'>>,
): Record<PacketDashboardStatus, number> {
  const counts: Record<PacketDashboardStatus, number> = {
    unseen: 0,
    reviewing: 0,
    completed: 0,
    flagged: 0,
  }
  for (const packet of packets) counts[packetDashboardStatus(packet)] += 1
  return counts
}

export function filterPackets<T extends Pick<PacketMeta, 'review'>>(
  packets: ReadonlyArray<T>,
  filter: PacketDashboardFilter,
): T[] {
  return filter === 'all'
    ? [...packets]
    : packets.filter(packet => packetDashboardStatus(packet) === filter)
}

export function prioritizeAttention<
  T extends Pick<PacketMeta, 'matchedBy' | 'flags'>,
>(packets: ReadonlyArray<T>): T[] {
  return [
    ...packets.filter(packet => attentionReasons(packet).length > 0),
    ...packets.filter(packet => attentionReasons(packet).length === 0),
  ]
}


/**
 * How the splitter cut this submission's packets, in one line — or '' when
 * there is nothing to say.
 *
 * The recurring page the splitter finds is not always a packet's first, so the
 * boundaries get moved to where a document actually starts. That changes which
 * pages belong to whom, so the reviewer should be told it happened.
 */
export function boundaryNote(summary: CaseResultSummary): string {
  const offset = summary.boundaries_offset
  if (offset === undefined) return ''        // ingested before this existed
  if (offset === null) {
    return 'Chưa xác nhận được ranh giới gói — cần kiểm tra trang đầu mỗi gói'
  }
  const parts: string[] = []
  const moved = summary.boundaries_snapped ?? 0
  if (offset && moved) {
    const inferred = summary.boundaries_inferred ?? 0
    parts.push(`${moved} gói được cắt lại sớm hơn ${offset} trang`
      + (inferred ? ` (${inferred} gói suy ra theo số còn lại)` : ''))
  }
  const split = summary.boundaries_inserted ?? 0
  if (split) parts.push(`${split} gói bị gộp đã tách ra`)
  return parts.join(' · ')
}


/**
 * The two counts, in one line — or '' when there is nothing to say.
 *
 * `cần gửi lại` is what a *person* decided; the engine's own findings are
 * candidates. Keeping them apart is what stops the packet list and the exported
 * report contradicting each other, which they did: 0 against 34 on the same case.
 */
export function findingsNote(progress: CaseProgress): string {
  const parts: string[] = []
  if (progress.flagged) parts.push(`${progress.flagged} gói cần gửi lại`)
  // Decisions first: what a person concluded outranks what the machine proposed.
  if (progress.candidates) {
    parts.push(`${progress.candidates} gói có phát hiện cần xem`)
  }
  return parts.join(' · ')
}


/**
 * The one-line detail under a packet's lifecycle status: how far a review got,
 * or why it is flagged. Shared by the card and the table so the wording cannot
 * drift between them.
 *
 * The `reviewFieldCount > 0` branch matters: a packet whose field count has not
 * been resolved yet still reports how many fields were seen, rather than
 * silently showing nothing.
 */
export function packetStatusSummary(
  packet: Pick<PacketMeta, 'review' | 'reviewFieldCount'>,
  status: PacketDashboardStatus,
): string | null {
  if (status === 'reviewing') {
    const seen = packetSeenCount(packet)
    return packet.reviewFieldCount > 0
      ? `${seen}/${packet.reviewFieldCount} đã xem`
      : `${seen} trường đã xem`
  }
  if (status !== 'flagged') return null
  if (packet.review.rejection) {
    const selected = new Set(packet.review.rejection.reasons)
    const labels = PACKET_REJECTION_OPTIONS
      .filter(option => selected.has(option.value))
      .map(option => option.label)
    return `Đã từ chối · ${labels.join('; ')}`
  }
  return `${packetFlagCount(packet)} trường đã đánh dấu`
}
