import type { EvidenceKind } from '../ctv/types'

// Docs whose typed body carries reviewable content — the ones the "AI tóm tắt"
// affordance is offered on. C1 is just the first place a reviewer reaches for it;
// identity scans (CCCD) and the PIT lookup are excluded (nothing to read fast).
export const CONTENT_BEARING_KINDS: readonly EvidenceKind[] = ['contract', 'bbnt', 'appendix', 'commitment']

export function isContentBearing(kind: EvidenceKind): boolean {
  return CONTENT_BEARING_KINDS.includes(kind)
}

// Shown at the foot of every recap popover. Keep in sync with server/recap.py's DISCLAIMER.
export const RECAP_DISCLAIMER =
  'Bản xem thử. AI hỗ trợ đọc nhanh hồ sơ dài/phức tạp — quyết định cuối cùng do bạn.'
