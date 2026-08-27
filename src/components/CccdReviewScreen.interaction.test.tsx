// src/components/CccdReviewScreen.interaction.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CccdCard, PacketMeta } from '../upload/api'

const listCccdCards = vi.fn()
const assignCccdCard = vi.fn()

vi.mock('../upload/api', () => ({
  listCccdCards: (...args: unknown[]) => listCccdCards(...args),
  assignCccdCard: (...args: unknown[]) => assignCccdCard(...args),
  cccdCardImageUrl: (caseId: string, cardId: string, side: string) => (
    `/api/cases/${caseId}/cccd-cards/${cardId}/image/${side}`
  ),
}))

vi.mock('./CccdCardPicker', () => ({
  default: ({ packetIndex, packetLabel, onAssigned, onCancel }: {
    packetIndex: number
    packetLabel: string
    onAssigned: () => void
    onCancel: () => void
  }) => (
    <div data-testid="picker">
      <span>{`picker:${packetIndex}:${packetLabel}`}</span>
      <button type="button" onClick={onAssigned}>mock-assigned</button>
      <button type="button" onClick={onCancel}>mock-cancel</button>
    </div>
  ),
}))

const CccdReviewScreen = (await import('./CccdReviewScreen')).default

function packet(index: number, name: string): PacketMeta {
  return {
    index,
    name,
    pages: [index * 2, index * 2 + 1],
    n_pages: 2,
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: 'synthetic', name },
    rosterIdentity: { cccd: 'synthetic', name },
    review: { done: false, fields: {}, rejection: null },
    reviewFieldCount: 6,
  }
}

function card(cardId: string, attachedPacketIndex: number | null): CccdCard {
  return {
    cardId,
    state: attachedPacketIndex === null ? 'conflict' : 'exact',
    attachedPacketIndex,
    number: '',
    issues: [],
    sides: [{ side: 'front', width: 1059, height: 668 }],
  }
}

const packets = [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')]

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  listCccdCards.mockReset()
  assignCccdCard.mockReset()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

// Re-rendering into the same root keeps the same instance, so `caseId` changes
// in place — what UploadFlow's render branch does, since it carries no `key`.
async function render(caseId: string, onContinue = () => {}) {
  await act(async () => {
    root.render(
      <CccdReviewScreen
        caseId={caseId}
        caseName="FA-SYNTHETIC.pdf"
        packets={packets}
        onContinue={onContinue}
      />,
    )
  })
}

async function mount(onContinue = () => {}) {
  await render('case-1', onContinue)
}

// A response the test lands by hand, after the screen has moved on.
function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(res => { resolve = res })
  return { promise, resolve }
}

function button(text: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')]
    .find(el => el.textContent?.includes(text))
  if (!found) throw new Error(`no button matching ${text}: ${host.textContent}`)
  return found as HTMLButtonElement
}

