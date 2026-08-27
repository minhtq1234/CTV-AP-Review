import { describe, expect, it } from 'vitest'
import type { CriteriaPayload, CriterionRow, SummaryStatus } from '../upload/api'
import {
  DECIDABLE_STATUSES,
  cellFor,
  choicesFor,
  decisionKey,
  isDecided,
  criteriaHeadline,
  groupsInOrder,
  matrixRows,
  cardRows,
  visibleColumns,
} from './criteriaMatrix'

function row(
  stt: number,
  status: SummaryStatus,
  cells: Array<[string, SummaryStatus]>,
  extra: Partial<CriterionRow> = {},
): CriterionRow {
  return {
    stt,
    code: String(stt).padStart(2, '0'),
    label: `Tiêu chí ${stt}`,
    group: '01',
    groupLabel: 'Thông tin cá nhân',
    kind: 'compare',
    render: 'matrix',
    how: 'Cách kiểm tra cụ thể của Acc, dài hơn bốn mươi ký tự để có ý nghĩa.',
    status,
    note: '',
    cells: cells.map(([document, s]) => ({
      document, status: s, value: '', note: 'ghi chú', evidence: [],
    })),
    ...extra,
  }
}

const COLUMNS = ['Excel', 'CCCD/Passport', 'Hợp đồng', 'BBNT', 'Bảng Kê Thu Mua']

function payload(criteria: CriterionRow[]): CriteriaPayload {
  const counts = { ok: 0, no: 0, rv: 0, na: 0, missing: 0, pending: 0 }
  for (const c of criteria) counts[c.status] += 1
  return {
    packet: 0,
    name: 'CTV',
    documents: COLUMNS,
    criteria,
    counts,
    groups: { '01': { label: 'Thông tin cá nhân', counts } },
    matchedRoster: true,
  }
}

describe('visibleColumns', () => {
  it('keeps only the documents some criterion actually spans', () => {
    const rows = [row(1, 'ok', [['Excel', 'ok'], ['Hợp đồng', 'ok']])]
    expect(visibleColumns(COLUMNS, rows)).toEqual(['Excel', 'Hợp đồng'])
  })

  it('preserves the payload order rather than first-seen order', () => {
    const rows = [row(1, 'ok', [['BBNT', 'ok'], ['Excel', 'ok']])]
    expect(visibleColumns(COLUMNS, rows)).toEqual(['Excel', 'BBNT'])
  })

  it('ignores criteria rendered as cards when choosing columns', () => {
    const rows = [
      row(1, 'ok', [['Excel', 'ok']]),
      row(17, 'ok', [['BBNT', 'ok']], { render: 'card' }),
    ]
    expect(visibleColumns(COLUMNS, rows)).toEqual(['Excel'])
  })
})

describe('cellFor', () => {
  it('finds a criterion’s cell for a column', () => {
    const r = row(1, 'no', [['Excel', 'ok'], ['BBNT', 'no']])
    expect(cellFor(r, 'BBNT')?.status).toBe('no')
  })

  it('returns null for a document the criterion does not span', () => {
    // Renders as a static dash, not a clickable `na`.
    const r = row(1, 'ok', [['Excel', 'ok']])
    expect(cellFor(r, 'BBNT')).toBeNull()
  })
})

describe('row split', () => {
  it('separates the matrix rows from the card ones', () => {
    const rows = [
      row(1, 'ok', [['Excel', 'ok']]),
      row(17, 'ok', [['Excel', 'ok']], { render: 'card' }),
    ]
    expect(matrixRows(rows).map(r => r.stt)).toEqual([1])
    expect(cardRows(rows).map(r => r.stt)).toEqual([17])
  })
})

describe('groupsInOrder', () => {
  it('sorts by the group code so Acc’s sections keep their order', () => {
    const groups = {
      '03': { label: 'Dịch vụ', counts: {} as Record<SummaryStatus, number> },
      '01': { label: 'Cá nhân', counts: {} as Record<SummaryStatus, number> },
    }
    expect(groupsInOrder(groups).map(g => g.code)).toEqual(['01', '03'])
  })
})

describe('criteriaHeadline', () => {
  it('counts criteria, not cells', () => {
    // A criterion spanning five documents must not weigh five times as much.
    const parts = criteriaHeadline(payload([
      row(1, 'no', [['Excel', 'ok'], ['BBNT', 'no'], ['Hợp đồng', 'no']]),
      row(2, 'ok', [['Excel', 'ok']]),
    ]))
    expect(parts).toEqual(['2 tiêu chí', '1 không khớp', '1 đạt'])
  })

  it('leads with the problems', () => {
    const parts = criteriaHeadline(payload([
      row(1, 'ok', [['Excel', 'ok']]),
      row(2, 'missing', [['Excel', 'missing']]),
      row(3, 'no', [['Excel', 'no']]),
    ]))
    expect(parts.slice(1)).toEqual(['1 không khớp', '1 thiếu chứng từ', '1 đạt'])
  })

  it('says when the packet matched no roster row at all', () => {
    const parts = criteriaHeadline({
      ...payload([row(1, 'pending', [['Excel', 'pending']])]),
      matchedRoster: false,
    })
    expect(parts[0]).toBe('chưa khớp bảng kê')
  })
})

describe('recording a decision', () => {
  const cell = (
    document: string,
    status: SummaryStatus,
    computedStatus: SummaryStatus = status,
  ) => ({ document, status, computedStatus, value: '', note: '', evidence: [] })

  it('offers every status a person can decide', () => {
    // `na` is excluded: it says the document is outside the criterion — a fact
    // about the checklist, not a judgment.
    expect(DECIDABLE_STATUSES).toEqual(['ok', 'no', 'rv', 'missing', 'pending'])
    expect(DECIDABLE_STATUSES).not.toContain('na')
  })

  it('knows when a reviewer has changed a cell', () => {
    expect(isDecided(cell('Excel', 'ok', 'rv'))).toBe(true)
    expect(isDecided(cell('Excel', 'ok'))).toBe(false)
  })

  it('treats a missing computedStatus as undecided', () => {
    // Older payloads have no such field.
    expect(isDecided({ document: 'Excel', status: 'ok', value: '', note: '',
                       evidence: [] } as never)).toBe(false)
  })

  it('addresses a cell the way the server keys it', () => {
    expect(decisionKey(21, 'Hợp đồng')).toBe('21:Hợp đồng')
    expect(decisionKey(7, 'Excel')).toBe('07:Excel')
  })

  it('will not offer the status a cell already has', () => {
    // An override to the same status records nothing, and the server refuses it.
    expect(choicesFor(cell('Excel', 'ok'))).toEqual(
      ['no', 'rv', 'missing', 'pending'])
  })

  it('offers nothing for a cell outside the criterion', () => {
    expect(choicesFor(null)).toEqual([])
  })

  it('offers nothing for an `na` cell', () => {
    expect(choicesFor(cell('Excel', 'na'))).toEqual([])
  })

  it('still offers the computed status back to a decided cell', () => {
    // Undoing a decision means deciding it back to what the engine said.
    expect(choicesFor(cell('Excel', 'ok', 'rv'))).toContain('rv')
  })
})
