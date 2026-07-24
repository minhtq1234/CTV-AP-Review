import { describe, it, expect } from 'vitest'
import { clampPage } from './pageNav'

describe('clampPage', () => {
  it('clamps a stale high index down to the last page', () => {
    expect(clampPage(3, 2)).toBe(1)   // page 4 of a 2-page doc -> last (index 1)
  })
  it('clamps negatives up to 0', () => {
    expect(clampPage(-2, 5)).toBe(0)
  })
  it('passes an in-range index through', () => {
    expect(clampPage(2, 5)).toBe(2)
  })
  it('returns 0 for an empty/zero-page doc', () => {
    expect(clampPage(4, 0)).toBe(0)
  })
})
