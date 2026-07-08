import { describe, it, expect } from 'vitest'
import { compareField, orderFields } from './verdict'
import type { CaseField, Prediction } from '../types'

const pred = (value: string, confidence = 0.98): Prediction => ({
  value, confidence, page: 0, bbox: { x: 0, y: 0, width: 10, height: 10 },
})

describe('compareField', () => {
  it('numbers: exact numeric equality is a match despite formatting', () => {
    expect(compareField('2.050.000 ₫', pred('2050000'), 'number')).toBe('match')
  })
  it('numbers: different amounts mismatch', () => {
    expect(compareField('2.500.000 ₫', pred('2.050.000'), 'number')).toBe('mismatch')
  })
  it('dates: same day in different formats matches', () => {
    expect(compareField('05/07/2026', pred('2026-07-05'), 'date')).toBe('match')
  })
  it('dates: different day mismatches', () => {
    expect(compareField('05/07/2026', pred('06/07/2026'), 'date')).toBe('mismatch')
  })
  it('text: trimmed exact equality matches, else mismatch', () => {
    expect(compareField('AA/26E-0451', pred(' AA/26E-0451 '), 'text')).toBe('match')
    expect(compareField('AA/26E-0451', pred('AA/26E-0999'), 'text')).toBe('mismatch')
  })
  it('names: identical -> match; normalized-close -> fuzzy; different -> mismatch', () => {
    expect(compareField('Grab', pred('Grab'), 'name')).toBe('match')
    expect(compareField('Grab', pred('CÔNG TY TNHH GRAB'), 'name')).toBe('fuzzy')
    expect(compareField('Grab', pred('Highlands Coffee'), 'name')).toBe('mismatch')
  })
  it('low confidence overlays a match', () => {
    expect(compareField('2050000', pred('2050000', 0.5), 'number')).toBe('low_conf')
  })
  it('mismatch beats low confidence (more severe wins)', () => {
    expect(compareField('2500000', pred('2050000', 0.5), 'number')).toBe('mismatch')
  })
  it('null prediction is a mismatch', () => {
    expect(compareField('2050000', null, 'number')).toBe('mismatch')
  })
})

describe('orderFields', () => {
  const f = (key: string, kind: CaseField['kind'], expected: string, p: Prediction | null): CaseField =>
    ({ key, label: key, kind, expected, prediction: p })

  it('orders mismatch -> low_conf -> fuzzy -> match, keeping original index', () => {
    const fields: CaseField[] = [
      f('ok', 'number', '100', pred('100')),
      f('vendor', 'name', 'Grab', pred('CÔNG TY TNHH GRAB')),
      f('inv', 'text', 'X', pred('X', 0.5)),
      f('total', 'number', '2500000', pred('2050000')),
    ]
    const ranked = orderFields(fields)
    expect(ranked.map(r => r.field.key)).toEqual(['total', 'inv', 'vendor', 'ok'])
    expect(ranked.map(r => r.verdict)).toEqual(['mismatch', 'low_conf', 'fuzzy', 'match'])
    expect(ranked.find(r => r.field.key === 'total')!.index).toBe(3)
  })

  it('breaks ties by page then bbox.y among same-severity fields', () => {
    const at = (key: string, page: number, y: number): CaseField => ({
      key, label: key, kind: 'number', expected: '100',
      prediction: { value: '200', confidence: 0.98, page, bbox: { x: 0, y, width: 10, height: 10 } },
    })
    // all mismatch (100 vs 200) -> same severity; expect page asc, then y asc
    const ranked = orderFields([at('b', 1, 50), at('a', 0, 900), at('c', 1, 20)])
    expect(ranked.map(r => r.field.key)).toEqual(['a', 'c', 'b'])
  })

  it('empty-vs-empty number is a mismatch, not a false match', () => {
    const f: CaseField = { key: 'x', label: 'x', kind: 'number', expected: '',
      prediction: { value: '', confidence: 0.98, page: 0, bbox: { x: 0, y: 0, width: 1, height: 1 } } }
    expect(orderFields([f])[0].verdict).toBe('mismatch')
  })
})
