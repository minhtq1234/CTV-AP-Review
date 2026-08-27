// src/components/UploadFlow.cccdGate.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CaseDetail as CaseDetailT, CccdSummary } from '../upload/api'

const getCase = vi.fn()

// Every value export reachable from UploadFlow's module graph. Omitting one
// makes the module that imports it throw, which surfaces as an unrelated-looking
// import error rather than a routing failure.
vi.mock('../upload/api', () => ({
  getCase: (...args: unknown[]) => getCase(...args),
  listCases: () => Promise.resolve([]),
  createCase: () => Promise.resolve({ case_id: 'case-1' }),
  setReview: () => Promise.resolve({}),
  deleteCase: () => Promise.resolve(),
  fetchPacketManifest: () => Promise.resolve(null),
  normalizePacketReview: () => ({ done: false, fields: {}, rejection: null }),
  caseProgressLabel: () => '',
  progressPct: () => 0,
  stageLabel: () => '',
  generateReport: () => Promise.resolve({}),
  reportUrls: () => ({ md: '', csv: '' }),
  fetchCaseSummary: () => Promise.resolve({}),
  fetchPacketCriteria: () => Promise.resolve({}),
  decideCriterionCell: () => Promise.resolve({}),
  listCccdCards: () => Promise.resolve([]),
  assignCccdCard: () => Promise.resolve({ cards: [], cccdSummary: null }),
  cccdCardImageUrl: () => '',
  PACKET_REJECTION_REASONS: [],
}))

vi.mock('./CaseList', () => ({
  default: ({ onOpen }: { onOpen: (id: string) => void }) => (
    <button type="button" onClick={() => onOpen('case-1')}>open-case</button>
  ),
}))

vi.mock('./CaseDetail', () => ({
  default: ({ detail }: { detail: CaseDetailT }) => (
    <p>{`DETAIL attached=${detail.cccdSummary?.attached ?? 'none'}`}</p>
  ),
}))

vi.mock('./CccdReviewScreen', () => ({
  default: ({ onContinue }: { onContinue: () => void }) => (
    <div>
      <p>CCCD-STEP</p>
      <button type="button" onClick={onContinue}>continue</button>
    </div>
  ),
}))

const UploadFlow = (await import('./UploadFlow')).default

const workbook: CccdSummary = {
  status: 'partial', candidates: 42, attached: 40, unresolved: 2,
}

function caseDetail(cccdSummary: CccdSummary | null): CaseDetailT {
  return {
    id: 'case-1',
    name: 'FA-SYNTHETIC.pdf',
    createdAt: null,
    status: 'ready',
    pdfName: 'FA-SYNTHETIC.pdf',
    rosterName: 'roster.xlsx',
    cccdName: cccdSummary ? 'cards.xlsx' : null,
    cccdSummary,
    summary: null,
    error: null,
    packets: [],
    progress: { done: 0, total: 0, flagged: 0 },
  }
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  getCase.mockReset()
  window.localStorage.clear()
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  // Guarantees any Storage.prototype spy from a throwing-storage test is torn
  // down even when the test's own assertions fail first — a mockRestore() at
  // the tail of a test body only runs on the pass path, and a still-throwing
  // spy would otherwise leak into (and break) the next test.
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

async function openTheCase() {
  await act(async () => { root.render(<UploadFlow />) })
  const open = [...host.querySelectorAll('button')]
    .find(el => el.textContent === 'open-case') as HTMLButtonElement
  await act(async () => { open.click() })
}

describe('the CCCD gate', () => {
  it('opens a case with a workbook on the review step', async () => {
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    expect(host.textContent).toContain('CCCD-STEP')
  })

  it('skips the step once it has been dismissed for that case', async () => {
    window.localStorage.setItem('cccd-reviewed:case-1', '2026-08-27T00:00:00.000Z')
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    expect(host.textContent).toContain('DETAIL')
    expect(host.textContent).not.toContain('CCCD-STEP')
  })

  it('never shows the step for a case uploaded without a workbook', async () => {
    getCase.mockResolvedValue(caseDetail(null))
    await openTheCase()
    expect(host.textContent).toContain('DETAIL')
  })

  it('records the dismissal when the reviewer continues', async () => {
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    const go = [...host.querySelectorAll('button')]
      .find(el => el.textContent === 'continue') as HTMLButtonElement
    await act(async () => { go.click() })
    expect(host.textContent).toContain('DETAIL')
    expect(window.localStorage.getItem('cccd-reviewed:case-1')).not.toBeNull()
  })

  it('still opens on the review step when reading the dismissal flag throws', async () => {
    // jsdom's localStorage is a "legacy platform object" — spying on the
    // instance (window.localStorage.getItem) never intercepts real calls;
    // the spy must sit on Storage.prototype. Restored in the shared afterEach.
    vi.spyOn(Storage.prototype, 'getItem')
      .mockImplementation(() => { throw new Error('blocked') })
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    expect(host.textContent).toContain('CCCD-STEP')
    expect(host.textContent).not.toContain('Không kết nối được')
  })

  it('still reaches the case detail when recording the dismissal flag throws', async () => {
    vi.spyOn(Storage.prototype, 'setItem')
      .mockImplementation(() => { throw new Error('blocked') })
    getCase.mockResolvedValue(caseDetail(workbook))
    await openTheCase()
    const go = [...host.querySelectorAll('button')]
      .find(el => el.textContent === 'continue') as HTMLButtonElement
    await act(async () => { go.click() })
    expect(host.textContent).toContain('DETAIL')
  })

  it('refreshes the case on the way out, so the packet list is not stale', async () => {
    getCase
      .mockResolvedValueOnce(caseDetail(workbook))                                  // 40 attached
      .mockResolvedValueOnce(caseDetail({ ...workbook, attached: 41, unresolved: 1 }))
    await openTheCase()
    expect(host.textContent).toContain('CCCD-STEP')

    const go = [...host.querySelectorAll('button')]
      .find(el => el.textContent === 'continue') as HTMLButtonElement
    await act(async () => { go.click() })

    expect(getCase).toHaveBeenCalledTimes(2)
    expect(host.textContent).toContain('DETAIL attached=41')
  })

  it('still lets the reviewer through when the refresh fails', async () => {
    getCase
      .mockResolvedValueOnce(caseDetail(workbook))
      .mockRejectedValueOnce(new Error('offline'))
    await openTheCase()
    const go = [...host.querySelectorAll('button')]
      .find(el => el.textContent === 'continue') as HTMLButtonElement
    await act(async () => { go.click() })

    expect(host.textContent).toContain('DETAIL attached=40')   // the stale value, deliberately
    expect(host.textContent).not.toContain('Không kết nối được')
  })
})
