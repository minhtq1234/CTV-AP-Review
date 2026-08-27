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

async function mount(onContinue = () => {}) {
  await act(async () => {
    root.render(
      <CccdReviewScreen
        caseId="case-1"
        caseName="FA-SYNTHETIC.pdf"
        packets={packets}
        onContinue={onContinue}
      />,
    )
  })
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
})
