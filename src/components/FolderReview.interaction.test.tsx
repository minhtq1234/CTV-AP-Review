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

const multiPageFolder: CtvFolder = {
  ...folder,
  id: 'multi-page-interaction-folder',
  docs: [
    {
      ...folder.docs[0],
      pages: [
        { src: '/contract-1.svg', width: 1000, height: 1400 },
        { src: '/contract-2.svg', width: 1000, height: 1400 },
        { src: '/contract-3.svg', width: 1000, height: 1400 },
      ],
    },
    {
      ...folder.docs[1],
      pages: [
        { src: '/appendix-1.svg', width: 1000, height: 1400 },
        { src: '/appendix-2.svg', width: 1000, height: 1400 },
        { src: '/appendix-3.svg', width: 1000, height: 1400 },
      ],
    },
  ],
}

let root: Root
let container: HTMLDivElement
let styleElement: HTMLStyleElement
let scrollIntoViewSpy: ReturnType<typeof vi.fn>
let scrollToSpy: ReturnType<typeof vi.fn>

beforeEach(() => {
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    callback(0)
    return 0
  })
  vi.stubGlobal('cancelAnimationFrame', () => undefined)
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  scrollIntoViewSpy = vi.fn()
  scrollToSpy = vi.fn(function (this: HTMLElement, options: ScrollToOptions) {
    this.scrollLeft = options.left ?? this.scrollLeft
    this.scrollTop = options.top ?? this.scrollTop
  })
  HTMLElement.prototype.scrollIntoView = scrollIntoViewSpy
  HTMLElement.prototype.scrollTo = scrollToSpy
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

const renderReview = (review = emptyReview, reviewFolder = folder) => {
  const onReview = vi.fn()
  act(() => {
    root.render(
      <FolderReview
        folder={reviewFolder}
        review={review}
        onReview={onReview}
        onCommitReview={async () => undefined}
      />,
    )
  })
  return onReview
}

const pressOn = (target: Element, key: string) => {
  act(() => {
    target.dispatchEvent(new KeyboardEvent('keydown', {
      key,
      bubbles: true,
      cancelable: true,
    }))
  })
}

const press = (key: string) => pressOn(document.body, key)

