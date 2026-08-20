// @vitest-environment jsdom

import { act, createElement } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, beforeEach, expect, test, vi } from 'vitest'
import UploadScreen from './UploadScreen'

let root: Root
let container: HTMLDivElement

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

const selectFile = (input: HTMLInputElement, file: File) => {
  Object.defineProperty(input, 'files', {
    configurable: true,
    value: [file],
  })
  act(() => {
    input.dispatchEvent(new Event('change', { bubbles: true }))
  })
}

const click = (element: Element) => {
  act(() => {
    element.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

test('renders the optional xlsx CCCD chooser and high-resolution guidance', () => {
  const html = renderToStaticMarkup(createElement(UploadScreen, {
    busy: false,
    onBack: () => undefined,
    onStart: () => undefined,
  }))

  expect(html).toContain('Chọn file ảnh CCCD Excel (tuỳ chọn)')
  expect(html).toContain('Nên dùng ảnh gốc hoặc ảnh độ phân giải cao')
  expect((html.match(/accept="\.xlsx"/g) ?? []).length).toBe(2)
})

test('returns to the case list from the upload screen', () => {
  const onBack = vi.fn()
  act(() => {
    root.render(<UploadScreen busy={false} onBack={onBack} onStart={() => undefined} />)
  })

  const back = Array.from(container.querySelectorAll('button')).find(
    button => button.textContent?.includes('Quay lại danh sách hồ sơ'),
  )

  expect(back).toBeDefined()
  click(back!)
  expect(onBack).toHaveBeenCalledOnce()
})

test('prevents leaving while an upload is being submitted', () => {
  act(() => {
    root.render(<UploadScreen busy onBack={() => undefined} onStart={() => undefined} />)
  })

  const back = Array.from(container.querySelectorAll('button')).find(
    button => button.textContent?.includes('Quay lại danh sách hồ sơ'),
  ) as HTMLButtonElement | undefined

  expect(back).toBeDefined()
  expect(back?.disabled).toBe(true)
})

test('blocks CCCD without roster, then submits and clears all three files', () => {
  const onStart = vi.fn()
  act(() => {
    root.render(<UploadScreen busy={false} onBack={() => undefined} onStart={onStart} />)
  })
  const pdfInput = container.querySelector(
    'input[accept="application/pdf"]',
  ) as HTMLInputElement
  const xlsxInputs = container.querySelectorAll<HTMLInputElement>(
    'input[accept=".xlsx"]',
  )
  const start = container.querySelector('.upload-start') as HTMLButtonElement
  const pdf = new File(['pdf'], 'packet.pdf', { type: 'application/pdf' })
  const roster = new File(['roster'], 'roster.xlsx')
  const cccd = new File(['cccd'], 'cccd.xlsx')

  expect(xlsxInputs).toHaveLength(2)
  selectFile(pdfInput, pdf)
  selectFile(xlsxInputs[1], cccd)
  expect(container.querySelector('[role="alert"]')?.textContent).toContain(
    'Cần bảng kê',
  )
  expect(start.disabled).toBe(true)

  selectFile(xlsxInputs[0], roster)
  expect(container.querySelector('[role="alert"]')).toBeNull()
  expect(start.disabled).toBe(false)
  click(start)
  expect(onStart).toHaveBeenCalledWith(pdf, roster, cccd)

  const clear = Array.from(container.querySelectorAll('button')).find(
    button => button.textContent === 'Bỏ file CCCD',
  )
  expect(clear).toBeDefined()
  click(clear!)
  expect(container.textContent).not.toContain('cccd.xlsx')
})
