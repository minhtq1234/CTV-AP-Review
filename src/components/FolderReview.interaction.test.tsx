// @vitest-environment jsdom

import { readFileSync } from 'node:fs'
import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CtvFolder } from '../ctv/types'
import type { PacketReview } from '../upload/api'
import FolderFieldsPanel from './FolderFieldsPanel'
import FolderReview from './FolderReview'

const styles = readFileSync('src/styles.css', 'utf8')

const folder: CtvFolder = {
  id: 'interaction-folder',
  name: 'Interaction CTV',
  product: 'Synthetic Product',
  status: 'pending',
  exempt: false,
  docs: [
    {
      id: 'contract',
      kind: 'contract',
      label: 'Synthetic contract',
      pages: [{ src: '/contract.svg', width: 1000, height: 1400 }],
    },
    {
      id: 'appendix',
      kind: 'appendix',
      label: 'Synthetic appendix',
      pages: [{ src: '/appendix.svg', width: 1000, height: 1400 }],
    },
  ],
  fields: [{
    key: 'field-a',
    label: 'Trường mẫu',
    group: 'Danh tính',
    check: 'compare',
    kind: 'text',
    expected: 'Giá trị mẫu',
    sources: [{
      docId: 'contract',
      page: 0,
      value: 'Giá trị mẫu',
      bbox: { x: 100, y: 100, width: 200, height: 40 },
      confidence: 0.99,
    }],
  }],
}

const emptyReview: PacketReview = { done: false, fields: {}, rejection: null }

let root: Root
let container: HTMLDivElement
let styleElement: HTMLStyleElement

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 0
  })
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  HTMLElement.prototype.scrollIntoView = () => undefined
  styleElement = document.createElement('style')
  styleElement.textContent = styles
  document.head.append(styleElement)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  styleElement.remove()
  vi.unstubAllGlobals()
})

const renderReview = (review = emptyReview) => {
  const onReview = vi.fn()
  act(() => {
    root.render(
      <FolderReview
        folder={folder}
        review={review}
        onReview={onReview}
        onCommitReview={async () => undefined}
      />,
    )
  })
  return onReview
}

const press = (key: string) => {
  act(() => {
    document.body.dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  })
}

const click = (element: Element) => {
  act(() => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

describe('FolderReview mounted Overview interactions', () => {
  it('opens on Overview without publishing a field review and guards field shortcuts', () => {
    const onReview = renderReview()

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(container.querySelector('.roster-callout')).toBeNull()
    expect(onReview).not.toHaveBeenCalled()

    press('ArrowRight')
    press('f')

    expect(onReview).not.toHaveBeenCalled()
    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
  })

  it('moves from Overview to a field and returns to Overview with vertical arrows', () => {
    const onReview = renderReview()

    press('ArrowDown')

    expect(container.querySelector('.cfield.sel')?.textContent).toContain('Trường mẫu')
    expect(onReview).toHaveBeenCalledWith({
      done: false,
      fields: { 'field-a': { seen: true, flag: null } },
      rejection: null,
    })

    press('ArrowUp')

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(container.querySelector('.cfield.sel')).toBeNull()
    expect(container.querySelector('.roster-callout')).toBeNull()
    expect(onReview).toHaveBeenCalledTimes(1)
  })

  it('switches document tabs from Overview without focusing a field', () => {
    const onReview = renderReview()
    const appendixTab = Array.from(container.querySelectorAll('.ev-tab'))
      .find(button => button.textContent === 'Synthetic appendix')

    expect(appendixTab).toBeDefined()
    click(appendixTab!)

    expect(container.querySelector('img')?.getAttribute('src')).toBe('/appendix.svg')
    expect(container.querySelector('.roster-callout')).toBeNull()
    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(onReview).not.toHaveBeenCalled()
  })

  it('selects Overview before opening packet rejection actions', () => {
    const onReview = renderReview()
    press('ArrowDown')

    const rejectionButton = Array.from(container.querySelectorAll('button'))
      .find(button => button.textContent === 'Từ chối hồ sơ')

    expect(rejectionButton).toBeDefined()
    click(rejectionButton!)

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(container.querySelector('.packet-rejection-dialog')).not.toBeNull()
    expect(onReview).toHaveBeenCalledTimes(1)
  })

  it('selects Overview before editing a persisted packet rejection', () => {
    const onReview = renderReview({
      done: true,
      fields: { 'field-a': { seen: true, flag: null } },
      rejection: { reasons: ['missing_documents'], note: 'Synthetic note' },
    })
    press('ArrowDown')

    const editButton = Array.from(container.querySelectorAll('button'))
      .find(button => button.textContent === 'Sửa lý do')

    expect(editButton).toBeDefined()
    click(editButton!)

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(container.querySelector('.packet-rejection-dialog h2')?.textContent)
      .toBe('Sửa lý do từ chối')
    expect(onReview).not.toHaveBeenCalled()
  })

  it('keeps the rejection summary compact inside Overview', () => {
    act(() => {
      root.render(
        <FolderFieldsPanel
          ranked={[]}
          selection={{ kind: 'overview' }}
          onSelectOverview={() => undefined}
          onSelectField={() => undefined}
          review={{
            done: true,
            fields: {},
            rejection: { reasons: ['missing_documents'], note: 'Synthetic note' },
          }}
          onToggleFlag={() => undefined}
          onOpenPacketRejection={() => undefined}
        />,
      )
    })

    const summary = container.querySelector('.overview-row .packet-rejection-summary')
    expect(summary).not.toBeNull()
    const computed = getComputedStyle(summary!)
    expect(computed.marginTop).toBe('10px')
    expect(computed.marginRight).toBe('0px')
    expect(computed.marginBottom).toBe('0px')
    expect(computed.marginLeft).toBe('0px')
  })
})
