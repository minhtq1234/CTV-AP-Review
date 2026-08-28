// src/components/PacketTable.interaction.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PacketMeta, PacketReview } from '../upload/api'
import PacketTable from './PacketTable'

function review(): PacketReview {
  return { done: false, fields: {}, rejection: null }
}

function packet(index: number, name: string, overrides: Partial<PacketMeta> = {}): PacketMeta {
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
    review: review(),
    reviewFieldCount: 6,
    documents: { span: 6, missing: [] },
    ...overrides,
  }
}

const packets = [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')]

let host: HTMLDivElement
let root: Root

beforeEach(() => {
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

async function render(
  onOpenPacket: (index: number) => void,
  onPreviewDocs?: (index: number) => void,
) {
  await act(async () => {
    root.render(
      <PacketTable packets={packets} onOpenPacket={onOpenPacket} onPreviewDocs={onPreviewDocs} />,
    )
  })
}

function previewButton(name: string): HTMLButtonElement {
  const found = host.querySelector(`button.pt-docs-preview[aria-label="Xem chứng từ — ${name}"]`)
  if (!found) throw new Error(`no preview button for ${name}: ${host.innerHTML}`)
  return found as HTMLButtonElement
}

describe('PacketTable CHỨNG TỪ preview button', () => {
  // The one most likely to regress, and the whole point of the button's own
  // stopPropagation: without it, this click would bubble to the row's onClick
  // and ALSO navigate into the full reviewer.
  it('clicking the button calls onPreviewDocs and does not call onOpenPacket', async () => {
    const onOpenPacket = vi.fn()
    const onPreviewDocs = vi.fn()
    await render(onOpenPacket, onPreviewDocs)

    await act(async () => { previewButton('Synthetic B').click() })

    expect(onPreviewDocs).toHaveBeenCalledOnce()
    expect(onPreviewDocs).toHaveBeenCalledWith(1)
    expect(onOpenPacket).not.toHaveBeenCalled()
  })

  // The keyboard path bubbles a different event (keydown, not click) to a
  // different handler (the row's onKeyDown) -- it needs its own guard, and
  // its own proof the guard exists.
  it('activating the button with Enter does not bubble to the row and open it', async () => {
    const onOpenPacket = vi.fn()
    const onPreviewDocs = vi.fn()
    await render(onOpenPacket, onPreviewDocs)

    await act(async () => {
      previewButton('Synthetic A').dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Enter',
        bubbles: true,
        cancelable: true,
      }))
    })

    expect(onOpenPacket).not.toHaveBeenCalled()
  })

  it('activating the button with Space does not bubble to the row and open it', async () => {
    const onOpenPacket = vi.fn()
    const onPreviewDocs = vi.fn()
    await render(onOpenPacket, onPreviewDocs)

    await act(async () => {
      previewButton('Synthetic A').dispatchEvent(new KeyboardEvent('keydown', {
        key: ' ',
        bubbles: true,
        cancelable: true,
      }))
    })

    expect(onOpenPacket).not.toHaveBeenCalled()
  })

  it('clicking the row elsewhere still opens the packet, unaffected by the button', async () => {
    const onOpenPacket = vi.fn()
    const onPreviewDocs = vi.fn()
    await render(onOpenPacket, onPreviewDocs)

    const name = host.querySelector('.pt-name-text') as HTMLElement
    expect(name.textContent).toBe('Synthetic A')
    await act(async () => { name.click() })

    expect(onOpenPacket).toHaveBeenCalledWith(0)
    expect(onPreviewDocs).not.toHaveBeenCalled()
  })

  it('renders no button, and the row click still works, when onPreviewDocs is absent', async () => {
    const onOpenPacket = vi.fn()
    await render(onOpenPacket, undefined)

    expect(host.querySelector('.pt-docs-preview')).toBeNull()

    const row = host.querySelectorAll('tr.packet-table-row')[1]
    await act(async () => { (row as HTMLElement).click() })
    expect(onOpenPacket).toHaveBeenCalledWith(1)
  })
})
