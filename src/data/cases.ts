import type { Case } from '../types'

const RECEIPT = { width: 800, height: 1120 }

// shared receipt coordinate grid (matches the SVG receipts in public/docs)
const G = {
  vendor:   { x: 150, y: 92,  width: 500, height: 48 },
  invoice:  { x: 470, y: 192, width: 210, height: 30 },
  date:     { x: 470, y: 232, width: 150, height: 30 },
  subtotal: { x: 520, y: 542, width: 190, height: 32 },
  vat:      { x: 520, y: 592, width: 190, height: 32 },
  total:    { x: 500, y: 658, width: 210, height: 40 },
}

export const seedCases: Case[] = [
  {
    id: 'PR-2026-0138', title: 'Tiếp khách phòng Kinh doanh', requester: 'Trần Thị B',
    category: 'Tiếp khách', status: 'pending',
    pages: [
      { src: '/docs/case1-form.svg', ...RECEIPT, label: 'Đề nghị' },
      { src: '/docs/case1-receipt.svg', ...RECEIPT, label: 'Hóa đơn' },
    ],
    fields: [
      { key: 'vendor', label: 'Nhà cung cấp', kind: 'name', expected: 'Highlands',
        prediction: { value: 'CÔNG TY CP HIGHLANDS COFFEE', page: 1, bbox: G.vendor, confidence: 0.95 } },
      { key: 'invoice', label: 'Số hóa đơn', kind: 'text', expected: 'HD-2026-8842',
        prediction: { value: 'HD-2026-8842', page: 1, bbox: G.invoice, confidence: 0.97 } },
      { key: 'date', label: 'Ngày hóa đơn', kind: 'date', expected: '03/07/2026',
        prediction: { value: '03/07/2026', page: 1, bbox: G.date, confidence: 0.98 } },
      { key: 'subtotal', label: 'Tiền hàng', kind: 'number', expected: '454.545 ₫',
        prediction: { value: '454.545', page: 1, bbox: G.subtotal, confidence: 0.96 } },
      { key: 'vat', label: 'Thuế GTGT', kind: 'number', expected: '45.455 ₫',
        prediction: { value: '45.455', page: 1, bbox: G.vat, confidence: 0.96 } },
      { key: 'total', label: 'Tổng cộng', kind: 'number', expected: '500.000 ₫',
        prediction: { value: '500.000', page: 1, bbox: G.total, confidence: 0.98 } },
    ],
  },
  {
    id: 'PR-2026-0142', title: 'Chi phí đi lại — đón đối tác', requester: 'Nguyễn Văn A',
    category: 'Chi phí đi lại', status: 'pending',
    pages: [
      { src: '/docs/case2-form.svg', ...RECEIPT, label: 'Đề nghị' },
      { src: '/docs/case2-receipt.svg', ...RECEIPT, label: 'Hóa đơn' },
      { src: '/docs/case2-photo.svg', ...RECEIPT, label: 'Ảnh chuyến đi' },
    ],
    fields: [
      { key: 'vendor', label: 'Nhà cung cấp', kind: 'name', expected: 'Grab',
        prediction: { value: 'CÔNG TY TNHH GRAB', page: 1, bbox: G.vendor, confidence: 0.94 } },
      { key: 'invoice', label: 'Số hóa đơn', kind: 'text', expected: 'AA/26E-0451',
        prediction: { value: 'AA/26E-0451', page: 1, bbox: G.invoice, confidence: 0.52 } },
      { key: 'date', label: 'Ngày hóa đơn', kind: 'date', expected: '05/07/2026',
        prediction: { value: '05/07/2026', page: 1, bbox: G.date, confidence: 0.99 } },
      { key: 'subtotal', label: 'Tiền hàng', kind: 'number', expected: '1.863.636 ₫',
        prediction: { value: '1.863.636', page: 1, bbox: G.subtotal, confidence: 0.97 } },
      { key: 'vat', label: 'Thuế GTGT', kind: 'number', expected: '186.364 ₫',
        prediction: { value: '186.364', page: 1, bbox: G.vat, confidence: 0.97 } },
      { key: 'total', label: 'Tổng cộng', kind: 'number', expected: '2.500.000 ₫',
        prediction: { value: '2.050.000', page: 1, bbox: G.total, confidence: 0.98 } },
    ],
  },
  {
    id: 'PR-2026-0151', title: 'Văn phòng phẩm quý 3', requester: 'Lê Văn C',
    category: 'Văn phòng phẩm', status: 'pending',
    pages: [
      { src: '/docs/case3-form.svg', ...RECEIPT, label: 'Đề nghị' },
      { src: '/docs/case3-receipt.svg', ...RECEIPT, label: 'Hóa đơn' },
    ],
    fields: [
      { key: 'vendor', label: 'Nhà cung cấp', kind: 'name', expected: 'Nhà sách Fahasa',
        prediction: { value: 'NHÀ SÁCH FAHASA', page: 1, bbox: G.vendor, confidence: 0.9 } },
      { key: 'invoice', label: 'Số hóa đơn', kind: 'text', expected: 'FHS-0099',
        prediction: { value: 'FHS-0099', page: 1, bbox: G.invoice, confidence: 0.88 } },
      { key: 'date', label: 'Ngày hóa đơn', kind: 'date', expected: '01/07/2026',
        prediction: { value: '01/07/2026', page: 1, bbox: G.date, confidence: 0.86 } },
      { key: 'subtotal', label: 'Tiền hàng', kind: 'number', expected: '290.909 ₫',
        prediction: { value: '290.909', page: 1, bbox: G.subtotal, confidence: 0.83 } },
      { key: 'vat', label: 'Thuế GTGT', kind: 'number', expected: '29.091 ₫',
        prediction: { value: '29.091', page: 1, bbox: G.vat, confidence: 0.8 } },
      { key: 'total', label: 'Tổng cộng', kind: 'number', expected: '320.000 ₫',
        prediction: { value: '320.000', page: 1, bbox: G.total, confidence: 0.5 } },
    ],
  },
]
