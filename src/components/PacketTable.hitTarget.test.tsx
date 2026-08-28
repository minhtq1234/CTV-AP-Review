// src/components/PacketTable.hitTarget.test.tsx
// @vitest-environment jsdom
//
// The hit-target contract for the CHỨNG TỪ preview button: its rendered box
// should equal its <td>'s box, padding included, not just wrap the pill's
// natural size -- otherwise a click in what looks like the cell but isn't
// the button falls through to the row's own onClick (wrong-action, not
// no-action). jsdom has no layout engine, so this cannot assert real pixel
// geometry -- it asserts the CSS relationship the fix relies on (padding
// moved from the cell to the button, the button sized to 100% of its parent
// under border-box sizing), read from the real stylesheet, guarding against
// a future style edit silently undoing it.
//
// That relationship does NOT fully deliver box equality in every row, and a
// jsdom test cannot see the gap because jsdom never computes real layout.
// Measured in a real browser: width matches on every row, and height
// matches when THIS cell's own content is what makes the row tall (the
// "Thiếu: ..." case) -- but when a SIBLING cell (Kết quả FA's second
// .pt-sub line) is what stretches the row instead, the button stays sized
// to its own single-line content and falls ~13-16.5px short of the row's
// real height (3 of 41 rows in the case checked). See the batch report for
// the full measurements; no fix for that residual gap is applied yet.

import { readFileSync } from 'node:fs'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { PacketMeta, PacketReview } from '../upload/api'
import PacketTable from './PacketTable'

const styles = readFileSync('src/styles.css', 'utf8')

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

// A row whose "Kết quả FA" cell renders a second .pt-sub line ("N/6 đã xem"),
// matching the real-browser scenario this was checked against (see the file
// header) -- kept here even though jsdom's lack of layout means this
// particular test can't itself tell that row apart from a plain one.
const tallerRowPacket = packet(0, 'Synthetic Taller Row', {
  review: {
    done: false,
    fields: { a: { seen: true, flag: null }, b: { seen: true, flag: null } },
    rejection: null,
  },
})

let host: HTMLDivElement
let root: Root
let styleElement: HTMLStyleElement

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  styleElement = document.createElement('style')
  styleElement.textContent = styles
  document.head.append(styleElement)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  styleElement.remove()
  vi.unstubAllGlobals()
})

describe('PacketTable CHỨNG TỪ hit-target contract', () => {
  it("gives the preview button the padding its <td> gave up, sized to fill it, box included", async () => {
    await act(async () => {
      root.render(
        <PacketTable
          packets={[tallerRowPacket]}
          onOpenPacket={() => {}}
          onPreviewDocs={() => {}}
        />,
      )
    })

    const cell = host.querySelector('td.pt-docs') as HTMLElement
    const button = host.querySelector('button.pt-docs-preview') as HTMLElement
    // A plain, non-interactive cell in the SAME row still carries the base
    // `.packet-table td` padding -- read from it rather than hard-coding
    // "9px 10px" a second time, so this test can't silently drift from the
    // rule it is checking.
    const plainCell = host.querySelector('td.pt-stt') as HTMLElement
    expect(cell).not.toBeNull()
    expect(button).not.toBeNull()
    expect(plainCell).not.toBeNull()

    const cellStyle = getComputedStyle(cell)
    const buttonStyle = getComputedStyle(button)
    const basePadding = getComputedStyle(plainCell)

    // The cell gave its padding away -- it must not also keep it, or the
    // button (sized to the cell's now-smaller content box) would fall short
    // of the cell's real edges again.
    expect([cellStyle.paddingTop, cellStyle.paddingRight, cellStyle.paddingBottom, cellStyle.paddingLeft])
      .toEqual(['0px', '0px', '0px', '0px'])

    // The button holds exactly the padding an ordinary cell would have had.
    expect(buttonStyle.paddingTop).toBe(basePadding.paddingTop)
    expect(buttonStyle.paddingRight).toBe(basePadding.paddingRight)
    expect(buttonStyle.paddingBottom).toBe(basePadding.paddingBottom)
    expect(buttonStyle.paddingLeft).toBe(basePadding.paddingLeft)
    expect(basePadding.paddingTop).not.toBe('0px') // guards against a vacuous pass

    // border-box + 100%/100% on the cell's only child is what makes that
    // padded border-box equal the cell's own content box (jsdom cannot
    // resolve the percentages into pixels itself -- that part is confirmed
    // in a real browser, see the batch report).
    expect(buttonStyle.boxSizing).toBe('border-box')
    expect(buttonStyle.width).toBe('100%')
    expect(buttonStyle.height).toBe('100%')
    expect(buttonStyle.display).toBe('block')

    // Sanity: this row really is the taller-sibling scenario, not an
    // accidental single-line one.
    expect(host.querySelector('.pt-sub')?.textContent).toContain('đã xem')
  })
})
