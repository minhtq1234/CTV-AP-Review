// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  BoundaryProposal,
  CaseDetail,
  CaseSummary,
} from '../upload/api'
import BoundaryReviewScreen from './BoundaryReviewScreen'
import UploadFlow from './UploadFlow'

const apiMocks = vi.hoisted(() => ({
  listCases: vi.fn(),
  getCase: vi.fn(),
  getBoundaryProposal: vi.fn(),
  resolveBoundaryProposal: vi.fn(),
  createCase: vi.fn(),
  setReview: vi.fn(),
  deleteCase: vi.fn(),
  fetchPacketManifest: vi.fn(),
}))

vi.mock('../upload/api', async () => ({
  ...await vi.importActual<typeof import('../upload/api')>('../upload/api'),
  ...apiMocks,
}))

let root: Root
let container: HTMLDivElement

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.clearAllMocks()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

function proposalWithPages(
  pages: number[],
  overrides: Partial<BoundaryProposal> = {},
): BoundaryProposal {
  return {
    status: 'review_required',
    sourceCaseId: 'source-case',
    expectedPacketCount: 3,
    currentPacketCount: 2,
    candidateStarts: pages.map(page => ({
      page,
      packetIndex: page < 8 ? 0 : 1,
      relativePage: page < 8 ? page : page - 8,
      signals: page % 8 === 0 ? ['visual'] : ['contract-title', 'cadence'],
      confidence: page % 8 === 0 ? 'medium' : 'high',
    })),
    affectedPacketIndexes: [1],
    correctionEnabled: true,
    ...overrides,
  }
}

function renderBoundary(
  proposal: BoundaryProposal,
  onResolve = vi.fn(),
  onBack = vi.fn(),
) {
  act(() => {
    root.render(
      <BoundaryReviewScreen
        proposal={proposal}
        onResolve={onResolve}
        onBack={onBack}
      />,
    )
  })
  return { onResolve, onBack }
}

function button(name: string): HTMLButtonElement {
  const match = Array.from(container.querySelectorAll('button'))
    .find(candidate => candidate.textContent?.trim() === name)
  if (!match) throw new Error(`button not found: ${name}`)
  return match
}

async function click(element: Element) {
  await act(async () => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
    await Promise.resolve()
  })
}

async function flush() {
  await act(async () => {
    await Promise.resolve()
    await Promise.resolve()
  })
}

