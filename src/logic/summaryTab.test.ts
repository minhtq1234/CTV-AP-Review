import { describe, expect, it } from 'vitest'
import type { SummaryCriterion, SummaryPayload } from '../upload/api'
import {
  MISSING_LABELS,
  SUMMARY_STATUS_PRESENTATION,
  cellPresentation,
  gapNotes,
  headlineParts,
  worstFirst,
} from './summaryTab'

function criterion(
  stt: number,
  status: SummaryCriterion['status'],
  extra: Partial<SummaryCriterion> = {},
): SummaryCriterion {
  return {
    stt,
    code: String(stt),
    label: `Tiêu chí ${stt}`,
    group: 'TH',
    kind: 'compare',
    docs: ['Bảng kê'],
    how: 'Cách kiểm tra',
    status,
    message: 'Thông điệp',
    detail: [],
    ...extra,
  }
}

function payload(
  criteria: SummaryCriterion[],
  extra: Partial<SummaryPayload> = {},
): SummaryPayload {
  const counts = { ok: 0, no: 0, rv: 0, na: 0, missing: 0, pending: 0 }
  for (const c of criteria) counts[c.status] += 1
  return {
    criteria,
    counts,
    people: 41,
    missing: [],
    rosterName: 'bangke.xlsx',
    ...extra,
  }
}

describe('worstFirst', () => {
  it('puts what is wrong above what is fine', () => {
    const order = worstFirst([
      criterion(20, 'ok'),
      criterion(26, 'rv'),
      criterion(30, 'no'),
      criterion(31, 'pending'),
    ]).map(c => c.stt)

    expect(order).toEqual([30, 26, 31, 20])
  })

  it('ranks a missing document above a question', () => {
    // An absent document is a gate failure, not something to look into.
    const order = worstFirst([
      criterion(26, 'rv'),
      criterion(20, 'missing'),
    ]).map(c => c.stt)

    expect(order).toEqual([20, 26])
  })

  it('sinks a not-applicable criterion to the bottom', () => {
    const order = worstFirst([
      criterion(20, 'na'),
      criterion(30, 'ok'),
    ]).map(c => c.stt)

    expect(order).toEqual([30, 20])
  })

  it('keeps checklist order within one status', () => {
    const order = worstFirst([
      criterion(32, 'pending'),
      criterion(20, 'pending'),
      criterion(31, 'pending'),
    ]).map(c => c.stt)

    expect(order).toEqual([20, 31, 32])
  })

  it('leaves the input array untouched', () => {
    const input = [criterion(20, 'ok'), criterion(30, 'no')]
    worstFirst(input)
    expect(input.map(c => c.stt)).toEqual([20, 30])
  })
})

describe('headlineParts', () => {
  it('counts the roster rows the criteria were run over', () => {
    const parts = headlineParts(payload([criterion(20, 'ok')]))
    expect(parts[0]).toBe('41 dòng bảng kê')
  })

  it('names only the statuses actually present', () => {
    const parts = headlineParts(payload([
      criterion(20, 'ok'),
      criterion(26, 'rv'),
      criterion(30, 'ok'),
    ]))

    // problems before passes, always
    expect(parts).toEqual(['41 dòng bảng kê', '1 cần người kiểm tra', '2 đạt'])
  })

  it('leads with the problems', () => {
    const parts = headlineParts(payload([
      criterion(20, 'ok'),
      criterion(30, 'no'),
      criterion(31, 'pending'),
    ]))

    expect(parts.slice(1)).toEqual([
      '1 không khớp', '1 chưa kiểm tra được', '1 đạt',
    ])
  })

  it('says so when no row could be read', () => {
    const parts = headlineParts(payload([criterion(20, 'pending')], { people: 0 }))
    expect(parts[0]).toBe('chưa đọc được dòng nào')
  })
})

describe('gapNotes', () => {
  it('explains each missing input in the reviewer’s terms', () => {
    const notes = gapNotes(payload([], { missing: ['purchaseTotal', 'packets'] }))
    expect(notes).toEqual([
      MISSING_LABELS.purchaseTotal,
      MISSING_LABELS.packets,
    ])
  })

  it('is empty when nothing is missing', () => {
    expect(gapNotes(payload([]))).toEqual([])
  })

  it('never renders a raw key', () => {
    for (const note of Object.values(MISSING_LABELS)) {
      expect(note).not.toMatch(/[a-z]+[A-Z]/)
    }
  })
})

describe('SUMMARY_STATUS_PRESENTATION', () => {
  it('covers every status the backend can return', () => {
    expect(Object.keys(SUMMARY_STATUS_PRESENTATION).sort()).toEqual(
      ['missing', 'na', 'no', 'ok', 'pending', 'rv'],
    )
  })

  it('distinguishes “not checked” from “fine”', () => {
    // The whole point of the five-state vocabulary.
    expect(SUMMARY_STATUS_PRESENTATION.pending.label)
      .not.toBe(SUMMARY_STATUS_PRESENTATION.ok.label)
    expect(SUMMARY_STATUS_PRESENTATION.pending.tone).toBe('unknown')
    expect(SUMMARY_STATUS_PRESENTATION.ok.tone).toBe('good')
  })
})

describe('cellPresentation', () => {
  // `? Chưa kiểm tra được` was doing five jobs. Only `unread` and `unmatched`
  // are facts about the packet in front of the reviewer; showing all five
  // identically taught them to skip the chip, and with it the two that matter.
  it('keeps a non-pending status exactly as it was', () => {
    for (const status of ['ok', 'no', 'rv', 'missing', 'na'] as const) {
      expect(cellPresentation({ status })).toBe(
        SUMMARY_STATUS_PRESENTATION[status])
    }
  })

  it('mutes the two that are about scope, not about this packet', () => {
    expect(cellPresentation({ status: 'pending', pendingReason: 'not-automated' }))
      .toMatchObject({ tone: 'muted' })
    expect(cellPresentation({ status: 'pending', pendingReason: 'roster-level' }))
      .toMatchObject({ tone: 'muted' })
  })

  it('says where a roster-level document is actually checked', () => {
    expect(cellPresentation({ status: 'pending', pendingReason: 'roster-level' })
      .label).toContain('Tổng hợp')
  })

  it('leaves the packet-specific ones as genuine unknowns', () => {
    for (const reason of ['unread', 'unmatched'] as const) {
      expect(cellPresentation({ status: 'pending', pendingReason: reason }))
        .toMatchObject({ tone: 'unknown' })
    }
  })

  it('flags an empty bảng kê cell as needing attention, not as unknown', () => {
    // The tool knows the answer: the submitter left it blank.
    expect(cellPresentation({
      status: 'pending', pendingReason: 'no-roster-value',
    })).toMatchObject({ tone: 'attention' })
  })

  it('falls back to plain pending for a reason it does not know', () => {
    expect(cellPresentation({ status: 'pending', pendingReason: 'invented' }))
      .toBe(SUMMARY_STATUS_PRESENTATION.pending)
    expect(cellPresentation({ status: 'pending' }))
      .toBe(SUMMARY_STATUS_PRESENTATION.pending)
  })
})
