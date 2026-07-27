import type { PacketReview } from '../upload/api'

export function allSeen(review: PacketReview, fieldKeys: string[]): boolean {
  return fieldKeys.every(k => review.fields[k]?.seen === true)
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
