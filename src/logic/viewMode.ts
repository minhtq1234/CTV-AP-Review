import type { CheckItem } from '../ctv/types'

// '1' (single page, auto-zoomed to a located field) is NOT a manual toolbar mode — it's
// entered automatically when a VALUE check is selected (see viewModeForCheck / FolderReview).
// The toolbar only offers continuous scroll and the two-page spread.
export type ViewMode = '1' | 'cont' | '2'

export const VIEW_MODES: ReadonlyArray<{ mode: ViewMode; label: string }> = [
  { mode: 'cont', label: 'Cuộn liên tục' },
  { mode: '2', label: '2 trang' },
]

/** Continuous-mode width multiplier, clamped to a sane range (1 = fit width). */
export function clampZoom(z: number): number {
  return Math.max(0.5, Math.min(4, z))
}

/**
 * Default view when a check is (re)selected. A VALUE check (a located field with a
 * bbox) auto-focuses the single page it sits on ('1' — zoom to the field + red box +
 * pinned bảng-kê value). Every other check (signature gates B3/C2, glance/confirm
 * G-DOC/C1/D1/D3) just opens its document in continuous scroll — no auto-zoom. A manual
 * toolbar toggle (cont/2) overrides this until the next check is selected.
 */
export function viewModeForCheck(c: CheckItem): ViewMode {
  return c.kind === 'value' ? '1' : 'cont'
}
