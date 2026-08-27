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

vi.mock('./CaseDetail', () => ({ default: () => <p>DETAIL</p> }))

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
})
