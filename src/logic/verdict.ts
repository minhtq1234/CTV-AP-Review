import type { CaseField, FieldKind, Prediction, Verdict } from '../types'

export const LOW_CONF = 0.7      // below this confidence -> low_conf
export const NAME_SIM = 0.8      // name similarity >= this (and not exact) -> fuzzy

const digits = (s: string) => s.replace(/[^\d]/g, '')

function normNumber(s: string): string { return String(parseInt(digits(s) || 'NaN', 10)) }

function normDate(s: string): string {
  const t = s.trim()
  let m = t.match(/^(\d{4})[-/](\d{1,2})[-/](\d{1,2})$/)          // YYYY-MM-DD
  if (m) return `${+m[3]}-${+m[2]}-${+m[1]}`
  m = t.match(/^(\d{1,2})[-/](\d{1,2})[-/](\d{4})$/)              // DD/MM/YYYY
  if (m) return `${+m[1]}-${+m[2]}-${+m[3]}`
  return t
}

function stripDiacritics(s: string): string {
  return s.normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/đ/g, 'd').replace(/Đ/g, 'D')
}

// Personal names get no company-suffix stripping and no token-containment
// shortcuts -- only accent folding, so an OCR read that lost its tone marks can
// still line up with the roster.
function normPerson(s: string): string {
  return stripDiacritics(s.toLowerCase())
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

/** Plain edit-distance ratio -- no containment floor. */
function editRatio(a: string, b: string): number {
  const longer = Math.max(a.length, b.length)
  return longer === 0 ? 1 : 1 - levenshtein(a, b) / longer
}

function normName(s: string): string {
  return stripDiacritics(s.toLowerCase())
    .replace(/\b(cong ty|cty|tnhh|cp|co\.?|ltd|jsc)\b/g, ' ')
    .replace(/[^a-z0-9 ]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
}

function levenshtein(a: string, b: string): number {
  const m = a.length, n = b.length
  const d: number[][] = Array.from({ length: m + 1 }, (_, i) => [i, ...Array(n).fill(0)])
  for (let j = 0; j <= n; j++) d[0][j] = j
  for (let i = 1; i <= m; i++)
    for (let j = 1; j <= n; j++)
      d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1))
  return d[m][n]
}

function similarity(a: string, b: string): number {
  if (!a && !b) return 1
  const longer = Math.max(a.length, b.length)
  if (longer === 0) return 1
  const at = a.split(' '), bt = b.split(' ')
  // a fully-contained token set (e.g. "grab" inside "cong ty tnhh grab") floors the score at 0.9;
  // a short common token can over-boost dissimilar names — acceptable heuristic for this prototype
  const contained = at.every(t => bt.includes(t)) || bt.every(t => at.includes(t))
  const lev = 1 - levenshtein(a, b) / longer
  return contained ? Math.max(lev, 0.9) : lev
}

function baseVerdict(expected: string, value: string, kind: FieldKind): Verdict {
  switch (kind) {
    case 'number': {
      if (!digits(expected) || !digits(value)) return 'mismatch'   // no parseable number on a side -> not a match
      return normNumber(expected) === normNumber(value) ? 'match' : 'mismatch'
    }
    case 'date':   return normDate(expected) === normDate(value) ? 'match' : 'mismatch'
    case 'text':   return expected.trim() === value.trim() ? 'match' : 'mismatch'
    case 'name': {
      if (expected.trim() === value.trim()) return 'match'
      const sim = similarity(normName(expected), normName(value))
      return sim >= NAME_SIM ? 'fuzzy' : 'mismatch'
    }
    case 'person': {
      if (expected.trim() === value.trim()) return 'match'
      const a = normPerson(expected)
      const b = normPerson(value)
      if (!a || !b) return 'mismatch'
      // Same letters, different tone marks. Tesseract drops Vietnamese
      // diacritics routinely -- but so does the difference between Anh and
      // Ánh, or Hùng and Hưng, who are different people. Never a pass; always
      // worth a look.
      if (a === b) return 'fuzzy'
      // A person's name is not a prefix of another person's. "Lê Thị Thu Hà"
      // and "Lê Thị Thu Hà Vy" are two people however close the strings are,
      // so a differing word count is a mismatch, not a near miss.
      if (a.split(' ').length !== b.split(' ').length) return 'mismatch'
      return editRatio(a, b) >= NAME_SIM ? 'fuzzy' : 'mismatch'
    }
  }
}

export function compareField(expected: string, prediction: Prediction | null, kind: FieldKind): Verdict {
  if (!prediction) return 'mismatch'
  const base = baseVerdict(expected, prediction.value, kind)
  if (base === 'mismatch') return 'mismatch'
  if (prediction.confidence < LOW_CONF) return 'low_conf'
  return base
}

// An approximate identity match is the wrong-person case, which is the most
// expensive error this tool can wave through -- so it sorts just behind an
// outright mismatch, ahead of a merely low-confidence read.
const SEVERITY: Record<Verdict, number> = { mismatch: 0, fuzzy: 1, low_conf: 2, match: 3 }

export interface RankedField { field: CaseField; index: number; verdict: Verdict }

export function orderFields(fields: CaseField[]): RankedField[] {
  return fields
    .map((field, index) => ({ field, index, verdict: compareField(field.expected, field.prediction, field.kind) }))
    .sort((a, b) => {
      if (SEVERITY[a.verdict] !== SEVERITY[b.verdict]) return SEVERITY[a.verdict] - SEVERITY[b.verdict]
      const pa = a.field.prediction, pb = b.field.prediction
      const paPage = pa ? pa.page : Infinity, pbPage = pb ? pb.page : Infinity
      if (paPage !== pbPage) return paPage - pbPage
      const ay = pa ? pa.bbox.y : Infinity, by = pb ? pb.bbox.y : Infinity
      return ay - by
    })
}
