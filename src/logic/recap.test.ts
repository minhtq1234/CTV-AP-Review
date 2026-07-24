import { describe, it, expect } from 'vitest'
import { isContentBearing, CONTENT_BEARING_KINDS, RECAP_DISCLAIMER } from './recap'

describe('isContentBearing', () => {
  it('is true for docs whose typed body carries reviewable content', () => {
    for (const k of ['contract', 'bbnt', 'appendix', 'commitment'] as const) {
      expect(isContentBearing(k)).toBe(true)
    }
  })
  it('is false for id scans and the PIT lookup (nothing to read fast)', () => {
    for (const k of ['id_front', 'id_back', 'pit'] as const) {
      expect(isContentBearing(k)).toBe(false)
    }
  })
  it('CONTENT_BEARING_KINDS is exactly the four content docs', () => {
    expect([...CONTENT_BEARING_KINDS].sort()).toEqual(['appendix', 'bbnt', 'commitment', 'contract'])
  })
})

describe('RECAP_DISCLAIMER', () => {
  it('frames the recap as assist, never verdict', () => {
    expect(RECAP_DISCLAIMER).toContain('Bản xem thử')
    expect(RECAP_DISCLAIMER).toContain('quyết định cuối cùng do bạn')
  })
})
