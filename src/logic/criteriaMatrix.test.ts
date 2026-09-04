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
    automatic: true,
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
  // The engine decides this and says so. It used to be inferred here from cell
  // shapes, and the inference was wrong twice over, both times in the
  // reassuring direction: a criterion whose every live cell was a MISSING
  // document read as a live check (so the packet where the tool read almost
  // nothing advertised the smallest coverage gap in the corpus), and the
  // PRESENCE and EXTERNAL criteria -- the ones that ALWAYS need a person --
  // escaped the test because it keyed on a pending reason, which only PENDING
  // cells carry. Measured on 166 real packets it reported 18-24 automated,
  // varying with how empty the packet was. The truth is 10, on every packet.
  const auto = (stt: number) => row(stt, 'ok', [['Excel', 'ok']])
  const manual = (stt: number) => ({
    ...row(stt, 'rv', [['Hợp đồng', 'rv']]),
    automatic: false,
  })

  it('counts what the engine says it can answer', () => {
    expect(automatedCount(payload([auto(1), auto(2), manual(21)]))).toBe(2)
  })

  it('does not count a criterion that always needs a person', () => {
    // #21/#22/#28 are pinned to REVIEW by design and used to count on 166 of
    // 166 packets.
    expect(automatedCount(payload([manual(21), manual(22), manual(28)]))).toBe(0)
  })

  it('does not count a criterion whose documents are merely absent', () => {
    // An absent document is an answer, not a live check -- and it carries no
    // pending reason, which is how it slipped past the old inference.
    const absent = {
      ...row(4, 'missing', [['CCCD/Passport', 'missing']]),
      automatic: false,
    }
    expect(automatedCount(payload([absent]))).toBe(0)
  })

  it('says nothing extra in the headline when everything is automated', () => {
    const parts = criteriaHeadline(payload([auto(1)]))
    expect(parts.some(p => p.includes('tự động'))).toBe(false)
  })

  it('names what has no automatic check, rather than scoring coverage', () => {
    const parts = criteriaHeadline(payload([auto(1), manual(21)]))
    expect(parts).toContain('1 tiêu chí chưa có kiểm tra tự động')
  })

  // A cached bundle against a server predating `automatic`: the field is simply
  // absent. Read straight off the payload it is undefined, the filter drops
  // every row, and the headline reports the maximally alarming and completely
  // wrong "25 tiêu chí chưa có kiểm tra tự động" with no error surfaced
  // anywhere. Neither default is honest -- `?? false` IS that headline, and
  // `?? true` reports zero and hides a real coverage gap -- so the answer is
  // that the tool does not know.
  const unsaid = (stt: number) => {
    const { automatic: _automatic, ...rest } = row(stt, 'ok', [['Excel', 'ok']])
    return rest as CriterionRow
  }

  it('answers null when the payload never said', () => {
    expect(automatedCount(payload([unsaid(1), unsaid(2)]))).toBeNull()
  })

  it('answers null when even one row does not say', () => {
    expect(automatedCount(payload([auto(1), unsaid(2)]))).toBeNull()
  })
})

describe('criteriaHeadline when the payload does not say what is automated', () => {
  const unsaid = (stt: number) => {
    const { automatic: _automatic, ...rest } = row(stt, 'ok', [['Excel', 'ok']])
    return rest as CriterionRow
  }

  it('says the figure is unavailable rather than inventing a number', () => {
    const parts = criteriaHeadline(payload([unsaid(1), unsaid(2)]))
    // Not the wrong count...
    expect(parts.some(p => /\d+ tiêu chí chưa có kiểm tra tự động/.test(p)))
      .toBe(false)
    // ...and not silence either, which is what FULL coverage renders as: the
    // two must not be indistinguishable, or "we could not tell" reads to a
    // reviewer as "nothing is left to check by hand".
    expect(parts).toContain('chưa rõ mức kiểm tra tự động')
    const stated = row(1, 'ok', [['Excel', 'ok']])
    expect(criteriaHeadline(payload([stated])))
      .not.toContain('chưa rõ mức kiểm tra tự động')
    // Everything it does know is still there.
    expect(parts[0]).toBe('2 tiêu chí')
    expect(parts).toContain('2 đạt')
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
