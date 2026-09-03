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

// The stub threads the assign PUT's own card list up, the way the real picker
// now does. `pickerResponse` is what the test wants that PUT to have returned.
let pickerResponse: CccdCard[] = []

vi.mock('./CccdCardPicker', () => ({
  default: ({ packetIndex, packetLabel, onAssigned, onCancel }: {
    packetIndex: number
    packetLabel: string
    onAssigned: (cards: CccdCard[]) => void
    onCancel: () => void
  }) => (
    <div data-testid="picker">
      <span>{`picker:${packetIndex}:${packetLabel}`}</span>
      <button type="button" onClick={() => onAssigned(pickerResponse)}>
        mock-assigned
      </button>
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

// Two sides by default: the one real case checked had 42/42 cards with both
// a front and a back, and having both is what makes the viewer trigger exist
// at all (CardThumb renders no button for a single-sided card). Tests that
// specifically want the single-sided, no-button case build their own object.
function card(cardId: string, attachedPacketIndex: number | null): CccdCard {
  return {
    cardId,
    state: attachedPacketIndex === null ? 'conflict' : 'exact',
    attachedPacketIndex,
    number: '',
    issues: [],
    sides: [
      { side: 'front', width: 1059, height: 668 },
      { side: 'back', width: 1059, height: 668 },
    ],
  }
}

const packets = [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')]

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  listCccdCards.mockReset()
  pickerResponse = []
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

function thumbButton(cardId: string): HTMLButtonElement {
  const label = `Xem cả hai mặt của ảnh CCCD ${cardId}`
  const found = host.querySelector(`button[aria-label="${label}"]`)
  if (!found) throw new Error(`no thumbnail button for ${cardId}: ${host.textContent}`)
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

  it('renders an assignment from the PUT itself, with no second GET', async () => {
    // It used to learn the assignment through a refetch, which could fail on
    // its own: the screen then kept its pre-assign rows while the server had
    // the card attached, so the row still offered `Gán thẻ` and re-picking
    // answered `packet-already-has-card` for a packet showing no card and no
    // `Gỡ`. Detach on this screen always rendered from its own PUT.
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    pickerResponse = [card('card-00', 0), card('card-09', 1)]
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    await act(async () => { button('mock-assigned').click() })

    expect(listCccdCards).toHaveBeenCalledOnce()
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

  it('leaves no in-flight window after an assignment', async () => {
    // These two assertions replace a pair of tests that held the rows on
    // screen, and the buttons disabled, while a post-assign refetch was in
    // flight. There is no such refetch now, so there is no window to guard --
    // what must hold is that the screen is immediately actionable again.
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    pickerResponse = [card('card-00', 0), card('card-09', 1)]
    await mount()
    await act(async () => { button('Gán thẻ').click() })
    await act(async () => { button('mock-assigned').click() })

    expect(host.textContent).not.toContain('Đang tải…')
    expect(button('Gỡ').disabled).toBe(false)
  })

  it('a stale load does not re-enable rows while the live case is detaching', async () => {
    const slowA = deferred<CccdCard[]>()
    listCccdCards.mockImplementation((cid: string) => (
      cid === 'case-1' ? slowA.promise : Promise.resolve([card('card-00', 0), card('card-01', 1)])
    ))
    const pending = deferred<{ cards: CccdCard[] }>()
    assignCccdCard.mockReturnValue(pending.promise)

    await render('case-1')          // A's load hangs
    await render('case-2')          // B loads and settles
    await act(async () => { button('Gỡ').click() })   // B's detach in flight
    expect(button('Gỡ').disabled).toBe(true)

    await act(async () => {         // A's abandoned load finally lands
      slowA.resolve([card('card-77', 0)])
      await slowA.promise
    })

    // B's detach is still in flight — its rows must stay disabled.
    expect(button('Gỡ').disabled).toBe(true)
  })

  // The full-size card viewer is view-only UI state that lives in the
  // presentational view (CardThumb), not the container — so opening it must
  // never touch the network, and must work for a card already attached
  // (nested inside the collapsed "Đã gán" <details>), which is the harder of
  // the two spots it appears in.
  it('opens the full-size viewer for an attached row, showing every side', async () => {
    const twoSided: CccdCard = {
      cardId: 'card-00',
      state: 'exact',
      attachedPacketIndex: 0,
      number: '',
      issues: [],
      sides: [
        { side: 'front', width: 1059, height: 668 },
        { side: 'back', width: 1059, height: 668 },
      ],
    }
    listCccdCards.mockResolvedValue([twoSided])
    await mount()
    await act(async () => { thumbButton('card-00').click() })

    const dialog = host.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    const imgs = [...(dialog?.querySelectorAll('img') ?? [])]
    const srcs = imgs.map(img => img.getAttribute('src'))
    expect(srcs).toEqual([
      '/api/cases/case-1/cccd-cards/card-00/image/front',
      '/api/cases/case-1/cccd-cards/card-00/image/back',
    ])
    // The recorded side dimensions are transposed on any case ingested before
    // fccded7 (the JPEG parser returned header order, height before width) --
    // only the image file itself knows its real size, so the viewer must not
    // assert a width/height that came from that untrustworthy manifest.
    for (const img of imgs) {
      expect(img.hasAttribute('width')).toBe(false)
      expect(img.hasAttribute('height')).toBe(false)
    }
  })

  it('also opens the full-size viewer from an unattached card row', async () => {
    listCccdCards.mockResolvedValue([card('card-09', null)])
    await mount()
    await act(async () => { thumbButton('card-09').click() })
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()
  })

  it('closes the full-size viewer on Escape, from wherever focus is', async () => {
    // Dispatched at document.activeElement, not at the dialog. The old test
    // dispatched on the dialog element, which is the one thing a browser never
    // does -- keydown fires at the focused element -- so it passed while
    // Escape was dead in Chrome from every reachable path.
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    await act(async () => { thumbButton('card-00').click() })
    const dialog = host.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog).not.toBeNull()
    // The dialog takes focus on mount, which is what makes Escape reachable.
    expect(dialog.contains(document.activeElement)).toBe(true)

    await act(async () => {
      document.activeElement!.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Escape',
        bubbles: true,
        cancelable: true,
      }))
    })
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })

  it('traps Tab inside the viewer so the Tiếp tục gate is unreachable', async () => {
    // Measured in Chrome before the trap: 70 tab stops, the dialog's own first
    // control at 51 and `Tiếp tục` -- the hard gate off this screen -- at 50.
    // Tab reached the gate behind the backdrop and activating it advanced the
    // case with cards still unassigned.
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    await act(async () => { thumbButton('card-00').click() })
    const dialog = host.querySelector('[role="dialog"]') as HTMLElement

    const inside = Array.from(
      dialog.querySelectorAll<HTMLElement>('button:not([disabled])'),
    )
    expect(inside.length).toBeGreaterThan(0)
    inside[inside.length - 1].focus()

    const event = new KeyboardEvent('keydown', {
      key: 'Tab', bubbles: true, cancelable: true,
    })
    await act(async () => { document.activeElement!.dispatchEvent(event) })

    expect(event.defaultPrevented).toBe(true)
    expect(dialog.contains(document.activeElement)).toBe(true)
  })

  it('gates Tiếp tục on busy like every other control', async () => {
    // It was the only live control mid-mutation, and leaving then defeats the
    // single getCase that continueFromCccdReview does because a mutation moves
    // the summary and the per-packet rollups.
    const pending = deferred<{ cards: CccdCard[] }>()
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    assignCccdCard.mockReturnValue(pending.promise)

    await act(async () => { button('Gỡ').click() })
    expect(button('Tiếp tục').disabled).toBe(true)

    await act(async () => { pending.resolve({ cards: [] }) })
  })

  it('does not tell the reviewer to use a row that is not on the screen', async () => {
    // Every packet has its card and one orphan remains -- the shape of the
    // 41-packet July submission. The reassurance used to be suppressed (it was
    // gated on needsAction, which counts orphan CARD rows too) and the orphan
    // tile pointed at a "gói cần thẻ" row that does not exist.
    listCccdCards.mockResolvedValue([
      card('card-00', 0), card('card-01', 1), card('card-02', 2),
      card('card-orphan', null),
    ])
    await mount()

    expect(host.textContent).toContain('Mọi gói đều đã có thẻ CCCD.')
    expect(host.textContent).toContain('gỡ thẻ của một gói trước khi gán')
    expect(host.textContent).not.toContain('Gán từ dòng của gói cần thẻ.')
  })

  it('closes the full-size viewer on a backdrop click', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    await act(async () => { thumbButton('card-00').click() })
    const backdrop = host.querySelector('.cccd-picker-backdrop') as HTMLElement
    expect(backdrop).not.toBeNull()

    await act(async () => {
      backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    })
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })

  it('opening the full-size viewer makes no new list or assign call', async () => {
    listCccdCards.mockResolvedValue([card('card-00', 0)])
    await mount()
    expect(listCccdCards).toHaveBeenCalledTimes(1)
    expect(assignCccdCard).not.toHaveBeenCalled()

    await act(async () => { thumbButton('card-00').click() })

    expect(listCccdCards).toHaveBeenCalledTimes(1)
    expect(assignCccdCard).not.toHaveBeenCalled()
  })

  // The one most likely to regress: a single-sided card has no back to
  // reveal, so it must render no clickable trigger at all -- just the image.
  it('renders no viewer button for a single-sided card, but does for a two-sided one', async () => {
    const singleSided: CccdCard = {
      cardId: 'card-00',
      state: 'exact',
      attachedPacketIndex: 0,
      number: '',
      issues: [],
      sides: [{ side: 'front', width: 1059, height: 668 }],
    }
    listCccdCards.mockResolvedValue([singleSided, card('card-01', 1)])
    await mount()

    expect(host.querySelector('button[aria-label="Xem cả hai mặt của ảnh CCCD card-00"]')).toBeNull()
    expect(host.querySelector('button[aria-label="Xem cả hai mặt của ảnh CCCD card-01"]')).not.toBeNull()
    // The single-sided card's image still renders, just not as a button.
    expect(host.querySelector('img[alt="Ảnh CCCD card-00"]')).not.toBeNull()
  })
})
