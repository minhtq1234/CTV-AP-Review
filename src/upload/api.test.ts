import { describe, it, expect } from 'vitest'
import { stageLabel, progressPct, withAbsolutePageSrc, caseProgressLabel, decisionBadge } from './api'

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
    expect(caseProgressLabel({ decided: 12, total: 32, flagged: 3 }))
      .toMatch(/12\/32.*duyệt.*3.*cần xem/i)
  })
  it('maps decision to badge', () => {
    expect(decisionBadge('approved')).toMatch(/duyệt/i)
    expect(decisionBadge('rejected')).toMatch(/từ chối/i)
    expect(decisionBadge('pending')).toMatch(/chưa xem/i)
  })
})
