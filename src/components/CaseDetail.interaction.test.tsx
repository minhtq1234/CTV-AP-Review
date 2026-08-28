// src/components/CaseDetail.interaction.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CaseDetail as CaseDetailT, PacketMeta, PacketReview } from '../upload/api'
import type { CtvFolder } from '../ctv/types'

const fetchPacketManifest = vi.fn()

vi.mock('../upload/api', async () => {
  const actual = await vi.importActual<typeof import('../upload/api')>('../upload/api')
  return {
    ...actual,
    fetchPacketManifest: (...args: unknown[]) => fetchPacketManifest(...args),
  }
})

const CaseDetail = (await import('./CaseDetail')).default

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

function detailFor(): CaseDetailT {
  return {
    id: 'case-1',
    name: 'Synthetic Case',
    createdAt: null,
    status: 'ready',
    pdfName: 'packet.pdf',
    rosterName: 'roster.xlsx',
    cccdName: null,
    cccdSummary: null,
    summary: { found: 2, roster_n: 2, matched: 2, auto_merged: 0 },
    error: null,
    packets,
    progress: { done: 0, total: 2, flagged: 0 },
  }
}

function folder(): CtvFolder {
  return {
    id: 'folder',
    name: 'Synthetic',
    product: 'Synthetic Product',
    status: 'pending',
    exempt: false,
    docs: [{
      id: 'doc',
      kind: 'contract',
      label: 'Synthetic document',
      pages: [{ src: '/doc.svg', width: 1000, height: 1400 }],
    }],
    fields: [],
  }
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 0
  })
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  HTMLElement.prototype.scrollIntoView = vi.fn()
  HTMLElement.prototype.scrollTo = vi.fn()
  fetchPacketManifest.mockReset()
  fetchPacketManifest.mockResolvedValue(folder())
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

async function mount(onOpenPacket: (index: number) => void) {
  await act(async () => {
    root.render(
      <CaseDetail
        detail={detailFor()}
        onOpenPacket={onOpenPacket}
        onBack={() => {}}
        onExport={() => {}}
      />,
    )
  })
}

function findButton(text: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')].find(el => el.textContent === text)
  if (!found) throw new Error(`no button matching ${text}: ${host.textContent}`)
  return found as HTMLButtonElement
}

describe('CaseDetail packet-docs preview wiring', () => {
  it('opens a dialog for the row that was clicked, fetching that packet\'s manifest', async () => {
    const onOpenPacket = vi.fn()
    await mount(onOpenPacket)

    const preview = host.querySelector(
      'button.pt-docs-preview[aria-label="Xem chứng từ — Synthetic B"]',
    ) as HTMLButtonElement
    expect(preview).not.toBeNull()

    await act(async () => { preview.click() })

    expect(fetchPacketManifest).toHaveBeenCalledWith('case-1', 1)
    const dialog = host.querySelector('[role="dialog"]')
    expect(dialog).not.toBeNull()
    expect(dialog?.textContent).toContain('Synthetic B')
    expect(onOpenPacket).not.toHaveBeenCalled()
  })

  it('"Mở gói hồ sơ" reuses CaseDetail\'s own onOpenPacket and closes the dialog', async () => {
    const onOpenPacket = vi.fn()
    await mount(onOpenPacket)

    await act(async () => {
      (host.querySelector(
        'button.pt-docs-preview[aria-label="Xem chứng từ — Synthetic B"]',
      ) as HTMLButtonElement).click()
    })
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()

    await act(async () => { findButton('Mở gói hồ sơ').click() })

    expect(onOpenPacket).toHaveBeenCalledOnce()
    expect(onOpenPacket).toHaveBeenCalledWith(1)
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })

  it('closing the dialog leaves onOpenPacket untouched, and a later row click still works', async () => {
    const onOpenPacket = vi.fn()
    await mount(onOpenPacket)

    await act(async () => {
      (host.querySelector(
        'button.pt-docs-preview[aria-label="Xem chứng từ — Synthetic A"]',
      ) as HTMLButtonElement).click()
    })
    await act(async () => { findButton('Đóng').click() })
    expect(host.querySelector('[role="dialog"]')).toBeNull()
    expect(onOpenPacket).not.toHaveBeenCalled()

    const row = host.querySelectorAll('tr.packet-table-row')[0] as HTMLElement
    await act(async () => { row.click() })
    expect(onOpenPacket).toHaveBeenCalledWith(0)
  })

  it('a direct row click opens the packet without ever fetching a preview manifest', async () => {
    const onOpenPacket = vi.fn()
    await mount(onOpenPacket)

    const row = host.querySelectorAll('tr.packet-table-row')[0] as HTMLElement
    await act(async () => { row.click() })

    expect(onOpenPacket).toHaveBeenCalledWith(0)
    expect(fetchPacketManifest).not.toHaveBeenCalled()
    expect(host.querySelector('[role="dialog"]')).toBeNull()
  })
})
