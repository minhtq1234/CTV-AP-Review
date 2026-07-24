export type ViewMode = '1' | 'cont' | '2'

export const VIEW_MODES: ReadonlyArray<{ mode: ViewMode; label: string }> = [
  { mode: '1', label: '1 trang' },
  { mode: 'cont', label: 'Cuộn liên tục' },
  { mode: '2', label: '2 trang' },
]

/** Continuous-mode width multiplier, clamped to a sane range (1 = fit width). */
export function clampZoom(z: number): number {
  return Math.max(0.5, Math.min(4, z))
}

import type { CheckItem } from '../ctv/types'

const SIGNATURE_CODES = new Set(['B3', 'C2'])
const SKIM_CODES = new Set(['G-DOC', 'D3', 'D1'])

/**
 * Default view mode for a check (#2). value + signature land on a single page
 * (1 trang; value auto-zooms to its bbox, signature to its focus band); skim/
 * glance checks open in continuous scroll. A manual toolbar override is layered
 * on top in FolderReview and reset when the check changes.
 */
export function viewModeForCheck(c: CheckItem): ViewMode {
  if (c.kind === 'value') return '1'
  if (SIGNATURE_CODES.has(c.code)) return '1'
  if (SKIM_CODES.has(c.code)) return 'cont'
  return '1'
}
