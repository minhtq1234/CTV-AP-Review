import { describe, expect, it } from 'vitest'
import type { UploadInspection } from '../upload/api'
import {
  imageColumnLine,
  needsAttention,
  rosterLine,
  UNRECOGNISED,
} from './uploadInspection'

const inspection = (overrides: Partial<UploadInspection> = {}): UploadInspection => ({
  rosterSheet: 'CTV',
  people: 25,
  columns: ['cccd', 'gross', 'name'],
  images: [
    { sheet: 'CCCD', column: 'D', kind: 'card', count: 24 },
    { sheet: 'CCCD', column: 'E', kind: 'card', count: 24 },
    { sheet: 'CCCD', column: 'G', kind: 'bank', count: 25 },
    { sheet: 'MST', column: 'D', kind: 'tax', count: 25 },
  ],
  ...overrides,
})

describe('the declaration a reviewer confirms', () => {
  it('names the sheet it read and how many people it found', () => {
    expect(rosterLine(inspection())).toContain('CTV')
    expect(rosterLine(inspection())).toContain('25')
  })

  it('says plainly when no sheet qualified', () => {
    expect(rosterLine(inspection({ rosterSheet: null }))).toBe(
      'Không nhận ra sheet bảng kê',
    )
  })

  it('names each image population by column, sheet and count', () => {
    const line = imageColumnLine({ sheet: 'CCCD', column: 'D', kind: 'card', count: 24 })
    expect(line).toContain('24')
    expect(line).toContain('cột D')
    expect(line).toContain('sheet CCCD')
  })

  it('marks an unexplained image column rather than describing it as nothing', () => {
    const line = imageColumnLine({ sheet: 'CCCD', column: 'H', kind: null, count: 9 })
    expect(line).toContain(UNRECOGNISED)
    expect(line).toContain('cột H')
  })
})

describe('what deserves a second look', () => {
  it('a clean inspection does not', () => {
    expect(needsAttention(inspection())).toBe(false)
  })

  it('an unrecognised image column does', () => {
    const images = [...inspection().images, {
      sheet: 'CCCD', column: 'H', kind: null, count: 9,
    }]
    expect(needsAttention(inspection({ images }))).toBe(true)
  })

  it('no roster sheet, or a sheet with nobody in it, does', () => {
    expect(needsAttention(inspection({ rosterSheet: null }))).toBe(true)
    expect(needsAttention(inspection({ people: 0 }))).toBe(true)
  })

  it('does not cry wolf on a workbook with no image headers at all', () => {
    // The real July cccd.xlsx: 42 images across nine sheets, none classified,
    // because that template has no image headers and pairs by proximity. It is
    // a supported input, not an anomaly.
    const images = Array.from({ length: 42 }, (_, index) => ({
      sheet: `Trang 0${(index % 9) + 1}`,
      column: index % 2 ? 'H' : 'B',
      kind: null,
      count: 5,
    }))
    expect(needsAttention(inspection({ images }))).toBe(false)
  })
})
