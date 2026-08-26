import { describe, it, expect } from 'vitest'
import { evalField, rankFolder, counts } from './checks'
import type { CtvField, CtvFolder, CtvSource } from './types'

const BBOX = { x: 0, y: 0, width: 10, height: 10 }

const src = (docId: string, value: string, confidence = 0.95): CtvSource =>
  ({ docId, page: 0, value, bbox: BBOX, confidence })

const folderWith = (fields: CtvField[]): CtvFolder => ({
  id: 'f1', name: 'X', product: 'P', status: 'pending', exempt: false,
  docs: [{ id: 'a', kind: 'contract', label: 'A', pages: [{ src: '', width: 100, height: 100 }] }],
  fields,
})

const field = (over: Partial<CtvField>): CtvField => ({
  key: 'k', label: 'L', group: 'Danh tính', check: 'compare', kind: 'text',
  expected: '123', sources: [], ...over,
})

describe('evalField compare — unread sources never gate the verdict', () => {
  it('a readable match + an unread ("cần xem") source -> overall match, unread source still present', () => {
    const f = field({ sources: [src('bbnt', '123'), src('contract', '')] })
    const r = evalField(f, folderWith([f]))
    expect(r.verdict).toBe('match')
    expect(r.sources).toHaveLength(2)
    expect(r.sources.find(s => s.source.docId === 'bbnt')!.verdict).toBe('match')
    expect(r.sources.find(s => s.source.docId === 'contract')!.verdict).toBe('unread')
  })

  it('only unread sources -> field verdict is "review", not mismatch', () => {
    const f = field({ sources: [src('contract', ''), src('bbnt', '')] })
    const r = evalField(f, folderWith([f]))
    expect(r.verdict).toBe('review')
    expect(r.sources.every(s => s.verdict === 'unread')).toBe(true)
  })

  it('a single fallback empty source (label absent everywhere) -> "review"', () => {
    const f = field({ sources: [src('', '')] })
    const r = evalField(f, folderWith([f]))
    expect(r.verdict).toBe('review')
  })

  it('a readable mismatch + an unread source -> still mismatch (unread does not rescue it)', () => {
    const f = field({ sources: [src('bbnt', '999'), src('contract', '')] })
    const r = evalField(f, folderWith([f]))
    expect(r.verdict).toBe('mismatch')
  })

  it('actual prefers the first readable value over an unread one', () => {
    const f = field({ sources: [src('contract', ''), src('bbnt', '123')] })
    const r = evalField(f, folderWith([f]))
    expect(r.actual).toBe('123')
  })
})

describe('rankFolder ordering — mismatch and review surface before matches', () => {
  it('orders mismatch -> fuzzy -> review -> low_conf -> match', () => {
    const mismatch = field({ key: 'mismatch', sources: [src('a', '999')] })
    const review = field({ key: 'review', sources: [src('a', '')] })
    const lowConf = field({ key: 'low_conf', sources: [src('a', '123', 0.5)] })
    const fuzzy = field({ key: 'fuzzy', kind: 'name', expected: 'Grab', sources: [src('a', 'CÔNG TY TNHH GRAB')] })
    const match = field({ key: 'match', sources: [src('a', '123')] })
    const folder = folderWith([match, fuzzy, lowConf, review, mismatch])
    const ranked = rankFolder(folder)
    expect(ranked.map(r => r.field.key)).toEqual(['mismatch', 'fuzzy', 'review', 'low_conf', 'match'])
    expect(ranked.map(r => r.verdict)).toEqual(['mismatch', 'fuzzy', 'review', 'low_conf', 'match'])
  })
})

describe('counts', () => {
  it('tallies a "review" bucket alongside mismatch/low_conf', () => {
    const review = field({ key: 'review', sources: [src('a', '')] })
    const mismatch = field({ key: 'mismatch', sources: [src('a', '999')] })
    const ranked = rankFolder(folderWith([review, mismatch]))
    const c = counts(ranked)
    expect(c.mismatch).toBe(1)
    expect(c.review).toBe(1)
  })
})
