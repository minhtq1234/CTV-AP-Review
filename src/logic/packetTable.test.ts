import { describe, expect, it } from 'vitest'
import type { PacketMeta, SummaryStatus } from '../upload/api'
import {
  NO_FILTERS,
  NO_NAME,
  COUNTER_ORDER,
  documentsLabel,
  filterRows,
  isFiltering,
  packetDisplayName,
  packetRow,
  packetRows,
  statusCounts,
  visibleCounters,
} from './packetTable'

function P(over: Partial<PacketMeta> = {}): PacketMeta {
  return {
    index: 0,
    name: 'Huỳnh Thị Thúy Phượng',
    pages: [8, 15],
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: '', name: '' },
    rosterIdentity: { cccd: '079189016370', name: 'Huỳnh Thị Thúy Phượng' },
    review: { done: false, fields: {}, rejection: null },
    reviewFieldCount: 6,
    ...over,
  } as PacketMeta
}

describe('packetDisplayName', () => {
  it('prefers the roster name, then the packet name, then the OCR name', () => {
    expect(packetDisplayName(P({
      rosterIdentity: { cccd: '1', name: 'Tên Trên Bảng Kê' },
      ocrIdentity: { cccd: '1', name: 'Tên Đọc Từ Scan' },
    }))).toBe('Tên Trên Bảng Kê')
    expect(packetDisplayName(P({ rosterIdentity: null, name: 'Tên Gói Hồ Sơ',
                                 ocrIdentity: { cccd: '', name: 'Tên Đọc Từ Scan' } })))
      .toBe('Tên Gói Hồ Sơ')
    expect(packetDisplayName(P({ rosterIdentity: null, name: null,
                                 ocrIdentity: { cccd: '', name: 'Đọc Từ Scan' } })))
      .toBe('Đọc Từ Scan')
  })

  it('falls back to the same unmatched label the packet table uses', () => {
    expect(packetDisplayName(P({ rosterIdentity: null, name: null,
                                 ocrIdentity: { cccd: '', name: '' } }))).toBe(NO_NAME)
  })
})

describe('packetRow', () => {
  it('numbers rows from 1, zero-padded', () => {
    expect(packetRow(P({ index: 0 })).stt).toBe('01')
    expect(packetRow(P({ index: 40 })).stt).toBe('41')
  })

  it('prefers the roster name — that is the one the reviewer is checking against', () => {
    const row = packetRow(P({
      rosterIdentity: { cccd: '1', name: 'Tên Trên Bảng Kê' },
      ocrIdentity: { cccd: '1', name: 'Tên Đọc Từ Scan' },
    }))
    expect(row.name).toBe('Tên Trên Bảng Kê')
  })

  it('falls back to the OCR name, then to a placeholder — never a blank row', () => {
    expect(packetRow(P({ rosterIdentity: null, name: null,
                         ocrIdentity: { cccd: '', name: 'Đọc Từ Scan' } })).name)
      .toBe('Đọc Từ Scan')
    expect(packetRow(P({ rosterIdentity: null, name: null,
                         ocrIdentity: { cccd: '', name: '' } })).name).toBe(NO_NAME)
  })

  it('carries the engine status through with its existing label and tone', () => {
    // Reuses SUMMARY_STATUS_PRESENTATION so a column and the 25-criterion
    // matrix cannot disagree about the same packet.
    const row = packetRow(P({ aiStatus: 'missing' }))
    expect(row.ai).toBe('missing')
    expect(row.aiLabel).toBe('Thiếu chứng từ')
    expect(row.aiTone).toBe('bad')
  })

  it('keeps `no` and `missing` apart', () => {
    // The design mock folded missing into "Không khớp"; on the July batch that
    // is 22 vs 6 packets doing different jobs for the reviewer.
    expect(packetRow(P({ aiStatus: 'no' })).aiLabel).toBe('Không khớp')
    expect(packetRow(P({ aiStatus: 'missing' })).aiLabel).toBe('Thiếu chứng từ')
  })

  it('says so rather than implying a verdict when there is no roster row', () => {
    const row = packetRow(P({ aiStatus: null, rosterIdentity: null }))
    expect(row.ai).toBeNull()
    expect(row.aiLabel).toBe('Chưa đối chiếu được')
    expect(row.aiTone).toBe('muted')
  })

  it('treats an older payload without the new fields as unknown, not as passing', () => {
    const row = packetRow(P())
    expect(row.ai).toBeNull()
    expect(row.documents).toBeNull()
    expect(row.documentsComplete).toBeNull()
    expect(row.documentsLabel).toBe('')
    expect(row.hasCommitment).toBeNull()
  })

  it('reports the reviewer’s own conclusion separately from the engine’s', () => {
    const done = packetRow(P({ review: { done: true, fields: {}, rejection: null } }))
    expect(done.fa).toBe('completed')
    expect(done.faLabel).toBe('Đã xong')
    const flagged = packetRow(P({
      review: { done: true, fields: { hoten: { seen: true, flag: { reason: 'sai', note: '' } } },
                rejection: null },
    } as never))
    expect(flagged.fa).toBe('flagged')
  })
})

