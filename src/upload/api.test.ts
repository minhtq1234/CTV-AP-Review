import { describe, it, expect, test } from 'vitest'
import {
  stageLabel,
  progressPct,
  withAbsolutePageSrc,
  caseProgressLabel,
  packetNeedsResubmit,
  normalizePacketReview,
  reportUrls,
  API_BASE,
} from './api'

describe('upload api helpers', () => {
  it('maps stages to Vietnamese labels', () => {
    expect(stageLabel('splitting')).toMatch(/tách|phát hiện|đối chiếu/i)
    expect(stageLabel('ocr')).toMatch(/đọc|trích|OCR/i)
    expect(stageLabel('done')).toMatch(/hoàn tất|xong/i)
  })
  it('computes percent, clamped, 0 when total is 0', () => {
    expect(progressPct({ stage: 'ocr', done: 8, total: 32, detail: '' })).toBe(25)
    expect(progressPct({ stage: 'queued', done: 0, total: 0, detail: '' })).toBe(0)
    expect(progressPct({ stage: 'done', done: 32, total: 32, detail: '' })).toBe(100)
  })
  it('prepends the API base to every page src', () => {
    const m: any = { docs: [{ pages: [{ src: '/api/jobs/J/packets/0/page/pg0.png', width: 1, height: 1 }] }] }
    const out = withAbsolutePageSrc(m, 'http://127.0.0.1:8000')
    expect(out.docs[0].pages[0].src).toBe('http://127.0.0.1:8000/api/jobs/J/packets/0/page/pg0.png')
  })
})

describe('case helpers', () => {
  it('formats progress', () => {
    expect(caseProgressLabel({ done: 12, total: 32, flagged: 3 }))
      .toMatch(/12\/32.*xong.*3.*cần gửi lại/i)
  })
})

test('packetNeedsResubmit: field flag or weak match', () => {
  const base = {
    matchedBy: 'cccd',
    review: { done: true, fields: {}, rejection: null },
  } as any
  expect(packetNeedsResubmit(base)).toBe(false)
  expect(packetNeedsResubmit({ ...base, matchedBy: 'name' })).toBe(true)
  expect(packetNeedsResubmit({ ...base, review: { done: true,
    fields: { cccd: { seen: true, flag: { reason: 'sai', note: '' } } },
    rejection: null } })).toBe(true)
  expect(packetNeedsResubmit({
    ...base,
    review: {
      done: true,
      fields: {},
      rejection: { reasons: ['missing_documents'], note: '' },
    },
  })).toBe(true)
})

test('normalizePacketReview adds the additive legacy default', () => {
  expect(normalizePacketReview({ done: true, fields: {} } as any))
    .toEqual({ done: true, fields: {}, rejection: null })
  expect(normalizePacketReview(undefined))
    .toEqual({ done: false, fields: {}, rejection: null })
})

test('reportUrls point at the backend', () => {
  expect(reportUrls('abc').md).toBe(`${API_BASE}/api/cases/abc/report.md`)
})
