import { describe, expect, it } from 'vitest'
import {
  canStartUpload,
  cccdRequirementMessage,
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
