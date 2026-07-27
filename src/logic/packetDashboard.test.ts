import { describe, expect, it } from 'vitest'
import type { PacketMeta, PacketReview } from '../upload/api'
import {
  attentionReasons,
  filterPackets,
  packetDashboardCounts,
  packetDashboardStatus,
  packetFlagCount,
  packetSeenCount,
  prioritizeAttention,
} from './packetDashboard'

function review(overrides: Partial<PacketReview> = {}): PacketReview {
  return {
    done: false,
    fields: {},
    rejection: null,
    ...overrides,
  }
}

function packet(
  index: number,
  packetReview: PacketReview = review(),
  overrides: Partial<PacketMeta> = {},
): PacketMeta {
  return {
    index,
    name: `Synthetic ${index}`,
    pages: [index, index],
    n_pages: 1,
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: 'synthetic', name: `Synthetic ${index}` },
    rosterIdentity: { cccd: 'synthetic', name: `Synthetic ${index}` },
    review: packetReview,
    reviewFieldCount: 6,
    ...overrides,
  }
}

describe('packet dashboard lifecycle', () => {
  it('derives exactly the four reviewer lifecycle states', () => {
    expect(packetDashboardStatus(packet(0))).toBe('unseen')
    expect(packetDashboardStatus(packet(1, review({
      fields: { a: { seen: true, flag: null } },
    })))).toBe('reviewing')
    expect(packetDashboardStatus(packet(2, review({ done: true })))).toBe('completed')
    expect(packetDashboardStatus(packet(3, review({
      fields: {
        a: {
          seen: false,
          flag: { reason: 'synthetic reason', note: '' },
        },
      },
    })))).toBe('flagged')
  })

  it('gives field flags and rejection precedence over reviewing and completed', () => {
    expect(packetDashboardStatus(packet(0, review({
      fields: {
        a: {
          seen: true,
          flag: { reason: 'synthetic reason', note: '' },
        },
      },
    })))).toBe('flagged')
    expect(packetDashboardStatus(packet(1, review({
      done: true,
      fields: {
        a: {
          seen: true,
          flag: { reason: 'synthetic reason', note: '' },
        },
      },
    })))).toBe('flagged')
    expect(packetDashboardStatus(packet(2, review({
      done: true,
      rejection: { reasons: ['missing_documents'], note: '' },
    })))).toBe('flagged')
  })

  it('counts seen and flagged fields independently', () => {
    const subject = packet(0, review({
      fields: {
        a: { seen: true, flag: null },
        b: { seen: true, flag: { reason: 'synthetic', note: '' } },
        c: { seen: false, flag: { reason: 'synthetic', note: '' } },
      },
    }))
    expect(packetSeenCount(subject)).toBe(2)
    expect(packetFlagCount(subject)).toBe(2)
  })
})

describe('system attention', () => {
  it('maps and deduplicates known and unknown signals in stable order', () => {
    const subject = packet(0, review({ done: true }), {
      matchedBy: 'unmatched',
      flags: [
        'roster-unmatched',
        'auto-merged',
        'near-threshold',
        'length-out-of-range',
        'future-warning',
        'another-future-warning',
      ],
    })
    expect(attentionReasons(subject)).toEqual([
      'Không khớp bảng kê',
      'Cần xác nhận ranh giới',
      'Ranh giới gần ngưỡng',
      'Số trang bất thường',
      'Cần kiểm tra xử lý',
    ])
  })

  it('does not change lifecycle for name-only or pipeline attention', () => {
    expect(packetDashboardStatus(packet(0, review({ done: true }), {
      matchedBy: 'name',
    }))).toBe('completed')
    expect(packetDashboardStatus(packet(1, review(), {
      flags: ['auto-merged'],
    }))).toBe('unseen')
    expect(attentionReasons(packet(2, review(), {
      matchedBy: 'name',
    }))).toEqual(['Chỉ khớp theo tên'])
  })
})

describe('dashboard counts, filters, and ordering', () => {
  const packets = [
    packet(0),
    packet(1, review({ fields: { a: { seen: true, flag: null } } })),
    packet(2, review({ done: true })),
    packet(3, review({
      rejection: { reasons: ['missing_signature'], note: '' },
    })),
  ]

  it('counts every packet in exactly one lifecycle bucket', () => {
    const counts = packetDashboardCounts(packets)
    expect(counts).toEqual({
      unseen: 1,
      reviewing: 1,
      completed: 1,
      flagged: 1,
    })
    expect(Object.values(counts).reduce((sum, count) => sum + count, 0)).toBe(4)
  })

  it('filters locally by lifecycle and preserves all for all', () => {
    expect(filterPackets(packets, 'reviewing').map(p => p.index)).toEqual([1])
    expect(filterPackets(packets, 'flagged').map(p => p.index)).toEqual([3])
    expect(filterPackets(packets, 'all').map(p => p.index)).toEqual([0, 1, 2, 3])
  })

  it('stably partitions attention without mutating base order', () => {
    const base = [
      packet(0),
      packet(1, review(), { matchedBy: 'name' }),
      packet(2),
      packet(3, review(), { flags: ['auto-merged'] }),
    ]
    expect(prioritizeAttention(base).map(p => p.index)).toEqual([1, 3, 0, 2])
    expect(base.map(p => p.index)).toEqual([0, 1, 2, 3])
    expect(filterPackets(base, 'all').map(p => p.index)).toEqual([0, 1, 2, 3])
  })
})
