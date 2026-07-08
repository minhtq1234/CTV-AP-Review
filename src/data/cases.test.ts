import { describe, it, expect } from 'vitest'
import { seedCases } from './cases'
import { orderFields } from '../logic/verdict'

const verdictsFor = (id: string) => {
  const c = seedCases.find(x => x.id === id)!
  return orderFields(c.fields).map(r => r.verdict)
}

describe('seed cases', () => {
  it('has three cases, all pending', () => {
    expect(seedCases.map(c => c.id)).toEqual(['PR-2026-0138', 'PR-2026-0142', 'PR-2026-0151'])
    expect(seedCases.every(c => c.status === 'pending')).toBe(true)
  })
  it('case 1 is clean: no mismatch, no low_conf (matches + one fuzzy vendor)', () => {
    const v = verdictsFor('PR-2026-0138')
    expect(v).not.toContain('mismatch')
    expect(v).not.toContain('low_conf')
    expect(v).toContain('fuzzy')
  })
  it('case 2 has exactly one mismatch (total) and one low_conf (invoice no.)', () => {
    const v = verdictsFor('PR-2026-0142')
    expect(v.filter(x => x === 'mismatch')).toHaveLength(1)
    expect(v.filter(x => x === 'low_conf')).toHaveLength(1)
  })
  it('case 3 has a low_conf but no mismatch (amount matches, AI unsure)', () => {
    const v = verdictsFor('PR-2026-0151')
    expect(v).toContain('low_conf')
    expect(v).not.toContain('mismatch')
  })
  it('every prediction bbox falls inside its page bounds', () => {
    for (const c of seedCases)
      for (const f of c.fields)
        if (f.prediction) {
          const pg = c.pages[f.prediction.page]
          const b = f.prediction.bbox
          expect(b.x + b.width).toBeLessThanOrEqual(pg.width)
          expect(b.y + b.height).toBeLessThanOrEqual(pg.height)
        }
  })
})