describe('boundary review presentation and controls', () => {
  it('displays only affected one-based candidates but posts the complete zero-based starts', async () => {
    const { onResolve } = renderBoundary(proposalWithPages([0, 8, 16]))

    const visiblePages = Array.from(
      container.querySelectorAll('.boundary-candidate-title strong'),
    ).map(element => element.textContent)
    expect(visiblePages).toEqual(['Trang 9', 'Trang 17'])
    const sources = Array.from(container.querySelectorAll('img'))
      .map(image => image.getAttribute('src'))
    expect(sources).toContain(
      'http://127.0.0.1:8001/api/cases/source-case/packets/1/page/pg0.png',
    )
    expect(sources.join(' ')).not.toMatch(/private|file:|\/Users\//)

    await click(button('Tạo phiên bản đã sửa'))

    expect(onResolve).toHaveBeenCalledWith({
      action: 'create-revision',
      starts: [0, 8, 16],
    })
  })

  it('removes and adds candidate starts without converting their page basis', async () => {
    const { onResolve } = renderBoundary(proposalWithPages([0, 8, 16]))

    await click(button('Bỏ ranh giới Trang 17'))
    await click(button('Tạo phiên bản đã sửa'))
    expect(onResolve).toHaveBeenLastCalledWith({
      action: 'create-revision',
      starts: [0, 8],
    })

    await click(button('Thêm ranh giới Trang 17'))
    await click(button('Tạo phiên bản đã sửa'))
    expect(onResolve).toHaveBeenLastCalledWith({
      action: 'create-revision',
      starts: [0, 8, 16],
    })
  })

  it('keeps the source on explicit keep and leaves it untouched on Back', async () => {
    const { onResolve, onBack } = renderBoundary(proposalWithPages([0, 8, 16]))

    await click(button('Giữ ranh giới hiện tại'))
    expect(onResolve).toHaveBeenCalledWith({ action: 'keep-current' })

    await click(button('Quay lại'))
    expect(onBack).toHaveBeenCalledOnce()
    expect(onResolve).toHaveBeenCalledTimes(1)
  })

  it('disables revision submission when the source start is removed', async () => {
    renderBoundary(proposalWithPages([0, 8], { affectedPacketIndexes: [0, 1] }))

    await click(button('Bỏ ranh giới Trang 1'))

    expect(button('Tạo phiên bản đã sửa').disabled).toBe(true)
  })

  it('normalizes unsorted duplicate proposal pages before posting zero-based starts', async () => {
    const { onResolve } = renderBoundary(proposalWithPages(
      [16, 8, 8, 0],
      { affectedPacketIndexes: [0, 1] },
    ))

    expect(button('Tạo phiên bản đã sửa').disabled).toBe(false)
    await click(button('Tạo phiên bản đã sửa'))

    expect(onResolve).toHaveBeenCalledWith({
      action: 'create-revision',
      starts: [0, 8, 16],
    })
  })

  it('preserves a valid nonzero source start and disables submit only after removing it', async () => {
    const { onResolve } = renderBoundary(proposalWithPages(
      [4, 12],
      { affectedPacketIndexes: [0, 1] },
    ))

    expect(button('Tạo phiên bản đã sửa').disabled).toBe(false)
    await click(button('Tạo phiên bản đã sửa'))
    expect(onResolve).toHaveBeenCalledWith({
      action: 'create-revision',
      starts: [4, 12],
    })

    await click(button('Bỏ ranh giới Trang 5'))
    expect(button('Tạo phiên bản đã sửa').disabled).toBe(true)
  })

  it('disables revision submission when no integer proposal starts remain', () => {
    renderBoundary(proposalWithPages([]))

    expect(button('Tạo phiên bản đã sửa').disabled).toBe(true)
  })

  it('is read-only in shadow mode while Back remains active', async () => {
    const { onResolve, onBack } = renderBoundary(proposalWithPages([0, 8, 16], {
      correctionEnabled: false,
    }))

    expect(container.textContent).toContain('Đang chạy thử đề xuất ranh giới')
    expect(container.textContent).not.toContain('Tạo phiên bản đã sửa')
    expect(container.textContent).not.toContain('Giữ ranh giới hiện tại')
    expect(container.textContent).not.toContain('Bỏ ranh giới')

    await click(button('Quay lại'))
    expect(onBack).toHaveBeenCalledOnce()
    expect(onResolve).not.toHaveBeenCalled()
  })
})

function caseSummary(id: string, name: string): CaseSummary {
  return {
    id,
    name,
    createdAt: null,
    status: 'ready',
    pdfName: `${id}.pdf`,
    progress: { done: 0, total: 1, flagged: 0 },
  }
}

function caseDetail(
  id: string,
  name: string,
  status: CaseDetail['status'] = 'ready',
): CaseDetail {
  return {
    ...caseSummary(id, name),
    status,
    rosterName: null,
    cccdName: null,
    cccdSummary: null,
    summary: null,
    error: null,
    packets: [],
    boundaryStatus: status === 'processing'
      ? { status: 'clear', packetIndexes: [], reasons: [] }
      : {
          status: 'review',
          packetIndexes: [1],
          reasons: ['multiple-contract-starts'],
        },
    publicationBlocked: status !== 'processing',
  }
}

it('polls and opens the returned revision case instead of refreshing the source', async () => {
  vi.useFakeTimers()
  const source = caseDetail('source-case', 'Source case')
  const processing = caseDetail('revision-case', 'Revision processing', 'processing')
  const revision = caseDetail('revision-case', 'Revision ready')
  apiMocks.listCases.mockResolvedValue([caseSummary('source-case', 'Source case')])
  apiMocks.getCase.mockImplementation(async (id: string) => {
    if (id === 'source-case') return source
    return apiMocks.getCase.mock.calls.filter(call => call[0] === 'revision-case').length === 1
      ? processing
      : revision
  })
  apiMocks.getBoundaryProposal.mockResolvedValue(proposalWithPages([0, 8, 16]))
  apiMocks.resolveBoundaryProposal.mockResolvedValue({
    caseId: 'revision-case',
    sourceCaseId: 'source-case',
    status: 'processing',
  })

  act(() => root.render(<UploadFlow />))
  await flush()
  const sourceRow = Array.from(container.querySelectorAll('.case-row'))
    .find(row => row.textContent?.includes('Source case'))
  expect(sourceRow).toBeDefined()
  await click(sourceRow!)
  await flush()
  await click(button('Kiểm tra ranh giới'))
  await flush()
  await click(button('Tạo phiên bản đã sửa'))
  await flush()

  expect(apiMocks.getCase).toHaveBeenCalledWith('revision-case')
  expect(container.textContent).not.toContain('Revision ready')

  await act(async () => {
    await vi.advanceTimersByTimeAsync(1000)
  })
  await flush()

  expect(container.textContent).toContain('Revision ready')
  expect(apiMocks.getCase.mock.calls.filter(call => call[0] === 'source-case'))
    .toHaveLength(1)
})
