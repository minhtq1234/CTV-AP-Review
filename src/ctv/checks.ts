import type { Verdict } from '../types'
import { compareField } from '../logic/verdict'
import type { CtvField, CtvFolder } from './types'

// Fixed "today" for the demo so the expiry check is deterministic.
export const REVIEW_DATE = new Date(2026, 6, 13) // 2026-07-13

const digits = (s: string) => s.replace(/[^\d]/g, '')

function parseVnDate(s: string): Date | null {
  const m = s.match(/(\d{1,2})[/-](\d{1,2})[/-](\d{4})/)
  if (!m) return null
  return new Date(+m[3], +m[2] - 1, +m[1])
}

const vnd = (n: number) => `${n.toLocaleString('vi-VN')} ₫`

export interface CheckResult { verdict: Verdict; actual: string }

// One field's verdict + the "actual" value to display, given its check type.
export function evalField(f: CtvField, folder: CtvFolder): CheckResult {
  switch (f.check) {
    case 'compare': {
      const v = compareField(
        f.expected,
        f.extract ? { value: f.extract.value, confidence: f.extract.confidence, page: 0, bbox: f.extract.bbox } : null,
        f.kind,
      )
      return { verdict: v, actual: f.extract?.value ?? '—' }
    }
    case 'expiry': {
      const d = f.extract ? parseVnDate(f.extract.value) : null
      const expired = !d || d < REVIEW_DATE
      return {
        verdict: expired ? 'mismatch' : 'match',
        actual: f.extract ? (expired ? `Hết hạn ${f.extract.value}` : `Hiệu lực đến ${f.extract.value}`) : '—',
      }
    }
    case 'math': {
      const num = (k: string) => {
        const fld = folder.fields.find(x => x.key === k)
        return fld ? parseInt(digits(fld.expected) || '0', 10) : 0
      }
      const claimed = parseInt(digits(f.expected) || '0', 10)
      if (f.key === 'pit') {
        // PIT should be 10% of gross when not exempt, 0 when exempt
        const expected = folder.exempt ? 0 : Math.round(num('gross') * 0.1)
        return { verdict: claimed === expected ? 'match' : 'mismatch', actual: vnd(expected) }
      }
      // net = gross - pit
      const computed = num('gross') - num('pit')
      return { verdict: computed === claimed ? 'match' : 'mismatch', actual: vnd(computed) }
    }
    case 'policy': {
      if (!folder.exempt) return { verdict: 'match', actual: 'Khấu trừ 10% (không miễn)' }
      const hasCommit = folder.docs.some(d => d.kind === 'commitment')
      return { verdict: hasCommit ? 'match' : 'mismatch', actual: hasCommit ? 'Có bản cam kết' : 'Thiếu bản cam kết' }
    }
  }
}

const SEVERITY: Record<Verdict, number> = { mismatch: 0, low_conf: 1, fuzzy: 2, match: 3 }

export interface RankedCtv { field: CtvField; index: number; verdict: Verdict; actual: string }

// Exception-first: most severe verdict first, ties keep original order.
export function rankFolder(folder: CtvFolder): RankedCtv[] {
  return folder.fields
    .map((field, index) => {
      const r = evalField(field, folder)
      return { field, index, verdict: r.verdict, actual: r.actual }
    })
    .sort((a, b) => SEVERITY[a.verdict] - SEVERITY[b.verdict] || a.index - b.index)
}

export function counts(ranked: RankedCtv[]) {
  return {
    mismatch: ranked.filter(r => r.verdict === 'mismatch').length,
    low_conf: ranked.filter(r => r.verdict === 'low_conf').length,
    fuzzy: ranked.filter(r => r.verdict === 'fuzzy').length,
  }
}