const click = (element: Element) => {
  act(() => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

const documentModeButton = (label: string) => Array.from(
  container.querySelectorAll('.ev-modes button'),
).find(button => button.textContent === label)

const viewerScroll = () => container.querySelector('.ev-scroll') as HTMLDivElement

const viewerZoom = () => container.querySelector('.zoom-value')?.textContent

const viewerHasMode = (mode: 'single' | 'paired') => container
  .querySelector('.ev-document')
  ?.classList.contains(mode)

const configureFocusedFieldGeometry = () => {
  const scroll = viewerScroll()
  Object.defineProperty(scroll, 'clientHeight', { configurable: true, value: 1000 })
  const page = container.querySelector('.document-page[data-page-index="0"]') as HTMLDivElement
  vi.spyOn(page, 'getBoundingClientRect').mockReturnValue({
    bottom: 1400,
    height: 1400,
    left: 0,
    right: 920,
    toJSON: () => ({}),
    top: 0,
    width: 920,
    x: 0,
    y: 0,
  })
}

describe('FolderReview mounted Overview interactions', () => {
  it('resets the complete Overview preset when the selected row is clicked again', () => {
    renderReview(emptyReview, multiPageFolder)

    click(documentModeButton('1 trang')!)
    click(container.querySelector('[aria-label="Phóng to"]')!)
    const appendixTab = Array.from(container.querySelectorAll('.ev-tab'))
      .find(button => button.textContent === 'Synthetic appendix')
    click(appendixTab!)

    const scroll = viewerScroll()
    scroll.scrollLeft = 240
    scroll.scrollTop = 180
    scrollToSpy.mockClear()
    scrollIntoViewSpy.mockClear()
    click(container.querySelector('.overview-row')!)

    expect(container.querySelector('img')?.getAttribute('src')).toBe('/contract-1.svg')
    expect(viewerHasMode('paired')).toBe(true)
    expect(container.querySelectorAll('.document-page-row')).toHaveLength(2)
    expect(viewerZoom()).toBe('100%')
    expect(scrollToSpy).toHaveBeenLastCalledWith({
      left: 0,
      top: 0,
      behavior: 'instant',
    })
    expect(container.querySelector('.document-focus-anchor')).toBeNull()
    expect(container.querySelector('.roster-callout')).toBeNull()
    expect(scrollIntoViewSpy).not.toHaveBeenCalled()

    scroll.scrollLeft = 75
    scroll.scrollTop = 90
    scrollToSpy.mockClear()
    click(container.querySelector('.overview-row')!)

    expect(scrollToSpy).toHaveBeenLastCalledWith({
      left: 0,
      top: 0,
      behavior: 'instant',
    })
  })

  it('uses a native selected Overview control separate from rejection actions', () => {
    renderReview()

    const overviewRow = container.querySelector('.overview-row')!
    const overviewControl = overviewRow.querySelector('.overview-selection-control')!
    const rejectionButton = Array.from(overviewRow.querySelectorAll('button'))
      .find(button => button.textContent === 'Từ chối hồ sơ')!

    expect(overviewControl).not.toBeNull()
    if (!overviewControl) return
    expect(overviewControl.tagName).toBe('BUTTON')
    expect(overviewControl.getAttribute('type')).toBe('button')
    expect(overviewControl.getAttribute('aria-label')).toBe('Tổng quan')
    expect(overviewControl.getAttribute('aria-pressed')).toBe('true')
    expect(overviewControl.contains(rejectionButton)).toBe(false)
    expect(overviewControl.parentElement).toBe(rejectionButton.parentElement)
    expect(overviewRow.getAttribute('role')).toBeNull()
    expect(overviewRow.getAttribute('tabindex')).toBeNull()

    press('ArrowDown')
    expect(overviewControl.getAttribute('aria-pressed')).toBe('false')
    click(overviewControl)

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(overviewControl.getAttribute('aria-pressed')).toBe('true')
  })

  it('moves from the focused Overview control to the first field with ArrowDown', () => {
    const onReview = renderReview()
    const overviewControl = container.querySelector(
      '.overview-selection-control',
    ) as HTMLButtonElement

    act(() => overviewControl.focus())
    expect(document.activeElement).toBe(overviewControl)
    pressOn(overviewControl, 'ArrowDown')

    const selectedField = container.querySelector('.cfield.sel')
    expect(selectedField).not.toBeNull()
    expect(selectedField?.textContent).toContain('Trường mẫu')
    expect(onReview).toHaveBeenCalledWith({
      done: false,
      fields: { 'field-a': { seen: true, flag: null } },
      rejection: null,
    })
  })

  it('keeps the persisted-rejection edit action outside the Overview control', () => {
    renderReview({
      done: true,
      fields: { 'field-a': { seen: true, flag: null } },
      rejection: { reasons: ['missing_documents'], note: 'Synthetic note' },
    })

    const overviewControl = container.querySelector('.overview-selection-control')!
    const editButton = Array.from(container.querySelectorAll('button'))
      .find(button => button.textContent === 'Sửa lý do')!

    expect(overviewControl).not.toBeNull()
    if (!overviewControl) return
    expect(overviewControl.tagName).toBe('BUTTON')
    expect(overviewControl.contains(editButton)).toBe(false)
  })

  it('keeps manual Overview state unchanged when ArrowUp is pressed in Overview', () => {
    renderReview(emptyReview, multiPageFolder)

    click(documentModeButton('1 trang')!)
    click(container.querySelector('[aria-label="Phóng to"]')!)
    const appendixTab = Array.from(container.querySelectorAll('.ev-tab'))
      .find(button => button.textContent === 'Synthetic appendix')
    click(appendixTab!)

    const scroll = viewerScroll()
    scroll.scrollLeft = 140
    scroll.scrollTop = 110
    scrollToSpy.mockClear()
    pressOn(container.querySelector('.overview-selection-control')!, 'ArrowUp')

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/appendix-1.svg')
    expect(viewerHasMode('single')).toBe(true)
    expect(viewerZoom()).toBe('125%')
    expect(scroll.scrollLeft).toBe(140)
    expect(scroll.scrollTop).toBe(110)
    expect(scrollToSpy).not.toHaveBeenCalled()
    expect(container.querySelector('.document-focus-anchor')).toBeNull()
    expect(container.querySelector('.roster-callout')).toBeNull()
  })

  it('preserves manual Overview controls across tabs and resets the preset on re-entry', () => {
    renderReview(emptyReview, multiPageFolder)

    expect(viewerHasMode('paired')).toBe(true)
    expect(container.querySelectorAll('.document-page-row')).toHaveLength(2)
    expect(viewerZoom()).toBe('100%')
    expect(scrollIntoViewSpy).not.toHaveBeenCalled()

    click(documentModeButton('1 trang')!)
    click(container.querySelector('[aria-label="Phóng to"]')!)

    expect(viewerHasMode('single')).toBe(true)
    expect(container.querySelectorAll('.document-page-row')).toHaveLength(3)
    expect(viewerZoom()).toBe('125%')

    const scroll = viewerScroll()
    scroll.scrollLeft = 300
    scroll.scrollTop = 200
    scrollToSpy.mockClear()
    act(() => {
      scroll.dispatchEvent(new MouseEvent('mousedown', {
        bubbles: true, clientX: 320, clientY: 240,
      }))
      window.dispatchEvent(new MouseEvent('mousemove', { clientX: 260, clientY: 210 }))
      window.dispatchEvent(new MouseEvent('mouseup'))
    })
    expect(scrollToSpy).toHaveBeenLastCalledWith({ left: 360, top: 230, behavior: 'instant' })

    scroll.scrollLeft = 45
    scroll.scrollTop = 60
    scrollToSpy.mockClear()
    const appendixTab = Array.from(container.querySelectorAll('.ev-tab'))
      .find(button => button.textContent === 'Synthetic appendix')
    click(appendixTab!)

    expect(scrollToSpy).toHaveBeenLastCalledWith({ left: 0, top: 0, behavior: 'instant' })
    expect(container.querySelector('img')?.getAttribute('src')).toBe('/appendix-1.svg')
    expect(viewerHasMode('single')).toBe(true)
    expect(viewerZoom()).toBe('125%')

    press('ArrowDown')
    click(container.querySelector('[aria-label="Phóng to"]')!)
    expect(viewerZoom()).toBe('125%')
    scroll.scrollLeft = 90
    scroll.scrollTop = 120
    scrollToSpy.mockClear()
    press('ArrowUp')

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(viewerHasMode('paired')).toBe(true)
    expect(container.querySelectorAll('.document-page-row')).toHaveLength(2)
    expect(viewerZoom()).toBe('100%')
    expect(scrollToSpy).toHaveBeenLastCalledWith({ left: 0, top: 0, behavior: 'instant' })
  })

  it('autofocuses and focus-scrolls an unlocked field but not Overview', () => {
    renderReview(emptyReview, multiPageFolder)
    configureFocusedFieldGeometry()

    expect(scrollIntoViewSpy).not.toHaveBeenCalled()
    press('ArrowDown')

    expect(container.querySelector('.document-focus-anchor')).not.toBeNull()
    expect(viewerZoom()).toBe('200%')
    expect(scrollIntoViewSpy).toHaveBeenCalledWith({
      behavior: 'smooth',
      block: 'center',
      inline: 'center',
    })
  })

  it('does not autofocus or focus-scroll a locked field', () => {
    renderReview(emptyReview, multiPageFolder)
    click(container.querySelector('[aria-label="Khoá khung nhìn"]')!)
    configureFocusedFieldGeometry()
    scrollIntoViewSpy.mockClear()

    press('ArrowDown')

    expect(container.querySelector('.document-focus-anchor')).not.toBeNull()
    expect(viewerZoom()).toBe('100%')
    expect(scrollIntoViewSpy).not.toHaveBeenCalled()
  })

  it('opens on Overview without publishing a field review and guards field shortcuts', () => {
    const onReview = renderReview()

    expect(container.querySelector('[data-review-selection="overview"]')).not.toBeNull()
    expect(container.querySelector('.roster-callout')).toBeNull()
    expect(onReview).not.toHaveBeenCalled()

    const overviewControl = container.querySelector('.overview-selection-control')!
    pressOn(overviewControl, 'ArrowRight')
    pressOn(overviewControl, 'f')

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
