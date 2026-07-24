// Pure page/document navigation helpers for the scan pane. Kept out of the
// React components so the index math (clamping, rolling into adjacent docs)
// is unit-tested (the components themselves carry no tests).

/** Clamp a page index into a doc's real range; 0 when the doc has no pages. */
export function clampPage(page: number, pageCount: number): number {
  if (pageCount <= 0) return 0
  return Math.max(0, Math.min(page, pageCount - 1))
}
