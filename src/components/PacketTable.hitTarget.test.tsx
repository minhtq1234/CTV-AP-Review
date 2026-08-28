// src/components/PacketTable.hitTarget.test.tsx
// @vitest-environment jsdom
//
// The hit-target contract for the CHỨNG TỪ preview button: a click anywhere
// in the cell -- padding included -- must open the preview popup, not fall
// through to the row's own onClick (which navigates into the full reviewer;
// wrong-action-on-misclick, not no-action-on-misclick).
//
// An earlier version tried to deliver that by sizing the button itself to
// the cell's box (width/height:100%, box-sizing:border-box, the <td>'s
// padding moved onto the button). Measured in a real browser against a real
// case, that worked for width on every row, and for height only when the
// docs cell's own content was what made the row tall -- when a SIBLING cell
// did instead (Kết quả FA's second .pt-sub line, on an otherwise
// single-line docs cell), the button stayed sized to its own content and
// left a ~13-16.5px dead strip (3 of 41 rows) where a click still fell
// through to the row. jsdom has no layout engine, so that gap was never
// visible to a jsdom test in the first place -- see git history for the
// CSS-relationship test this file used to have, which pinned the wrong
// mechanism.
//
// The actual fix moved the click handler onto the <td> itself (see
// PacketTable.tsx): a click event bubbles to whatever DOM element it lands
// on and up from there regardless of any descendant's box geometry, so the
// <td> catches everything the button's own (possibly smaller) box misses.
// That IS testable without layout: dispatching a click directly on the
// <td> element -- bypassing the button entirely -- is exactly what a real
// click in that dead strip would also target, since nothing else occupies
// that space.

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PacketMeta, PacketReview } from '../upload/api'
import PacketTable from './PacketTable'

function packet(index: number, name: string, overrides: Partial<PacketMeta> = {}): PacketMeta {
  const review: PacketReview = { done: false, fields: {}, rejection: null }
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
    review,
    reviewFieldCount: 6,
    documents: { span: 6, missing: [] },
    ...overrides,
  }
}

// The same scenario that showed the gap: a single-line docs cell next to a
// two-line "Kết quả FA" cell ("Đang xem" / "N/6 đã xem"), so the row is
// taller than the docs cell's own content -- the sibling-driven case the
// button's own box never covered.
const tallerRowPacket = packet(0, 'Synthetic Taller Row', {
  review: {
    done: false,
    fields: { a: { seen: true, flag: null }, b: { seen: true, flag: null } },
    rejection: null,
  },
})

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

describe('PacketTable CHỨNG TỪ hit-target contract', () => {
  it('a click on the <td> itself -- not the button -- opens the preview, not the row', async () => {
    const onOpenPacket = vi.fn()
    const onPreviewDocs = vi.fn()
    await act(async () => {
      root.render(
        <PacketTable
          packets={[tallerRowPacket]}
          onOpenPacket={onOpenPacket}
          onPreviewDocs={onPreviewDocs}
        />,
      )
    })

    // Sanity: this really is the taller-sibling row, not an accidental
    // single-line one -- otherwise this test would prove nothing new.
    expect(host.querySelector('.pt-sub')?.textContent).toContain('đã xem')

    const cell = host.querySelector('td.pt-docs') as HTMLElement
    expect(cell.contains(host.querySelector('button.pt-docs-preview'))).toBe(true)
    // Dispatched on the <td> directly: jsdom cannot aim a click at real
    // coordinates, but a click landing anywhere in the cell that isn't on
    // the (smaller) button targets the <td> exactly like this one does.
    await act(async () => { cell.click() })

    expect(onPreviewDocs).toHaveBeenCalledOnce()
    expect(onPreviewDocs).toHaveBeenCalledWith(0)
    expect(onOpenPacket).not.toHaveBeenCalled()
  })

  it('clicking the button does not also fire the <td>\'s own handler underneath it', async () => {
    const onOpenPacket = vi.fn()
    const onPreviewDocs = vi.fn()
    await act(async () => {
      root.render(
        <PacketTable
          packets={[tallerRowPacket]}
          onOpenPacket={onOpenPacket}
          onPreviewDocs={onPreviewDocs}
        />,
      )
    })

    const button = host.querySelector('button.pt-docs-preview') as HTMLButtonElement
    await act(async () => { button.click() })

    // Exactly once: the button's own stopPropagation must keep this click
    // from also reaching the <td>'s handler it sits inside.
    expect(onPreviewDocs).toHaveBeenCalledOnce()
    expect(onOpenPacket).not.toHaveBeenCalled()
  })

  it('renders the <td> with no click handler of its own when onPreviewDocs is absent', async () => {
    const onOpenPacket = vi.fn()
    await act(async () => {
      root.render(
        <PacketTable packets={[tallerRowPacket]} onOpenPacket={onOpenPacket} />,
      )
    })

    const cell = host.querySelector('td.pt-docs') as HTMLElement
    expect(cell.className).toBe('pt-docs')
    // With no handler of the <td>'s own, a click there has nothing to stop
    // it, and reaches the row exactly as it always has.
    await act(async () => { cell.click() })
    expect(onOpenPacket).toHaveBeenCalledWith(0)
  })
})
