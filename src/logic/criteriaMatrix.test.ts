import { describe, expect, it } from 'vitest'
import type { CriteriaPayload, CriterionRow, SummaryStatus } from '../upload/api'
import {
  DECIDABLE_STATUSES,
  cellFor,
  choicesFor,
  confirms,
  decisionKey,
  isDecided,
  automatedCount,
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

describe('automatedCount', () => {
  // A criterion every one of whose cells says `not-automated` has no
  // extractor behind it: no packet will ever change its answer, so it is not
  // something the tool checks. Telling the reviewer the denominator beats
  // leaving them to infer it from a column of identical chips.
  function unautomated(stt: number): CriterionRow {
    const built = row(stt, 'pending', [['Hợp đồng', 'pending'], ['BBNT', 'pending']])
    return {
      ...built,
      cells: built.cells.map(cell => ({ ...cell, pendingReason: 'not-automated' as const })),
    }
  }

  it('ignores the Excel reference column, which is not a check', () => {
    // #08's shape: the bảng kê has a value (green) and both document columns
    // have no extractor. Counting Excel made this never fire.
    const built = row(8, 'pending', [
      ['Excel', 'ok'], ['Hợp đồng', 'pending'], ['BBNT', 'pending'],
    ])
    const shaped = {
      ...built,
      cells: [
        built.cells[0],
        { ...built.cells[1], pendingReason: 'not-automated' as const },
        { ...built.cells[2], pendingReason: 'not-automated' as const },
      ],
    }
    expect(automatedCount(payload([shaped]))).toBe(0)
  })

  it('also ignores the batch-level column, checked on another tab', () => {
    // #09/#13/#27's shape. Leaving this in reported 24 of 25 automated on a
    // real packet where far fewer are.
    const built = row(9, 'pending', [
      ['Excel', 'ok'], ['Hợp đồng', 'pending'],
      ['BBNT', 'pending'], ['Bảng Kê Thu Mua', 'pending'],
    ])
    const shaped = {
      ...built,
      cells: [
        built.cells[0],
        { ...built.cells[1], pendingReason: 'not-automated' as const },
        { ...built.cells[2], pendingReason: 'not-automated' as const },
        { ...built.cells[3], pendingReason: 'roster-level' as const },
      ],
    }
    expect(automatedCount(payload([shaped]))).toBe(0)
  })

  it('ignores an n/a cell, which is not a check that failed', () => {
    // #09/#10/#11/#13's real shape: an n/a Phụ lục/KPI column. While those
    // counted, the rule reported 23 of 25 automated on a packet where six
    // criteria compare nothing.
    const built = row(11, 'pending', [
      ['Excel', 'pending'], ['Hợp đồng', 'pending'],
      ['BBNT', 'pending'], ['Phụ lục/KPI', 'na'],
    ])
    const shaped = {
      ...built,
      cells: [
        { ...built.cells[0], pendingReason: 'no-roster-value' as const },
        { ...built.cells[1], pendingReason: 'not-automated' as const },
        { ...built.cells[2], pendingReason: 'not-automated' as const },
        built.cells[3],
      ],
    }
    expect(automatedCount(payload([shaped]))).toBe(0)
  })

  it('excludes a criterion whose every cell has no extractor', () => {
    expect(automatedCount(payload([
      row(1, 'ok', [['Excel', 'ok']]),
      unautomated(8),
      unautomated(9),
    ]))).toBe(1)
  })

  it('counts a criterion that is merely unread on this packet', () => {
    // `unread` means the document is here and its value would not read --
    // a fact about this packet, not about the tool's scope.
    const built = row(2, 'pending', [['Hợp đồng', 'pending']])
    const unread = {
      ...built,
      cells: built.cells.map(c => ({ ...c, pendingReason: 'unread' as const })),
    }
    expect(automatedCount(payload([unread]))).toBe(1)
  })

  it('counts a criterion with a mix, since something can still be read', () => {
    const built = row(3, 'pending', [['Hợp đồng', 'pending'], ['BBNT', 'pending']])
    const mixed = {
      ...built,
      cells: [
        { ...built.cells[0], pendingReason: 'not-automated' as const },
        { ...built.cells[1], pendingReason: 'unread' as const },
      ],
    }
    expect(automatedCount(payload([mixed]))).toBe(1)
  })

  it('says nothing extra in the headline when everything is automated', () => {
    const parts = criteriaHeadline(payload([row(1, 'ok', [['Excel', 'ok']])]))
    expect(parts.some(p => p.includes('tự động'))).toBe(false)
  })

  it('names what has no automatic check, rather than scoring coverage', () => {
    // Not "1/2 automated": that reads as a property of the tool, and it is
    // neither -- it is per packet, and several counted criteria never answer
    // on their own.
    const parts = criteriaHeadline(payload([
      row(1, 'ok', [['Excel', 'ok']]),
      unautomated(8),
    ]))
    expect(parts).toContain('1 tiêu chí chưa có kiểm tra tự động')
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

  it('offers the current status too, as a confirmation', () => {
    // Without it a reviewer who agrees with a computed `no` cannot say so, and
    // `cần gửi lại` — which counts conclusions — stays at zero forever.
    expect(choicesFor(cell('Excel', 'ok'))).toEqual(DECIDABLE_STATUSES)
  })

  it('knows which choice is agreement rather than a change', () => {
    const c = cell('Excel', 'no')
    expect(confirms(c, 'no')).toBe(true)
    expect(confirms(c, 'ok')).toBe(false)
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
