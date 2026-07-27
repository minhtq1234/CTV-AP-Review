import { describe, expect, it } from 'vitest'
import {
  DOCUMENT_VIEW_MODES,
  bboxPercentStyle,
  clampPageIndex,
  groupPageIndexes,
} from './documentView'

describe('document view modes', () => {
  it('exposes exactly the approved one-page and two-page modes', () => {
    expect(DOCUMENT_VIEW_MODES).toEqual([
      { mode: 'single', label: '1 trang' },
      { mode: 'paired', label: '2 trang' },
    ])
  })

  it('keeps every page in a single vertical column', () => {
    expect(groupPageIndexes(3, 'single')).toEqual([[0], [1], [2]])
  })

  it('keeps every page in paired rows without dropping an odd final page', () => {
    expect(groupPageIndexes(3, 'paired')).toEqual([[0, 1], [2]])
  })
})

describe('document focus geometry', () => {
  it('clamps a target page into the active document', () => {
    expect(clampPageIndex(-2, 3)).toBe(0)
    expect(clampPageIndex(9, 3)).toBe(2)
    expect(clampPageIndex(4, 0)).toBe(0)
  })

  it('converts a natural-pixel bbox to hand-derived responsive percentages', () => {
    expect(bboxPercentStyle(
      { x: 100, y: 50, width: 200, height: 100 },
      1000,
      500,
    )).toEqual({
      left: '10%',
      top: '10%',
      width: '20%',
      height: '20%',
    })
  })
})