describe('documentsLabel', () => {
  it('shows the fraction present, not the fraction missing', () => {
    expect(documentsLabel({ span: 6, missing: [] })).toBe('Đầy đủ (6/6)')
    expect(documentsLabel({ span: 6, missing: ['BBNT'] })).toBe('Thiếu (5/6)')
    expect(documentsLabel({ span: 6, missing: ['BBNT', 'Phụ lục/KPI'] })).toBe('Thiếu (4/6)')
  })

  it('is empty when the span is unknown — no invented denominator', () => {
    expect(documentsLabel(null)).toBe('')
    expect(documentsLabel({ span: 0, missing: [] })).toBe('')
  })
})

describe('filterRows', () => {
  const rows = packetRows([
    P({ index: 0, name: 'Huỳnh Thị Thúy Phượng', aiStatus: 'no',
        documents: { span: 6, missing: [] }, hasCommitment: false }),
    P({ index: 1, name: 'Đoàn Dương Thanh Vân', aiStatus: 'missing',
        documents: { span: 6, missing: ['BBNT'] }, hasCommitment: true,
        rosterIdentity: { cccd: '2', name: 'Đoàn Dương Thanh Vân' } }),
    P({ index: 2, name: 'Lý Gia Huy', aiStatus: 'ok',
        documents: { span: 6, missing: [] }, hasCommitment: false,
        review: { done: true, fields: {}, rejection: null },
        rosterIdentity: { cccd: '3', name: 'Lý Gia Huy' } }),
  ])

  it('passes everything through with no filters set', () => {
    expect(filterRows(rows, NO_FILTERS)).toHaveLength(3)
  })

  it('searches the name case-insensitively', () => {
    expect(filterRows(rows, { ...NO_FILTERS, q: 'gia huy' }).map(r => r.index)).toEqual([2])
    expect(filterRows(rows, { ...NO_FILTERS, q: 'HUỲNH' }).map(r => r.index)).toEqual([0])
  })

  it('ignores surrounding whitespace in the query', () => {
    expect(filterRows(rows, { ...NO_FILTERS, q: '   ' })).toHaveLength(3)
  })

  it('filters by a single engine status, keeping `no` and `missing` distinct', () => {
    expect(filterRows(rows, { ...NO_FILTERS, ai: 'no' }).map(r => r.index)).toEqual([0])
    expect(filterRows(rows, { ...NO_FILTERS, ai: 'missing' }).map(r => r.index)).toEqual([1])
  })

  it('filters by document completeness', () => {
    expect(filterRows(rows, { ...NO_FILTERS, documents: 'complete' }).map(r => r.index))
      .toEqual([0, 2])
    expect(filterRows(rows, { ...NO_FILTERS, documents: 'missing' }).map(r => r.index))
      .toEqual([1])
  })

  it('excludes rows of unknown completeness from BOTH completeness filters', () => {
    // An older payload has no `documents`; it must not be claimed as complete.
    const unknown = packetRows([P({ index: 9 })])
    expect(filterRows(unknown, { ...NO_FILTERS, documents: 'complete' })).toEqual([])
    expect(filterRows(unknown, { ...NO_FILTERS, documents: 'missing' })).toEqual([])
  })

  it('filters by the reviewer’s conclusion', () => {
    expect(filterRows(rows, { ...NO_FILTERS, fa: 'completed' }).map(r => r.index)).toEqual([2])
    expect(filterRows(rows, { ...NO_FILTERS, fa: 'unseen' }).map(r => r.index)).toEqual([0, 1])
  })

  it('filters by cam kết thuế', () => {
    expect(filterRows(rows, { ...NO_FILTERS, commitment: 'yes' }).map(r => r.index)).toEqual([1])
    expect(filterRows(rows, { ...NO_FILTERS, commitment: 'no' }).map(r => r.index)).toEqual([0, 2])
  })

  it('combines filters conjunctively', () => {
    expect(filterRows(rows, { ...NO_FILTERS, documents: 'complete', commitment: 'no' })
      .map(r => r.index)).toEqual([0, 2])
    expect(filterRows(rows, { ...NO_FILTERS, ai: 'ok', commitment: 'yes' })).toEqual([])
  })
})

