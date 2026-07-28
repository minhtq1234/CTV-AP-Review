import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import type { CaseDetail as CaseDetailT, CccdSummary } from '../upload/api'
import CaseDetail from './CaseDetail'

const base: Omit<CaseDetailT, 'cccdSummary' | 'cccdName'> = {
  id: 'case-1',
  name: 'Synthetic case',
  createdAt: null,
  status: 'ready',
  pdfName: 'input.pdf',
  rosterName: 'roster.xlsx',
  summary: { found: 0, roster_n: 0, matched: 0, auto_merged: 0 },
  error: null,
  packets: [],
  progress: { done: 0, total: 0, flagged: 0 },
}

function render(
  cccdSummary: CccdSummary | null,
  cccdName: string | null = 'cards.xlsx',
) {
  return renderToStaticMarkup(createElement(CaseDetail, {
    detail: { ...base, cccdName, cccdSummary },
    onOpenPacket: () => undefined,
    onBack: () => undefined,
    onExport: () => undefined,
  }))
}

test('renders only aggregate CCCD counts for ready or partial ingest', () => {
  const poisonedSummary = {
    status: 'partial',
    candidates: 3,
    attached: 1,
    unresolved: 2,
    errorCode: 'private-error-detail',
    candidateId: 'private-candidate-id',
    sourcePath: '/private/source/000000000001.png',
    anchor: 'private-anchor',
    ocrText: '000000000001',
  } as CccdSummary

  const html = render(poisonedSummary, 'private-cards.xlsx')

  expect(html).toContain('CCCD: 1 đã gắn · 2 chưa ghép')
  expect(html).not.toContain('000000000001')
  expect(html).not.toContain('private-candidate-id')
  expect(html).not.toContain('/private/source')
  expect(html).not.toContain('private-anchor')
  expect(html).not.toContain('private-error-detail')
  expect(html).not.toContain('private-cards.xlsx')
})

test('renders generic CCCD error and omits the line without a summary or filename', () => {
  expect(render({
    status: 'error',
    candidates: 0,
    attached: 0,
    unresolved: 0,
    errorCode: 'private-error-detail',
  })).toContain('CCCD: Không xử lý được file ảnh')
  expect(render(null)).not.toContain('CCCD:')
  expect(render({
    status: 'ready',
    candidates: 1,
    attached: 1,
    unresolved: 0,
  }, null)).not.toContain('CCCD:')
})
