import { describe, it, expect } from 'vitest'
import { clampZoom, VIEW_MODES, viewModeForCheck } from './viewMode'
import type { CheckItem } from '../ctv/types'

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

const mk = (over: Partial<CheckItem>): CheckItem => ({
  code: 'X', label: 'x', tier: 'detail', kind: 'value',
  evidenceDocId: 'd', reference: null, source: null, autostatus: null, ...over,
})

describe('viewModeForCheck', () => {
  it('value checks -> 1 trang', () => {
    expect(viewModeForCheck(mk({ kind: 'value' }))).toBe('1')
  })
  it('signature gates (B3, C2) -> 1 trang', () => {
    expect(viewModeForCheck(mk({ code: 'B3', kind: 'confirm', focus: { page: 1, bbox: { x:0,y:0,width:1,height:1 }, caption: 'c' } }))).toBe('1')
    expect(viewModeForCheck(mk({ code: 'C2', kind: 'confirm' }))).toBe('1')
  })
  it('skim checks (G-DOC, D3, D1) -> continuous', () => {
    expect(viewModeForCheck(mk({ code: 'G-DOC', kind: 'confirm' }))).toBe('cont')
    expect(viewModeForCheck(mk({ code: 'D3', kind: 'confirm' }))).toBe('cont')
    expect(viewModeForCheck(mk({ code: 'D1', kind: 'confirm' }))).toBe('cont')
  })
})
