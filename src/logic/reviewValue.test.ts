import { describe, expect, it } from 'vitest'
import type { CtvField } from '../ctv/types'
import { formatRosterValue } from './reviewValue'

const field = (
  expected: string,
  overrides: Partial<Pick<CtvField, 'group' | 'kind'>> = {},
): Pick<CtvField, 'group' | 'kind' | 'expected'> => ({
  group: 'Thanh toán',
  kind: 'number',
  expected,
  ...overrides,
})

describe('formatRosterValue', () => {
  it('formats raw and already-grouped financial integers as Vietnamese đồng', () => {
    expect(formatRosterValue(field('6111111'))).toBe('6.111.111 ₫')
    expect(formatRosterValue(field('6.111.111 ₫'))).toBe('6.111.111 ₫')
    expect(formatRosterValue(field('6,111,111 VND'))).toBe('6.111.111 ₫')
    expect(formatRosterValue(field('0'))).toBe('0 ₫')
  })

  it('leaves non-financial and unparseable values unchanged', () => {
    expect(formatRosterValue(field('2865', { group: 'Chứng từ' }))).toBe('2865')
    expect(formatRosterValue(field('không rõ'))).toBe('không rõ')
  })
})
