import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import type { CtvFolder } from '../ctv/types'
import PacketGrid from './PacketGrid'

const folder: CtvFolder = {
  id: 'packet-grid-component',
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

test('renders Excel rows against dynamic document columns with accessible statuses', () => {
  const html = renderToStaticMarkup(
    <PacketGrid folder={folder} onOpenDocument={() => undefined} />,
  )

  expect(html).toContain('Excel file')
  expect(html).toContain('Hợp đồng')
  expect(html).toContain('Website thuế')
  expect(html).toContain('Nguyen Van A')
  expect(html).toContain('aria-label="Họ và tên · Chứng từ 1 Hợp đồng: Khớp"')
  expect(html).toContain('aria-label="Số CCCD · Chứng từ 2 Website thuế: Không khớp"')
  expect(html).toContain('Kết quả')
  expect(html).toContain('Không khớp')
})

test('distinguishes duplicate document labels by their package order', () => {
  const duplicateDocuments: CtvFolder = {
    ...folder,
    docs: [
      folder.docs[0],
      { ...folder.docs[0], id: 'contract-copy' },
    ],
    fields: [{
      ...folder.fields[0],
      sources: [
        folder.fields[0].sources[0],
        { ...folder.fields[0].sources[0], docId: 'contract-copy' },
      ],
    }],
  }
  const html = renderToStaticMarkup(
    <PacketGrid folder={duplicateDocuments} onOpenDocument={() => undefined} />,
  )

  expect(html).toContain('aria-label="Họ và tên · Chứng từ 1 Hợp đồng: Khớp"')
  expect(html).toContain('aria-label="Họ và tên · Chứng từ 2 Hợp đồng: Khớp"')
})

test('marks the exact evidence cell selected by the drawer', () => {
  const html = renderToStaticMarkup(
    <PacketGrid
      folder={folder}
      selectedEvidence={{ fieldKey: 'cccd', sourceIndex: 0 }}
      onOpenDocument={() => undefined}
    />,
  )

  expect(html).toContain(
    'class="packet-grid-status mismatch selected" aria-label="Số CCCD · Chứng từ 2 Website thuế: Không khớp"',
  )
  expect(html).toContain('aria-pressed="true"')
})
