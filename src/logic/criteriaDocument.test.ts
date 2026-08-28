import { describe, expect, it } from 'vitest'
import { documentKindForColumn, cellAction } from './criteriaDocument'

describe('documentKindForColumn', () => {
  it('maps every column that has a document behind it', () => {
    expect(documentKindForColumn('Hợp đồng')).toBe('contract')
    expect(documentKindForColumn('BBNT')).toBe('bbnt')
    expect(documentKindForColumn('Phụ lục/KPI')).toBe('appendix')
    expect(documentKindForColumn('Cam kết PIT')).toBe('commitment')
  })

  it('maps the MST lookup column to the pit kind, not to an mst kind', () => {
    // The column is named for MST; the document is the tax-lookup page, whose
    // kind is `pit`. Getting this wrong opens the wrong document.
    expect(documentKindForColumn('Website tra cứu MST')).toBe('pit')
  })

  it('maps the identity column to the card front', () => {
    // The back is reachable through the viewer's own tabs, so the click does
    // not have to choose between them.
    expect(documentKindForColumn('CCCD/Passport')).toBe('id_front')
  })

  it('has no document for the reference columns', () => {
    expect(documentKindForColumn('Excel')).toBeNull()
    expect(documentKindForColumn('Bảng Kê Thu Mua')).toBeNull()
  })

  it('returns null for a column it has never heard of', () => {
    expect(documentKindForColumn('Cột Mới')).toBeNull()
  })
})

describe('cellAction', () => {
  it('opens the document for an ordinary cell', () => {
    expect(cellAction('Hợp đồng', 'no')).toEqual({ kind: 'open', docKind: 'contract' })
  })

  it('does nothing for the Excel column', () => {
    expect(cellAction('Excel', 'ok')).toEqual({ kind: 'none' })
  })

  it('sends the roster-level column to Tổng hợp', () => {
    expect(cellAction('Bảng Kê Thu Mua', 'pending')).toEqual({ kind: 'summary' })
  })

  it('does nothing for a cell that does not apply', () => {
    // `na` means the criterion does not apply to this document at all -- there
    // is nothing to look at, and the note already says so.
    expect(cellAction('Phụ lục/KPI', 'na')).toEqual({ kind: 'none' })
  })

  it('still opens a document for a missing or pending cell', () => {
    // `missing` is a claim about a document; the reviewer may well want to look
    // at what IS in the packet to confirm it. The dialog handles the case where
    // the document genuinely is not there.
    expect(cellAction('BBNT', 'missing')).toEqual({ kind: 'open', docKind: 'bbnt' })
    expect(cellAction('BBNT', 'pending')).toEqual({ kind: 'open', docKind: 'bbnt' })
  })
})
