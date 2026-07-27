import type { Verdict } from '../types'
import { compareField } from '../logic/verdict'
import type { CtvField, CtvFolder, CtvSource } from './types'

// Fixed "today" for the demo so the expiry check is deterministic.
export const REVIEW_DATE = new Date(2026, 6, 13) // 2026-07-13

const digits = (s: string) => s.replace(/[^\d]/g, '')

function parseVnDate(s: string): Date | null {
  const m = s.match(/(\d{1,2})[/-](\d{1,2})[/-](\d{4})/)
  if (!m) return null
  return new Date(+m[3], +m[2] - 1, +m[1])
}

const vnd = (n: number) => `${n.toLocaleString('vi-VN')} ₫`

const SEVERITY: Record<Verdict, number> = { mismatch: 0, low_conf: 1, fuzzy: 2, match: 3 }
const worst = (vs: Verdict[]): Verdict =>
  vs.length === 0 ? 'mismatch' : vs.reduce((a, b) => (SEVERITY[b] < SEVERITY[a] ? b : a))

// A source with no value: the label was located (e.g. "Ngày sinh" on the contract) but its
// value couldn't be read (handwritten/illegible) -- navigable ("cần xem"), never a mismatch.
export type SourceVerdict = Verdict | 'unread'
// A field with no readable source at all -- every occurrence is "cần xem" -- reads as a neutral
// "needs eyes" exception, not a hard mismatch (#004: unread copies must not turn a field red).
export type FieldVerdict = Verdict | 'review'

// mismatch/review both need a human's attention and surface first; low_conf/fuzzy/match follow
// in the original severity order. Used only for field-level ranking (rankFolder) -- `worst`
// above still resolves a single field's READABLE sources using the plain 4-value Verdict.
const FIELD_SEVERITY: Record<FieldVerdict, number> = { mismatch: 0, review: 1, low_conf: 2, fuzzy: 3, match: 4 }

// How each source of a field stacks up against the Excel value.
export interface SourceResult { source: CtvSource; verdict: SourceVerdict }
export interface CheckResult { verdict: FieldVerdict; actual: string; sources: SourceResult[] }

function compareOne(expected: string, s: CtvSource, kind: CtvField['kind']): SourceVerdict {
  if (!s.value) return 'unread'
  return compareField(expected, { value: s.value, confidence: s.confidence, page: 0, bbox: s.bbox }, kind)
}

// A field's overall verdict + how each source compares. Compare-fields derive their verdict from
// the sources; expiry/math/policy are computed, and their sources are only there for focus.
export function evalField(f: CtvField, folder: CtvFolder): CheckResult {
  switch (f.check) {
    case 'compare': {
      const results = f.sources.map(s => ({ source: s, verdict: compareOne(f.expected, s, f.kind) }))
      const readable = results
        .map(r => r.verdict)
        .filter((v): v is Verdict => v !== 'unread')
      // The reviewer's eyes are the decision; an unread copy is a location to check, not a
      // vote -- the field verdict is the worst of the READABLE sources only. No readable
      // source at all -> "review" ("cần xem"), never a mismatch by default.
      const verdict: FieldVerdict = readable.length > 0 ? worst(readable) : 'review'
      const actual = f.sources.find(s => s.value)?.value ?? '—'
      return { verdict, actual, sources: results }
    }
    case 'expiry': {
      const s = f.sources[0]
      const d = s ? parseVnDate(s.value) : null
      const expired = !d || d < REVIEW_DATE
      const verdict: Verdict = expired ? 'mismatch' : 'match'
      return {
        verdict,
        actual: s ? (expired ? `Hết hạn ${s.value}` : `Hiệu lực đến ${s.value}`) : '—',
        sources: f.sources.map(src => ({ source: src, verdict })),
      }
    }
    case 'math': {
      const num = (k: string) => {
        const fld = folder.fields.find(x => x.key === k)
        return fld ? parseInt(digits(fld.expected) || '0', 10) : 0
      }
      const claimed = parseInt(digits(f.expected) || '0', 10)
      let expected: number
      if (f.key === 'pit') expected = folder.exempt ? 0 : Math.round(num('gross') * 0.1)
      else expected = num('gross') - num('pit') // net
      const verdict: Verdict = claimed === expected ? 'match' : 'mismatch'
      return { verdict, actual: vnd(expected), sources: f.sources.map(src => ({ source: src, verdict })) }
    }
    case 'policy': {
      let verdict: Verdict
      let actual: string
      if (!folder.exempt) { verdict = 'match'; actual = 'Khấu trừ 10% (không miễn)' }
      else {
        const hasCommit = folder.docs.some(d => d.kind === 'commitment')
        verdict = hasCommit ? 'match' : 'mismatch'
        actual = hasCommit ? 'Có bản cam kết' : 'Thiếu bản cam kết'
      }
      return { verdict, actual, sources: f.sources.map(src => ({ source: src, verdict })) }
    }
  }
}

export interface RankedCtv { field: CtvField; index: number; verdict: FieldVerdict; actual: string; sources: SourceResult[] }

// Exception-first: most severe verdict first (mismatch, then review, ...), ties keep original order.
export function rankFolder(folder: CtvFolder): RankedCtv[] {
  return folder.fields
    .map((field, index) => {
      const r = evalField(field, folder)
      return { field, index, verdict: r.verdict, actual: r.actual, sources: r.sources }
    })
    .sort((a, b) => FIELD_SEVERITY[a.verdict] - FIELD_SEVERITY[b.verdict] || a.index - b.index)
}

export function counts(ranked: RankedCtv[]) {
  return {
    mismatch: ranked.filter(r => r.verdict === 'mismatch').length,
    review: ranked.filter(r => r.verdict === 'review').length,
    low_conf: ranked.filter(r => r.verdict === 'low_conf').length,
    fuzzy: ranked.filter(r => r.verdict === 'fuzzy').length,
  }
}
