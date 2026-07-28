import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import type { CaseSummary, Progress } from '../upload/api'
import CaseList from './CaseList'

const processingCase: CaseSummary = {
  id: 'synthetic-case',
  name: 'Synthetic case',
  createdAt: null,
  status: 'processing',
  pdfName: 'input.pdf',
  progress: { done: 0, total: 0, flagged: 0 },
}

function render(live: Progress) {
  return renderToStaticMarkup(createElement(CaseList, {
    cases: [processingCase],
    live: { [processingCase.id]: live },
    onOpen: () => undefined,
    onNew: () => undefined,
    onDelete: () => undefined,
  }))
}

test('renders the CCCD processing label instead of packet progress', () => {
  const html = render({ stage: 'cccd', done: 1, total: 1, detail: '' })

  expect(html).toContain('Đọc và ghép ảnh CCCD…')
  expect(html).not.toContain('gói 1/1')
})

test('keeps packet progress for OCR stages', () => {
  expect(render({ stage: 'ocr', done: 1, total: 2, detail: 'synthetic' }))
    .toContain('gói 1/2 · synthetic')
})
