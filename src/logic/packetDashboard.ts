import type { PacketMeta } from '../upload/api'

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
  flagged: 'Flagged',
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
])

export function attentionReasons(
  packet: Pick<PacketMeta, 'matchedBy' | 'flags' | 'boundaryAssessment'>,
): string[] {
  const reasons: string[] = []
  const add = (reason: string) => {
    if (!reasons.includes(reason)) reasons.push(reason)
  }

  if (
    packet.boundaryAssessment.status === 'review'
    && packet.boundaryAssessment.suspectedMultiplePackets
  ) {
    add('Nghi ngờ nhiều hồ sơ trong một gói')
  }
  if (packet.matchedBy === 'name') add('Chỉ khớp theo tên')
  if (packet.matchedBy === 'unmatched') add('Không khớp bảng kê')
  if (packet.flags.includes('auto-merged')) add('Cần xác nhận ranh giới')
  if (packet.flags.includes('near-threshold')) add('Ranh giới gần ngưỡng')
  if (packet.flags.includes('length-out-of-range')) add('Số trang bất thường')
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
  T extends Pick<PacketMeta, 'matchedBy' | 'flags' | 'boundaryAssessment'>,
>(packets: ReadonlyArray<T>): T[] {
  return [
    ...packets.filter(packet => attentionReasons(packet).length > 0),
    ...packets.filter(packet => attentionReasons(packet).length === 0),
  ]
}
