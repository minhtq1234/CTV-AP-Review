// src/components/PacketDocsDialog.interaction.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CtvFolder, EvidenceKind } from '../ctv/types'

const fetchPacketManifest = vi.fn()

vi.mock('../upload/api', () => ({
  fetchPacketManifest: (...args: unknown[]) => fetchPacketManifest(...args),
}))

const PacketDocsDialog = (await import('./PacketDocsDialog')).default

function folder(overrides: Partial<CtvFolder> = {}): CtvFolder {
  return {
    id: 'synthetic-folder',
    name: 'Synthetic',
    product: 'Synthetic Product',
    status: 'pending',
    exempt: false,
    docs: [
      {
        id: 'id_front',
        kind: 'id_front',
        label: 'CCCD mặt trước',
        pages: [{ src: '/front.svg', width: 1000, height: 700 }],
      },
      {
        id: 'contract',
        kind: 'contract',
        label: 'Hợp đồng',
        pages: [
          { src: '/contract-1.svg', width: 1000, height: 1400 },
          { src: '/contract-2.svg', width: 1000, height: 1400 },
        ],
      },
    ],
    fields: [],
    ...overrides,
  }
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  // EvidenceViewer's overview-mode scroll-to-top effect needs these, exactly
  // like FolderReview.interaction.test.tsx's own setup (jsdom 24 has neither).
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 0
  })
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  HTMLElement.prototype.scrollIntoView = vi.fn()
  HTMLElement.prototype.scrollTo = vi.fn()
  fetchPacketManifest.mockReset()
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>(res => { resolve = res })
  return { promise, resolve }
}

interface RenderProps {
  caseId: string
  packetIndex: number
  packetName: string
  onClose: () => void
  onOpenPacket?: (index: number) => void
  initialDocKind?: EvidenceKind
  focus?: { page: number; bbox: { x: number; y: number; width: number; height: number } | null } | null
}

const defaultProps = (): RenderProps => ({
  caseId: 'case-1',
  packetIndex: 0,
  packetName: 'Synthetic Packet',
  onClose: () => {},
  onOpenPacket: () => {},
})

async function render(overrides: Partial<RenderProps> = {}) {
  const props = { ...defaultProps(), ...overrides }
  await act(async () => {
    root.render(
      <PacketDocsDialog
        caseId={props.caseId}
        packetIndex={props.packetIndex}
        packetName={props.packetName}
        onClose={props.onClose}
        onOpenPacket={props.onOpenPacket}
        initialDocKind={props.initialDocKind}
        focus={props.focus}
      />,
    )
  })
  return props
}

function findButton(text: string): HTMLButtonElement {
  const found = [...host.querySelectorAll('button')].find(el => el.textContent === text)
  if (!found) throw new Error(`no button matching ${text}: ${host.textContent}`)
  return found as HTMLButtonElement
}

