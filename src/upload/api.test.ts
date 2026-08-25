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
  getBoundaryProposal,
  resolveBoundaryProposal,
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
  expect(packetNeedsResubmit({
    ...base,
    boundaryAssessment: {
      status: 'review',
      suspectedMultiplePackets: true,
      reasons: ['multiple-contract-starts'],
      candidateStarts: [10, 18],
    },
  })).toBe(false)
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
    status: 'processing',
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
        boundaryStatus: {
          status: 'review',
          packetIndexes: [0],
          reasons: ['multiple-contract-starts'],
        },
        publicationBlocked: true,
      }),
    })
  vi.stubGlobal('fetch', fetchMock)

  const legacyCase = await getCase('synthetic-case')
  const reviewedCase = await getCase('synthetic-case')
  const legacyPacket = legacyCase.packets[0]
  const countedPacket = reviewedCase.packets[0]
  expect(legacyPacket.reviewFieldCount).toBe(0)
  expect(countedPacket.reviewFieldCount).toBe(6)
  expect(legacyPacket.boundaryAssessment).toEqual({
    status: 'clear',
    suspectedMultiplePackets: false,
    reasons: [],
    candidateStarts: [],
  })
  expect(legacyCase.boundaryStatus).toEqual({
    status: 'clear', packetIndexes: [], reasons: [],
  })
  expect(legacyCase.publicationBlocked).toBe(false)
  expect(reviewedCase.boundaryStatus).toEqual({
    status: 'review',
    packetIndexes: [0],
    reasons: ['multiple-contract-starts'],
  })
  expect(reviewedCase.publicationBlocked).toBe(true)
})

test('getCase adds compact dashboard evidence summaries for ready packets', async () => {
  const detail = {
    id: 'synthetic-case',
    name: 'Synthetic Case',
    createdAt: null,
    status: 'ready',
    pdfName: 'synthetic.pdf',
    rosterName: null,
    cccdName: null,
    cccdSummary: null,
    summary: null,
    error: null,
    progress: { done: 0, total: 1, flagged: 0 },
    packets: [{
      index: 0,
      name: 'Synthetic Person',
      pages: [0, 1],
      confidence: 'green',
      flags: [],
      matchedBy: 'cccd',
      ocrIdentity: { cccd: 'synthetic', name: 'Synthetic Person' },
      rosterIdentity: { cccd: 'synthetic', name: 'Synthetic Person' },
      review: { done: false, fields: {}, rejection: null },
      reviewFieldCount: 1,
      boundaryAssessment: {
        status: 'review',
        suspectedMultiplePackets: true,
        reasons: ['multiple-contract-starts'],
        candidateStarts: [10, 18],
      },
    }],
  }
  const manifest = {
    id: 'synthetic-folder',
    name: 'Synthetic Person',
    product: 'Synthetic Product',
    status: 'pending',
    exempt: false,
    docs: ['id_front', 'id_back', 'contract', 'bbnt', 'appendix', 'commitment']
      .map((kind, index) => ({
        id: `doc-${index}`,
        kind,
        label: `Synthetic ${kind}`,
        pages: [{ src: `/page-${index}.png`, width: 100, height: 100 }],
      })),
    fields: [{
      key: 'name',
      label: 'Name',
      group: 'Danh tính',
      check: 'compare',
      kind: 'text',
      expected: 'Synthetic Person',
      sources: [{
        docId: 'doc-2', page: 0, value: 'Synthetic Person', confidence: 0.99,
        bbox: { x: 0, y: 0, width: 10, height: 10 },
      }],
    }],
  }
  vi.stubGlobal('fetch', vi.fn(async (url: string) => (
    url.endsWith('/manifest.json')
      ? { ok: true, json: async () => manifest }
      : { ok: true, json: async () => detail }
  )))

  const result = await getCase('synthetic-case')

  expect(result.packets[0].dashboardSummary).toEqual({
    taxCommitmentDetected: true,
    documents: { present: 5, total: 5, missing: [] },
    aiResult: 'review',
  })
})

test('boundary proposal API reads the source proposal and posts exact zero-based starts', async () => {
  const proposal = {
    status: 'review_required',
    sourceCaseId: 'source-case',
    expectedPacketCount: 3,
    currentPacketCount: 2,
    candidateStarts: [{
      page: 8,
      packetIndex: 1,
      relativePage: 0,
      signals: ['contract-title'],
      confidence: 'medium',
    }],
    affectedPacketIndexes: [1],
    affectedRanges: [{ packetIndex: 1, startPage: 8, endPage: 15 }],
    correctionEnabled: true,
  }
  const resolved = {
    caseId: 'revision-case',
    sourceCaseId: 'source-case',
    status: 'processing',
  }
  const fetchMock = vi.fn()
    .mockResolvedValueOnce(new Response(JSON.stringify(proposal), { status: 200 }))
    .mockResolvedValueOnce(new Response(JSON.stringify(resolved), { status: 200 }))
  vi.stubGlobal('fetch', fetchMock)

  await expect(getBoundaryProposal('source-case')).resolves.toEqual(proposal)
  await expect(resolveBoundaryProposal('source-case', {
    action: 'create-revision',
    starts: [0, 8, 16],
  })).resolves.toEqual(resolved)

  expect(fetchMock.mock.calls[0][0]).toBe(
    `${API_BASE}/api/cases/source-case/boundary-proposal`,
  )
  expect(fetchMock.mock.calls[1]).toEqual([
    `${API_BASE}/api/cases/source-case/boundary-proposal/resolve`,
    {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({
        action: 'create-revision',
        starts: [0, 8, 16],
      }),
    },
  ])
})

test('boundary resolution throws on a non-success response', async () => {
  vi.stubGlobal('fetch', vi.fn(async () => new Response(null, { status: 409 })))

  await expect(resolveBoundaryProposal('source-case', {
    action: 'keep-current',
  })).rejects.toThrow('resolveBoundaryProposal: HTTP 409')
})
