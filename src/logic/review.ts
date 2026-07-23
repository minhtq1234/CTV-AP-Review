import type { PacketReview, PacketMeta } from '../upload/api'

export type PacketStatusKind = 'untouched' | 'in_review' | 'clear' | 'needs_resubmit'

export function allSeen(review: PacketReview, codes: string[]): boolean {
  return codes.every(k => review.items[k]?.seen === true)
}

function needsResubmit(p: Pick<PacketMeta, 'matchedBy' | 'review'>): boolean {
  const flagged = Object.values(p.review?.items ?? {}).some(f => f.flag)
  return flagged || p.matchedBy === 'name' || p.matchedBy === 'unmatched'
}

export function packetStatus(p: Pick<PacketMeta, 'matchedBy' | 'review'>): PacketStatusKind {
  if (!p.review?.done) {
    return Object.values(p.review?.items ?? {}).some(f => f.seen) ? 'in_review' : 'untouched'
  }
  return needsResubmit(p) ? 'needs_resubmit' : 'clear'
}

export const PACKET_STATUS_LABEL: Record<PacketStatusKind, string> = {
  untouched: 'Chưa xem',
  in_review: 'Đang xem',
  clear: 'Xong · sạch',
  needs_resubmit: 'Xong · cần gửi lại',
}

// Position the roster callout relative to a field box (viewport px). Prefer just
// above the box; flip below when there isn't `calloutH` px of room above.
export function calloutAnchor(
  box: { left: number; top: number; width: number; height: number },
  calloutH: number,
  paneH: number,
): { left: number; top: number; placement: 'above' | 'below' } {
  const above = box.top >= calloutH + 8
  return above
    ? { left: box.left, top: box.top - calloutH - 8, placement: 'above' }
    : { left: box.left, top: Math.min(box.top + box.height + 8, paneH - calloutH), placement: 'below' }
}
