import { describe, it, expect } from 'vitest'
import { clampPage, stepPage, stepDoc } from './pageNav'

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

const DOCS = [
  { id: 'a', pages: [{}, {}] },        // 2 pages
  { id: 'b', pages: [{}] },            // 1 page
  { id: 'c', pages: [{}, {}, {}] },    // 3 pages
] as unknown as import('../ctv/types').EvidenceDoc[]

describe('stepPage', () => {
  it('advances within a doc', () => {
    expect(stepPage(DOCS, 'a', 0, +1)).toEqual({ docId: 'a', page: 1 })
  })
  it('rolls forward into the next doc at the first page of it', () => {
    expect(stepPage(DOCS, 'a', 1, +1)).toEqual({ docId: 'b', page: 0 })
  })
  it('rolls backward into the previous doc at its last page', () => {
    expect(stepPage(DOCS, 'b', 0, -1)).toEqual({ docId: 'a', page: 1 })
  })
  it('stays put at the very first page going back', () => {
    expect(stepPage(DOCS, 'a', 0, -1)).toEqual({ docId: 'a', page: 0 })
  })
  it('stays put at the very last page going forward', () => {
    expect(stepPage(DOCS, 'c', 2, +1)).toEqual({ docId: 'c', page: 2 })
  })
})

describe('stepDoc', () => {
  it('moves to the next document', () => { expect(stepDoc(DOCS, 'a', +1)).toBe('b') })
  it('moves to the previous document', () => { expect(stepDoc(DOCS, 'b', -1)).toBe('a') })
  it('clamps at the ends', () => {
    expect(stepDoc(DOCS, 'a', -1)).toBe('a')
    expect(stepDoc(DOCS, 'c', +1)).toBe('c')
  })
})
