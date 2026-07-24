import { describe, it, expect } from 'vitest'
import { clampZoom, VIEW_MODES, viewModeForCheck } from './viewMode'
import type { CheckItem } from '../ctv/types'

const mk = (over: Partial<CheckItem>): CheckItem => ({
  code: 'X', label: 'x', tier: 'detail', kind: 'value',
  evidenceDocId: 'd', reference: null, source: null, autostatus: null, ...over,
})

describe('viewMode', () => {
  it('toolbar exposes only the two manual modes, in order', () => {
    expect(VIEW_MODES.map(m => m.mode)).toEqual(['cont', '2'])
  })
  it('clamps continuous zoom into [0.5, 4]', () => {
    expect(clampZoom(0.1)).toBe(0.5)
    expect(clampZoom(9)).toBe(4)
    expect(clampZoom(1.5)).toBe(1.5)
  })
})

describe('viewModeForCheck', () => {
  it('value checks auto-focus a single page', () => {
    expect(viewModeForCheck(mk({ kind: 'value' }))).toBe('1')
  })
  it('signature gates (B3/C2) open the doc in continuous scroll — no auto-focus', () => {
    expect(viewModeForCheck(mk({ code: 'B3', kind: 'confirm' }))).toBe('cont')
    expect(viewModeForCheck(mk({ code: 'C2', kind: 'confirm' }))).toBe('cont')
  })
  it('glance / confirm checks (G-DOC, C1, D1, D3) open the doc in continuous scroll', () => {
    expect(viewModeForCheck(mk({ code: 'G-DOC', kind: 'confirm' }))).toBe('cont')
    expect(viewModeForCheck(mk({ code: 'D1', kind: 'confirm' }))).toBe('cont')
  })
})
