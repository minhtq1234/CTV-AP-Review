// src/components/PacketGrid.interaction.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CtvFolder } from '../ctv/types'
import PacketGrid from './PacketGrid'

const folder: CtvFolder = {
  id: 'packet-grid-interaction',
  name: 'Synthetic reviewer',
  product: 'Synthetic product',
  status: 'pending',
  exempt: false,
  docs: [
    {
      id: 'contract', kind: 'contract', label: 'Hợp đồng',
      pages: [{ src: '/contract.svg', width: 1000, height: 1400 }],
    },
    {
      id: 'pit', kind: 'pit', label: 'Website thuế',
      pages: [{ src: '/pit.svg', width: 1000, height: 1400 }],
    },
  ],
  fields: [
    {
      key: 'name', label: 'Họ và tên', group: 'Danh tính', check: 'compare',
      kind: 'name', expected: 'Nguyen Van A',
      sources: [{
        docId: 'contract', page: 0, value: 'Nguyen Van A', confidence: 0.99,
        bbox: { x: 10, y: 20, width: 100, height: 20 },
      }],
    },
    {
      key: 'cccd', label: 'Số CCCD', group: 'Danh tính', check: 'compare',
      kind: 'text', expected: '123',
      sources: [{
        docId: 'pit', page: 0, value: '456', confidence: 0.99,
        bbox: { x: 10, y: 50, width: 100, height: 20 },
      }],
    },
  ],
}

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

function mount() {
  const opened: string[] = []
  act(() => {
    root.render(<PacketGrid folder={folder} onOpenDocument={docId => opened.push(docId)} />)
  })
  return opened
}

describe('clicking a Dạng bảng cell', () => {
  it('asks to open the document for the column the cell sits in', () => {
    const opened = mount()
    // The second field's only source is on the `pit` document, so its status
    // button sits in that column.
    const buttons = [...host.querySelectorAll('button.packet-grid-status')]
    const pitCell = buttons.find(b => b.closest('tr')?.textContent?.includes('Số CCCD'))
    expect(pitCell).toBeDefined()
    act(() => { (pitCell as HTMLButtonElement).click() })
    expect(opened).toEqual(['pit'])
  })

  it('opens the contract document from the contract column', () => {
    const opened = mount()
    const buttons = [...host.querySelectorAll('button.packet-grid-status')]
    const contractCell = buttons.find(b => b.closest('tr')?.textContent?.includes('Họ và tên'))
    act(() => { (contractCell as HTMLButtonElement).click() })
    expect(opened).toEqual(['contract'])
  })

  it('leaves a cell with no source unclickable', () => {
    mount()
    // Each field has a source on exactly one document, so the other column's
    // cell has no sourceIndex and must stay a span, never a button.
    const spans = host.querySelectorAll('span.packet-grid-status')
    expect(spans.length).toBeGreaterThan(0)
    for (const span of spans) expect(span.tagName).toBe('SPAN')
  })
})
