import { describe, it, expect } from 'vitest'
import { clampZoom, VIEW_MODES } from './viewMode'

describe('viewMode', () => {
  it('exposes the three modes in toolbar order', () => {
    expect(VIEW_MODES.map(m => m.mode)).toEqual(['1', 'cont', '2'])
  })
  it('clamps continuous zoom into [0.5, 4]', () => {
    expect(clampZoom(0.1)).toBe(0.5)
    expect(clampZoom(9)).toBe(4)
    expect(clampZoom(1.5)).toBe(1.5)
  })
})
