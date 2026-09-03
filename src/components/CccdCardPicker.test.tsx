// src/components/CccdCardPicker.test.tsx
// @vitest-environment jsdom
//
// The picker had no tests of its own: CccdReviewScreen.interaction.test.tsx
// mocks the component out entirely, so nothing exercised its assign path, its
// dismissals or its error rendering.

import React, { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CccdCard } from '../upload/api'

const listCccdCards = vi.fn()
const assignCccdCard = vi.fn()

vi.mock('../upload/api', () => ({
  listCccdCards: (...args: unknown[]) => listCccdCards(...args),
  assignCccdCard: (...args: unknown[]) => assignCccdCard(...args),
  cccdCardImageUrl: (caseId: string, cardId: string, side: string) => (
    `/api/cases/${caseId}/cccd-cards/${cardId}/image/${side}`
  ),
}))

const CccdCardPicker = (await import('./CccdCardPicker')).default

function card(cardId: string): CccdCard {
  return {
    cardId,
    state: 'conflict',
    number: '',
    name: '',
    attachedPacketIndex: null,
    matchMethod: null,
    reason: 'no-number-region',
    sides: [
      { side: 'front', width: 600, height: 380 },
      { side: 'back', width: 600, height: 380 },
    ],
  } as unknown as CccdCard
}

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason?: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

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
})

function button(text: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')]
    .find(el => el.textContent?.includes(text))
  if (!found) throw new Error(`no button matching ${text}: ${host.textContent}`)
  return found as HTMLButtonElement
}

async function mount(
  onAssigned: (cards: CccdCard[]) => void = () => {},
  onCancel: () => void = () => {},
) {
  await act(async () => {
    root.render(
      <CccdCardPicker
        caseId="case-1"
        packetIndex={3}
        packetLabel="NGUYEN VAN MOT"
        onAssigned={onAssigned}
        onCancel={onCancel}
      />,
    )
  })
}

describe('CccdCardPicker', () => {
  it('hands the assign PUT\'s own card list up', async () => {
    // The parent used to learn the assignment through a second GET.
    const settled = [card('card-00'), card('card-01')]
    listCccdCards.mockResolvedValue([card('card-00')])
    assignCccdCard.mockResolvedValue({ cards: settled, cccdSummary: null })
    const onAssigned = vi.fn()
    await mount(onAssigned)

    await act(async () => { button('Gán vào gói này').click() })

    expect(assignCccdCard).toHaveBeenCalledWith('case-1', 'card-00', 3)
    expect(onAssigned).toHaveBeenCalledWith(settled)
  })

  it('refuses every dismissal while an assign is in flight', async () => {
    // One PUT rewrites up to 25 manifests, so the window is not tight. All
    // three gestures used to stay live: the assign committed anyway, and the
    // late callback closed whichever picker was open by then.
    const inFlight = deferred<{ cards: CccdCard[] }>()
    listCccdCards.mockResolvedValue([card('card-00')])
    assignCccdCard.mockReturnValue(inFlight.promise)
    const onCancel = vi.fn()
    await mount(() => {}, onCancel)

    await act(async () => { button('Gán vào gói này').click() })

    expect(button('Đóng').disabled).toBe(true)

    // Escape, at the focused element the way a browser fires it
    await act(async () => {
      document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Escape', bubbles: true, cancelable: true,
      }))
    })
    // and the backdrop
    const backdrop = host.querySelector('.cccd-picker-backdrop') as HTMLElement
    await act(async () => {
      backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }))
    })

    expect(onCancel).not.toHaveBeenCalled()

    await act(async () => { inFlight.resolve({ cards: [] }) })
  })

  it('shows a rejection under StrictMode, not a frozen dialog', async () => {
    // The suite mounted with a bare createRoot, so `mounted.current` stayed
    // true and every assertion below passed against a build the reviewer
    // never runs. React re-runs an effect setup -> cleanup -> setup on mount
    // under StrictMode and refs survive it, so a cleanup-only effect latched
    // the guard false before first paint: the rejection was swallowed, busy
    // stayed set, and all three dismissals are gated on busy.
    listCccdCards.mockResolvedValue([card('card-00')])
    assignCccdCard.mockRejectedValue(new Error('packet-already-has-card'))
    const onCancel = vi.fn()
    await act(async () => {
      root.render(
        <React.StrictMode>
          <CccdCardPicker
            caseId="case-1"
            packetIndex={3}
            packetLabel="NGUYEN VAN MOT"
            onAssigned={() => {}}
            onCancel={onCancel}
          />
        </React.StrictMode>,
      )
    })

    await act(async () => { button('Gán vào gói này').click() })

    expect(host.textContent).toContain('Gỡ ảnh cũ trước')
    expect(button('Đóng').disabled).toBe(false)
    await act(async () => { button('Đóng').click() })
    expect(onCancel).toHaveBeenCalled()
  })

  it('dismisses normally when nothing is in flight', async () => {
    listCccdCards.mockResolvedValue([card('card-00')])
    const onCancel = vi.fn()
    await mount(() => {}, onCancel)

    await act(async () => { button('Đóng').click() })
    expect(onCancel).toHaveBeenCalled()
  })

  it('says what went wrong instead of asking for an impossible retry', async () => {
    // card-has-no-image, attach-failed and reconcile-failed had no entry, so
    // all three fell to "Vui lòng thử lại" -- a retry that cannot succeed.
    for (const [code, expected] of [
      ['card-has-no-image', 'không có tệp hình'],
      ['attach-failed', 'Thử ảnh khác'],
      ['reconcile-failed', 'Tải lại trang'],
    ] as const) {
      listCccdCards.mockResolvedValue([card('card-00')])
      assignCccdCard.mockRejectedValue(new Error(code))
      await mount()
      await act(async () => { button('Gán vào gói này').click() })

      expect(host.textContent).toContain(expected)
      expect(host.textContent).not.toContain('Vui lòng thử lại')
      await act(async () => { root.unmount() })
      host.remove()
      host = document.createElement('div')
      document.body.appendChild(host)
      root = createRoot(host)
    }
  })
})
