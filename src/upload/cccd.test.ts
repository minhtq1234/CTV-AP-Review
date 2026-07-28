import { describe, expect, it } from 'vitest'
import {
  canStartUpload,
  cccdRequirementMessage,
  formatCccdSummary,
} from './cccd'

describe('CCCD upload eligibility', () => {
  it('blocks CCCD without a roster', () => {
    expect(canStartUpload(true, false, true, false)).toBe(false)
    expect(cccdRequirementMessage(false, true))
      .toBe('Cần bảng kê để tự động ghép CCCD.')
  })

  it('allows CCCD with roster and restores roster-optional flow after removal', () => {
    expect(canStartUpload(true, true, true, false)).toBe(true)
    expect(cccdRequirementMessage(true, true)).toBeNull()
    expect(canStartUpload(true, false, false, false)).toBe(true)
    expect(cccdRequirementMessage(false, false)).toBeNull()
  })

  it('still requires a PDF and respects busy state', () => {
    expect(canStartUpload(false, true, true, false)).toBe(false)
    expect(canStartUpload(true, true, true, true)).toBe(false)
  })
})

describe('CCCD result summary', () => {
  it('formats ready and partial summaries as aggregate counts', () => {
    expect(formatCccdSummary({
      status: 'ready',
      candidates: 3,
      attached: 2,
      unresolved: 1,
    })).toBe('CCCD: 2 đã gắn · 1 chưa ghép')
    expect(formatCccdSummary({
      status: 'partial',
      candidates: 3,
      attached: 1,
      unresolved: 2,
      errorCode: 'extraction-incomplete',
    })).toBe('CCCD: 1 đã gắn · 2 chưa ghép')
  })

  it('uses generic copy for an ingest error', () => {
    expect(formatCccdSummary({
      status: 'error',
      candidates: 0,
      attached: 0,
      unresolved: 0,
      errorCode: 'invalid-workbook',
    })).toBe('CCCD: Không xử lý được file ảnh')
  })

  it('does not interpolate an error code', () => {
    expect(formatCccdSummary({
      status: 'error',
      candidates: 0,
      attached: 0,
      unresolved: 0,
      errorCode: 'private-error-detail',
    })).not.toContain('private-error-detail')
  })
})