describe('isFiltering', () => {
  it('is false only when nothing is narrowing the list', () => {
    expect(isFiltering(NO_FILTERS)).toBe(false)
    expect(isFiltering({ ...NO_FILTERS, q: '  ' })).toBe(false)
    expect(isFiltering({ ...NO_FILTERS, q: 'a' })).toBe(true)
    expect(isFiltering({ ...NO_FILTERS, ai: 'no' })).toBe(true)
    expect(isFiltering({ ...NO_FILTERS, documents: 'missing' })).toBe(true)
    expect(isFiltering({ ...NO_FILTERS, fa: 'completed' })).toBe(true)
    expect(isFiltering({ ...NO_FILTERS, commitment: 'yes' })).toBe(true)
  })
})

describe('statusCounts', () => {
  it('puts every packet in exactly one bucket, so the buckets sum to the total', () => {
    // This is what makes the counters safe to use as filters. The design mock's
    // "Thiếu / cần review" counter excluded every Thiếu case because missing
    // documents were folded into another bucket.
    const statuses: Array<SummaryStatus | null> =
      ['no', 'no', 'missing', 'rv', 'ok', 'pending', null]
    const rows = packetRows(statuses.map((s, i) => P({ index: i, aiStatus: s })))
    const { total, byStatus, unrated } = statusCounts(rows)
    expect(total).toBe(7)
    expect(byStatus).toEqual({ no: 2, missing: 1, rv: 1, ok: 1, pending: 1, na: 0 })
    expect(unrated).toBe(1)
    const summed = Object.values(byStatus).reduce((a, b) => a + b, 0) + unrated
    expect(summed).toBe(total)
  })

  it('counts nothing for an empty list', () => {
    expect(statusCounts([]).total).toBe(0)
  })
})

describe('visibleCounters', () => {
  it('orders worst first so the work leads', () => {
    expect(COUNTER_ORDER).toEqual(['no', 'missing', 'rv', 'pending', 'ok', 'na'])
    const rows = packetRows([
      P({ index: 0, aiStatus: 'ok' }), P({ index: 1, aiStatus: 'no' }),
      P({ index: 2, aiStatus: 'rv' }), P({ index: 3, aiStatus: 'missing' }),
    ])
    expect(visibleCounters(rows).map(c => c.status)).toEqual(['no', 'missing', 'rv', 'ok'])
  })

  it('omits statuses no packet has — a row of zeroes is noise', () => {
    const rows = packetRows([P({ index: 0, aiStatus: 'ok' })])
    expect(visibleCounters(rows)).toHaveLength(1)
    expect(visibleCounters(rows)[0]).toMatchObject({ status: 'ok', count: 1, tone: 'good' })
  })

  it('carries the same labels the matrix uses', () => {
    const rows = packetRows([P({ index: 0, aiStatus: 'missing' })])
    expect(visibleCounters(rows)[0].label).toBe('Thiếu chứng từ')
  })
})