describe('PacketDocsDialog', () => {
  it('fetches the manifest for exactly the case/packet it was given', async () => {
    const pending = deferred<CtvFolder>()
    fetchPacketManifest.mockReturnValue(pending.promise)
    await render({ caseId: 'case-9', packetIndex: 3 })
    expect(fetchPacketManifest).toHaveBeenCalledOnce()
    expect(fetchPacketManifest).toHaveBeenCalledWith('case-9', 3)
    expect(host.textContent).toContain('Đang tải…')
  })

  it('renders every document label from the loaded manifest', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    await render()
    expect(host.textContent).toContain('CCCD mặt trước')
    expect(host.textContent).toContain('Hợp đồng')
  })

  // overviewMode is permanent in this dialog, and lock view only ever gates
  // behaviour overview mode already skips (EvidenceViewer's own
  // hideLockControl doc comment) -- so this dialog passes hideLockControl,
  // and the toolbar should never offer a lock toggle that would do nothing.
  it('never offers the lock-view toggle, unlike the full reviewer', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    await render()
    expect(host.querySelector('[aria-label="Khoá khung nhìn"]')).toBeNull()
    // Every other viewer tool stays -- this isn't a viewer stripped down,
    // just the one control with nothing to do here.
    expect(host.querySelector('[aria-label="Vừa khung"]')).not.toBeNull()
    expect(host.querySelector('[aria-label="Di chuyển (pan)"]')).not.toBeNull()
  })

  it('titles the dialog with the given packet name', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    await render({ packetName: 'Nguyễn Văn A' })
    const dialog = host.querySelector('[role="dialog"]') as HTMLElement
    expect(dialog).not.toBeNull()
    expect(dialog.getAttribute('aria-modal')).toBe('true')
    expect(dialog.querySelector('h2')?.textContent).toContain('Nguyễn Văn A')
  })

  it('shows a retryable error on a failed fetch, and refetches on retry', async () => {
    fetchPacketManifest.mockRejectedValueOnce(new Error('boom'))
    fetchPacketManifest.mockResolvedValueOnce(folder())
    await render()
    expect(host.textContent).toContain('Không tải được chứng từ của gói này.')
    expect(host.textContent).not.toContain('CCCD mặt trước')

    await act(async () => { findButton('Thử lại').click() })

    expect(fetchPacketManifest).toHaveBeenCalledTimes(2)
    expect(host.textContent).toContain('CCCD mặt trước')
    expect(host.textContent).not.toContain('Không tải được chứng từ của gói này.')
  })

  it('closes on Escape', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    const onClose = vi.fn()
    await render({ onClose })
    const dialog = host.querySelector('[role="dialog"]') as HTMLElement

    await act(async () => {
      dialog.dispatchEvent(new KeyboardEvent('keydown', {
        key: 'Escape',
        bubbles: true,
        cancelable: true,
      }))
    })

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes on a backdrop click, but not on a click inside the dialog panel', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    const onClose = vi.fn()
    await render({ onClose })
    const dialogPanel = host.querySelector('.packet-docs-dialog') as HTMLElement
    const backdrop = host.querySelector('.packet-docs-backdrop') as HTMLElement

    await act(async () => {
      dialogPanel.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    })
    expect(onClose).not.toHaveBeenCalled()

    await act(async () => {
      backdrop.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true }))
    })
    expect(onClose).toHaveBeenCalledOnce()
  })

  it('closes via the explicit "Đóng" button', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    const onClose = vi.fn()
    await render({ onClose })

    await act(async () => { findButton('Đóng').click() })

    expect(onClose).toHaveBeenCalledOnce()
  })

  it('"Mở gói hồ sơ" calls onOpenPacket with this dialog\'s own packet index', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    const onOpenPacket = vi.fn()
    await render({ packetIndex: 7, onOpenPacket })

    await act(async () => { findButton('Mở gói hồ sơ').click() })

    expect(onOpenPacket).toHaveBeenCalledOnce()
    expect(onOpenPacket).toHaveBeenCalledWith(7)
  })

  it('offers "Mở gói hồ sơ" even while the manifest is still loading or failed to load', async () => {
    fetchPacketManifest.mockReturnValue(deferred<CtvFolder>().promise)
    const onOpenPacket = vi.fn()
    await render({ packetIndex: 2, onOpenPacket })

    await act(async () => { findButton('Mở gói hồ sơ').click() })

    expect(onOpenPacket).toHaveBeenCalledWith(2)
  })

  // The in-flight-fetch guard (liveKeyRef), mirroring CccdReviewScreen's own
  // liveCaseIdRef: a response for a packet the dialog has moved away from
  // must not land, even though the dialog was never unmounted in between.
  it('drops a manifest response for a packet/case it has moved away from', async () => {
    const first = deferred<CtvFolder>()
    fetchPacketManifest.mockImplementation((caseId: string, index: number) => (
      caseId === 'case-1' && index === 0
        ? first.promise
        : Promise.resolve(folder({
          docs: [{
            id: 'other',
            kind: 'contract',
            label: 'Other packet doc',
            pages: [{ src: '/other.svg', width: 1000, height: 1400 }],
          }],
        }))
    ))

    await render({ caseId: 'case-1', packetIndex: 0 })
    await render({ caseId: 'case-1', packetIndex: 1 })
    expect(host.textContent).toContain('Other packet doc')

    await act(async () => {
      first.resolve(folder())
      await first.promise
    })

    expect(host.textContent).toContain('Other packet doc')
    expect(host.textContent).not.toContain('CCCD mặt trước')
  })

  it('shows an explicit empty state for a packet with no documents, instead of a blank panel', async () => {
    fetchPacketManifest.mockResolvedValue(folder({ docs: [] }))
    await render()
    expect(host.textContent).toContain('Gói này chưa có chứng từ nào.')
  })

  it('opens on the requested document kind rather than the first', async () => {
    // The fixture's first doc is the CCCD front; ask for the contract and
    // assert the viewer starts there instead.
    fetchPacketManifest.mockResolvedValue(folder())
    await render({ initialDocKind: 'contract' })
    const active = host.querySelector('.ev-tab.on')
    expect(active?.textContent).toContain('Hợp đồng')
  })

  it('falls back to the first document when that kind is not in this packet', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    await render({ initialDocKind: 'appendix' })   // fixture has no appendix
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()
    const active = host.querySelector('.ev-tab.on')
    expect(active?.textContent).toContain('CCCD mặt trước')
  })

  it('omits the open-packet button when no handler is given', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    await render({ onOpenPacket: undefined })
    const buttons = [...host.querySelectorAll('button')].map(b => b.textContent)
    expect(buttons.some(t => t?.includes('Mở gói hồ sơ'))).toBe(false)
  })

  it('outlines the box the criterion pointed at', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    await render({
      initialDocKind: 'contract',
      focus: { page: 0, bbox: { x: 100, y: 200, width: 300, height: 120 } },
    })

    expect(host.querySelector('.document-focus-anchor')).not.toBeNull()
  })

  it('does not autofocus: the page is outlined, never scrolled to', async () => {
    // ver-3 scope §2 decided this popup must not autofocus. Overview mode
    // conflated the outline with the jump; only the jump stays disabled.
    const scrollIntoView = vi.fn()
    HTMLElement.prototype.scrollIntoView = scrollIntoView
    fetchPacketManifest.mockResolvedValue(folder())

    await render({
      initialDocKind: 'contract',
      focus: { page: 0, bbox: { x: 100, y: 200, width: 300, height: 120 } },
    })

    expect(scrollIntoView).not.toHaveBeenCalled()
  })

  it('opens on the page the criterion named even with no box', async () => {
    fetchPacketManifest.mockResolvedValue(folder())
    await render({ initialDocKind: 'contract', focus: { page: 1, bbox: null } })

    expect(host.querySelector('.document-focus-anchor')).toBeNull()
    expect(host.querySelector('[role="dialog"]')).not.toBeNull()
  })
})
