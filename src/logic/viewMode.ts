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