describe('CccdReviewScreen', () => {
  it('loads the cards for the case and renders the buckets', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0), card('card-09', null)])
    await mount()
    expect(listCccdCards).toHaveBeenCalledWith('case-1')
    expect(host.textContent).toContain('Synthetic B')
    expect(host.textContent).toContain('1 gói chưa có thẻ')
  })

  it('shows a load failure instead of an empty screen', async () => {
    listCccdCards.mockRejectedValue(new Error('boom'))
    await mount()
    expect(host.textContent).toContain('Không tải được danh sách ảnh.')
  })

  it('hands "Tiếp tục" straight through', async () => {
    listCccdCards.mockResolvedValue([])
    const onContinue = vi.fn()
    await mount(onContinue)
    await act(async () => { button('Tiếp tục').click() })
    expect(onContinue).toHaveBeenCalledOnce()
  })

  it('does not claim any packet needs a card when the load fails', async () => {
    listCccdCards.mockRejectedValue(new Error('boom'))
    await mount()
    expect(host.textContent).toContain('Không tải được danh sách ảnh.')
    expect(host.textContent).not.toContain('Synthetic B')
  })

  it('retries the load when "Thử lại" is clicked', async () => {
    listCccdCards.mockRejectedValueOnce(new Error('boom'))
    listCccdCards.mockResolvedValueOnce([card('card-00', 0), card('card-09', null)])
    await mount()
    expect(host.textContent).toContain('Không tải được danh sách ảnh.')

    await act(async () => { button('Thử lại').click() })

    expect(listCccdCards).toHaveBeenCalledTimes(2)
    expect(host.textContent).toContain('Synthetic B')
    expect(host.textContent).toContain('1 gói chưa có thẻ')
  })

  it('detaches with a null packetIndex and re-renders from the response', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0), card('card-01', 1)])
    assignCccdCard.mockResolvedValue({
      cards: [card('card-00', 0), card('card-01', null)],
      cccdSummary: { status: 'partial', candidates: 2, attached: 1, unresolved: 1 },
    })
    await mount()
    await act(async () => { button('Gỡ').click() })
    expect(assignCccdCard).toHaveBeenCalledWith('case-1', 'card-00', null)
    expect(host.textContent).toContain('1 gói chưa có thẻ')
    // The response is authoritative — no second GET.
    expect(listCccdCards).toHaveBeenCalledOnce()
  })

  it('translates a rejected detach into its Vietnamese message', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    assignCccdCard.mockRejectedValue(new Error('card-not-found'))
    await mount()
    await act(async () => { button('Gỡ').click() })
    expect(host.textContent).toContain('Không tìm thấy ảnh này.')
  })

  // Both cases below swap `caseId` on a mounted screen while a request for the
  // old case is still in flight. Its response describes a case the reviewer is
  // no longer looking at, so it must not be rendered.
  it('drops a detach response that arrives after the screen moved to another case', async () => {
    listCccdCards.mockImplementation((cid: string) => Promise.resolve(
      cid === 'case-1' ? [card('card-00', 0), card('card-01', 1)] : [],
    ))
    const detached = deferred<{ cards: CccdCard[] }>()
    assignCccdCard.mockReturnValue(detached.promise)

    await render('case-1')
    await act(async () => { button('Gỡ').click() })

    await render('case-2')
    expect(host.textContent).toContain('2 gói chưa có thẻ')

    await act(async () => {
      detached.resolve({ cards: [card('card-00', 0), card('card-01', null)] })
      await detached.promise
    })

    expect(host.textContent).toContain('2 gói chưa có thẻ')
    expect(host.textContent).not.toContain('1 gói chưa có thẻ')
  })

  it('drops a load response that arrives after the screen moved to another case', async () => {
    const first = deferred<CccdCard[]>()
    listCccdCards.mockImplementation((cid: string) => (
      cid === 'case-1' ? first.promise : Promise.resolve([])
    ))

    await render('case-1')
    await render('case-2')
    expect(host.textContent).toContain('2 gói chưa có thẻ')

    await act(async () => {
      first.resolve([card('card-00', 0), card('card-01', 1)])
      await first.promise
    })

    expect(host.textContent).toContain('2 gói chưa có thẻ')
    expect(host.textContent).not.toContain('0 gói chưa có thẻ')
  })

  it('opens the picker for the packet whose row was clicked', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    expect(host.textContent).toContain('picker:1:Synthetic B')
  })

  it('refetches after the picker reports an assignment, and closes it', async () => {
    listCccdCards
      .mockResolvedValueOnce([card('card-00', 0)])
      .mockResolvedValueOnce([card('card-00', 0), card('card-09', 1)])
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    await act(async () => { button('mock-assigned').click() })
    expect(listCccdCards).toHaveBeenCalledTimes(2)
    expect(host.querySelector('[data-testid="picker"]')).toBeNull()
    expect(host.textContent).toContain('0 gói chưa có thẻ')
  })

  it('closes the picker on cancel without refetching', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    await act(async () => { button('mock-cancel').click() })
    expect(host.querySelector('[data-testid="picker"]')).toBeNull()
    expect(listCccdCards).toHaveBeenCalledOnce()
  })

  it('keeps the current rows on screen while an assignment refetches', async () => {
    const second = deferred<CccdCard[]>()
    listCccdCards
      .mockResolvedValueOnce([card('card-00', 0)])
      .mockReturnValueOnce(second.promise)
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    await act(async () => { button('mock-assigned').click() })
    // The refetch is in flight: the list the reviewer was reading must still be
    // there, not replaced by the loading state.
    expect(host.textContent).toContain('Synthetic B')
    expect(host.textContent).not.toContain('Đang tải…')
    await act(async () => {
      second.resolve([card('card-00', 0), card('card-09', 1)])
      await second.promise
    })
    expect(host.textContent).toContain('0 gói chưa có thẻ')
  })

  it('closes a picker opened against the previous case', async () => {
    listCccdCards.mockImplementation((cid: string) => Promise.resolve(
      cid === 'case-1' ? [card('card-00', 0)] : [],
    ))
    await render('case-1')
    await act(async () => { button('Gán thẻ').click() })
    expect(host.querySelector('[data-testid="picker"]')).not.toBeNull()

    await render('case-2')
    // Left open, this picker would post case-1's packetIndex against case-2.
    expect(host.querySelector('[data-testid="picker"]')).toBeNull()
  })
})
