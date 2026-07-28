import { describe, it, expect, test, vi } from 'vitest'
import {
  stageLabel,
  progressPct,
  withAbsolutePageSrc,
  caseProgressLabel,
  packetNeedsResubmit,
  reportUrls,
  API_BASE,
  createCase,
} from './api'

describe('upload api helpers', () => {
  it('maps stages to Vietnamese labels', () => {
    expect(stageLabel('splitting')).toMatch(/tách|phát hiện|đối chiếu/i)
    expect(stageLabel('ocr')).toMatch(/đọc|trích|OCR/i)
    expect(stageLabel('done')).toMatch(/hoàn tất|xong/i)
  })
  it('maps CCCD processing to the approved Vietnamese label', () => {
    expect(stageLabel('cccd')).toBe('Đọc và ghép ảnh CCCD…')
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

test('packetNeedsResubmit reads items', () => {
  const base = { matchedBy: 'cccd', review: { done: true, items: {} } } as any
  expect(packetNeedsResubmit(base)).toBe(false)
  expect(packetNeedsResubmit({ ...base, matchedBy: 'name' })).toBe(true)
  expect(packetNeedsResubmit({ ...base, review: { done: true,
    items: { A2: { seen: true, flag: { reason: 'sai', note: '' } } } } })).toBe(true)
})

test('reportUrls point at the backend', () => {
  expect(reportUrls('abc').md).toBe(`${API_BASE}/api/cases/abc/report.md`)
})

test('createCase appends the CCCD workbook to multipart form', async () => {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const form = init?.body as FormData
    expect((form.get('pdf') as File).name).toBe('input.pdf')
    expect((form.get('roster') as File).name).toBe('roster.xlsx')
    expect((form.get('cccd') as File).name).toBe('cards.xlsx')
    return new Response(JSON.stringify({ case_id: 'case-1' }), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    })
  })
  vi.stubGlobal('fetch', fetchMock)

  try {
    await createCase(
      new File(['pdf'], 'input.pdf', { type: 'application/pdf' }),
      new File(['roster'], 'roster.xlsx'),
      new File(['cards'], 'cards.xlsx'),
    )
    expect(fetchMock).toHaveBeenCalledOnce()
  } finally {
    vi.unstubAllGlobals()
  }
})

test('createCase keeps the legacy PDF-and-roster multipart shape', async () => {
  const fetchMock = vi.fn(async (_url: string, init?: RequestInit) => {
    const form = init?.body as FormData
    expect((form.get('pdf') as File).name).toBe('input.pdf')
    expect((form.get('roster') as File).name).toBe('roster.xlsx')
    expect(form.has('cccd')).toBe(false)
    return new Response(JSON.stringify({ case_id: 'case-1' }), { status: 200 })
  })
  vi.stubGlobal('fetch', fetchMock)

  try {
    await createCase(
      new File(['pdf'], 'input.pdf', { type: 'application/pdf' }),
      new File(['roster'], 'roster.xlsx'),
    )
    expect(fetchMock).toHaveBeenCalledOnce()
  } finally {
    vi.unstubAllGlobals()
  }
})
