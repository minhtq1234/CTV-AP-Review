import { readFileSync } from 'node:fs'
import { describe, it, expect } from 'vitest'
import { evalField, rankFolder, counts } from './checks'
import { CHECK_GROUPS, CHECK_TYPES } from './types'
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

// ---------------------------------------------------------------------------
// The semantic reader's fields (server/ocr_extract.py `_semantic_fields`).
// `evalField`'s switch had four cases and no default, so a `check: "semantic"`
// field returned undefined -- and rankFolder reads `.verdict` off it while
// buildPacketGrid reads `.sources`, so the packet review screen rendered blank
// the moment the reader was wired in.
// ---------------------------------------------------------------------------
describe('evalField semantic — read and quoted, nothing compared yet', () => {
  // Exactly the shape the server emits: no expected value to compare against,
  // one located source and one whose quote could not be found on the page
  // (confidence 0.0, no bbox).
  const semantic = () => field({
    key: 'payment_terms',
    label: 'payment_terms',
    group: 'Điều khoản',
    check: 'semantic',
    kind: 'text',
    expected: '',
    sources: [
      { docId: 'contract', page: 1, value: '30 ngày', bbox: BBOX, confidence: 1 },
      { docId: 'bbnt', page: 0, value: '30 ngày', bbox: null, confidence: 0 },
    ],
  })

  it('reads as "cần xem" with every source kept, including the unlocatable one', () => {
    const f = semantic()
    const r = evalField(f, folderWith([f]))
    expect(r.verdict).toBe('review')
    expect(r.actual).toBe('30 ngày')
    expect(r.sources).toHaveLength(2)
    expect(r.sources.every(s => s.verdict === 'unchecked')).toBe(true)
    // The unlocatable read stays visible rather than being dropped: it is the
    // reviewer's only pointer at a quote the tool could not place.
    expect(r.sources.find(s => s.source.docId === 'bbnt')!.source.bbox).toBeNull()
  })

  it('never claims a pass or a mismatch it did not compute', () => {
    const f = semantic()
    const r = evalField(f, folderWith([f]))
    expect(r.verdict).not.toBe('match')
    expect(r.verdict).not.toBe('mismatch')
  })

  it('lets rankFolder and counts run over it instead of reading off undefined', () => {
    const f = semantic()
    const mismatch = field({ key: 'mismatch', sources: [src('a', '999')] })
    const ranked = rankFolder(folderWith([f, mismatch]))
    expect(ranked.map(r => r.field.key)).toEqual(['mismatch', 'payment_terms'])
    expect(counts(ranked).review).toBe(1)
  })

  it('refuses rather than throws or returns undefined for an unknown check', () => {
    // A server ahead of this bundle. Throwing here would take the whole packet
    // review screen down (evalField runs on the render path), turning one
    // unrenderable row into zero visible rows.
    const f = { ...semantic(), check: 'clause-graph' as unknown as CtvField['check'] }
    const r = evalField(f, folderWith([f]))
    expect(r).toBeDefined()
    expect(r.verdict).toBe('review')
    expect(r.sources).toHaveLength(2)
    expect(r.sources.every(s => s.verdict === 'unchecked')).toBe(true)
  })
})

// The two vocabularies the manifest is built from. `build_manifest`'s docstring
// claims it "matches src/ctv/types.ts exactly"; nothing checked, and it did not.
describe('the check/group vocabularies match the server that emits them', () => {
  // The WHOLE file, not the slice from `def _semantic_fields`. That slice was
  // justified by "`_semantic_fields` is the only emitter of a whole field dict
  // on the TS side of the wire", which is false: `_build_fields` emits one too
  // (`"check": "compare"` plus `"group": spec["group"]` off the spec table),
  // and every line of it sits ABOVE the slice point. So the pin covered 2 of
  // the 9 literals that reach the wire and missed 6 of the 7 CHECK_GROUPS --
  // including the drift class F12 itself came from. Every `"group"` / `"check"`
  // literal in this file is a manifest literal; there is nothing to exclude.
  const source = readFileSync('server/ocr_extract.py', 'utf8')

  it('emits a `check` this bundle has a case for', () => {
    const emitted = [...source.matchAll(/"check":\s*"([^"]+)"/g)].map(m => m[1])
    expect(emitted.length).toBeGreaterThan(0)
    for (const check of emitted) expect(CHECK_TYPES).toContain(check)
  })

  it('emits a `group` this bundle knows', () => {
    const emitted = [...source.matchAll(/"group":\s*"([^"]+)"/g)].map(m => m[1])
    // Both emitters. The slice this replaced saw one `"group"` literal; the
    // spec table alone has six, so a floor above 1 is what keeps the scan
    // from silently narrowing back to `_semantic_fields`.
    expect(emitted.length).toBeGreaterThan(1)
    for (const group of emitted) expect(CHECK_GROUPS).toContain(group)
  })
})
