import { describe, expect, test } from 'vitest'
import {
  normalizeRejectionDraft,
  rejectedReview,
  undoRejectedReview,
} from './packetRejection'
import type { PacketReview } from '../upload/api'

const baseReview = (): PacketReview => ({
  done: false,
  fields: {
    name: { seen: true, flag: null },
    cccd: {
      seen: false,
      flag: { reason: 'sai', note: 'Giữ nguyên' },
    },
  },
  rejection: null,
})

describe('packet rejection draft', () => {
  test('canonicalizes multiple reasons and trims the optional note', () => {
    expect(normalizeRejectionDraft(
      ['missing_signature', 'missing_documents'],
      '  Bổ sung bộ hồ sơ  ',
    )).toEqual({
      reasons: ['missing_documents', 'missing_signature'],
      note: 'Bổ sung bộ hồ sơ',
    })
  })

  test('requires at least one reason', () => {
    expect(() => normalizeRejectionDraft([], ''))
      .toThrow('Chọn ít nhất một lý do')
  })

  test('deduplicates reasons instead of persisting duplicate issues', () => {
    expect(normalizeRejectionDraft(
      ['missing_documents', 'missing_documents'],
      '',
    ).reasons).toEqual(['missing_documents'])
  })
})

describe('packet rejection review builders', () => {
  test('rejecting forces done and preserves every field review', () => {
    const current = baseReview()
    const next = rejectedReview(current, {
      reasons: ['missing_documents'],
      note: '',
    })
    expect(next.done).toBe(true)
    expect(next.rejection).toEqual({
      reasons: ['missing_documents'],
      note: '',
    })
    expect(next.fields).toEqual(current.fields)
  })

  test('editing replaces the rejection without duplicating it', () => {
    const current = rejectedReview(baseReview(), {
      reasons: ['missing_documents'],
      note: 'old',
    })
    expect(rejectedReview(current, {
      reasons: ['missing_signature'],
      note: 'new',
    }).rejection).toEqual({
      reasons: ['missing_signature'],
      note: 'new',
    })
  })

  test('undo preserves fields and derives incomplete done from all-seen', () => {
    const current = rejectedReview(baseReview(), {
      reasons: ['missing_documents'],
      note: '',
    })
    const next = undoRejectedReview(current, ['name', 'cccd'])
    expect(next).toEqual({
      done: false,
      fields: current.fields,
      rejection: null,
    })
  })

  test('undo remains normally complete when all detailed fields are seen', () => {
    const current = rejectedReview({
      ...baseReview(),
      fields: {
        name: { seen: true, flag: null },
        cccd: { seen: true, flag: null },
      },
    }, {
      reasons: ['missing_signature'],
      note: '',
    })
    expect(undoRejectedReview(current, ['name', 'cccd']).done).toBe(true)
  })
})
