import { afterEach, describe, it, expect, test, vi } from 'vitest'
import {
  stageLabel,
  progressPct,
  withAbsolutePageSrc,
  caseProgressLabel,
  packetNeedsResubmit,
  normalizePacketReview,
  reportUrls,
  API_BASE,
  createCase,
  getCase,
} from './api'

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('upload api helpers', () => {
  it('maps stages to Vietnamese labels', () => {
    expect(stageLabel('splitting')).toMatch(/tách|phát hiện|đối chiếu/i)
    expect(stageLabel('ocr')).toMatch(/đọc|trích|OCR/i)
    expect(stageLabel('done')).toMatch(/hoàn tất|xong/i)
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

test('createCase appends optional CCCD and preserves legacy multipart shape', async () => {
  const bodies: FormData[] = []
  vi.stubGlobal('fetch', vi.fn(async (_url: string, init?: RequestInit) => {
    bodies.push(init?.body as FormData)
    return new Response(JSON.stringify({ case_id: 'synthetic-case' }), {
      status: 200,
    })
  }))
  const pdf = new File(['pdf'], 'packet.pdf', { type: 'application/pdf' })
  const roster = new File(['roster'], 'roster.xlsx')
  const cccd = new File(['cards'], 'cards.xlsx')

  await createCase(pdf, roster, cccd)
  await createCase(pdf, roster)

  expect((bodies[0].get('cccd') as File).name).toBe('cards.xlsx')
  expect(bodies[1].has('cccd')).toBe(false)
})

describe('case helpers', () => {
  it('formats progress', () => {
    expect(caseProgressLabel({ done: 12, total: 32, flagged: 3 }))
      .toMatch(/12\/32.*xong.*3.*cần gửi lại/i)
  })
})

test('packetNeedsResubmit: only what a person decided', () => {
  // Mirrors server/cases.py. A weak roster match is the machine's observation,
  // reported as a candidate instead — see progress.candidates.
  const base = { index: 0, name: 'A', pages: [0, 7] as [number, number],
    confidence: 'green' as const, flags: [], labels: [],
    matchedBy: 'cccd' as const,
    ocrIdentity: { cccd: '1', name: 'A' }, rosterIdentity: null,
    reviewFieldCount: 0,
    review: { done: false, fields: {}, rejection: null } }
  expect(packetNeedsResubmit(base)).toBe(false)
  expect(packetNeedsResubmit({ ...base, matchedBy: 'name' })).toBe(false)
  expect(packetNeedsResubmit({ ...base, matchedBy: 'unmatched' })).toBe(false)
  expect(packetNeedsResubmit({ ...base, review: { done: true,
    fields: { a: { seen: true, flag: { reason: 'x', note: '' } } },
    rejection: null } })).toBe(true)
  expect(packetNeedsResubmit({ ...base, review: { done: false, fields: {},
    rejection: { reasons: ['missing_documents'], note: '' } } })).toBe(true)
  const decision = (toStatus: 'no' | 'ok') => ({ stt: 23, document: 'BBNT',
    fromStatus: 'rv' as const, toStatus, reason: '', at: 't', by: '' })
  expect(packetNeedsResubmit({ ...base, review: { done: false, fields: {},
    rejection: null, overrides: { '23:BBNT': [decision('no')] } } })).toBe(true)
  // reversed: the standing decision is what counts
  expect(packetNeedsResubmit({ ...base, review: { done: false, fields: {},
    rejection: null,
    overrides: { '23:BBNT': [decision('no'), decision('ok')] } } })).toBe(false)
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

test('getCase normalizes missing and present review field counts', async () => {
  const packet = {
    index: 0,
    name: 'Synthetic Person',
    pages: [0, 1],
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: 'synthetic', name: 'Synthetic Person' },
    rosterIdentity: { cccd: 'synthetic', name: 'Synthetic Person' },
    review: { done: false, fields: {}, rejection: null },
  }
  const detail = {
    id: 'synthetic-case',
    name: 'Synthetic Case',
    createdAt: null,
    status: 'ready',
    pdfName: 'synthetic.pdf',
    rosterName: null,
    summary: null,
    error: null,
    progress: { done: 0, total: 1, flagged: 0 },
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({ ...detail, packets: [packet] }),
    })
    .mockResolvedValueOnce({
      ok: true,
      json: async () => ({
        ...detail,
        packets: [{ ...packet, reviewFieldCount: 6 }],
      }),
    })
  vi.stubGlobal('fetch', fetchMock)

  expect((await getCase('synthetic-case')).packets[0].reviewFieldCount).toBe(0)
  expect((await getCase('synthetic-case')).packets[0].reviewFieldCount).toBe(6)
})
