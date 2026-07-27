import type { Bbox } from '../types'

export type DocumentViewMode = 'single' | 'paired'

export const DOCUMENT_VIEW_MODES: ReadonlyArray<{
  mode: DocumentViewMode
  label: string
}> = [
  { mode: 'single', label: '1 trang' },
  { mode: 'paired', label: '2 trang' },
]

export function groupPageIndexes(
  pageCount: number,
  mode: DocumentViewMode,
): number[][] {
  const indexes = Array.from({ length: Math.max(0, pageCount) }, (_, index) => index)
  if (mode === 'single') return indexes.map(index => [index])

  const rows: number[][] = []
  for (let index = 0; index < indexes.length; index += 2) {
    rows.push(indexes.slice(index, index + 2))
  }
  return rows
}

export function clampPageIndex(page: number, pageCount: number): number {
  if (pageCount <= 0) return 0
  return Math.max(0, Math.min(page, pageCount - 1))
}

export function isDocumentPanEnabled(manualPan: boolean, zoomLevel: number): boolean {
  return manualPan || zoomLevel > 1
}

export function dragScrollTarget(
  start: { x: number; y: number; scrollLeft: number; scrollTop: number },
  current: { x: number; y: number },
): ScrollToOptions {
  return {
    left: start.scrollLeft - (current.x - start.x),
    top: start.scrollTop - (current.y - start.y),
    behavior: 'instant',
  }
}

export function autofocusZoomLevel(
  bbox: Pick<Bbox, 'width' | 'height'>,
  renderedPageWidth: number,
  naturalPageWidth: number,
  viewportHeight: number,
): number {
  if (bbox.height <= 0 || renderedPageWidth <= 0 || naturalPageWidth <= 0 || viewportHeight <= 0) {
    return 1
  }
  const renderedBboxHeight = bbox.height * (renderedPageWidth / naturalPageWidth)
  const targetHeight = viewportHeight * 0.14
  return Math.max(1.1, Math.min(2, targetHeight / renderedBboxHeight))
}

export function bboxPercentStyle(
  bbox: Bbox,
  pageWidth: number,
  pageHeight: number,
): { left: string; top: string; width: string; height: string } {
  const width = pageWidth || 1
  const height = pageHeight || 1
  return {
    left: `${(bbox.x / width) * 100}%`,
    top: `${(bbox.y / height) * 100}%`,
    width: `${(bbox.width / width) * 100}%`,
    height: `${(bbox.height / height) * 100}%`,
  }
}
