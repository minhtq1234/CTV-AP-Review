import type { CtvFolder, EvidenceDoc } from './types'

// Flight-booking cases: the finance bảng-kê value (expected) is cross-checked 3 ways —
// against the approved eForm and against the travel-agency e-invoice.
const A4 = { width: 1000, height: 1400 }

const docs = (id: string): EvidenceDoc[] => [
  { id: 'eform', kind: 'contract', label: 'eForm (đã duyệt)', pages: [{ src: `/flights/${id}/eform.svg`, ...A4 }] },
  { id: 'invoice', kind: 'pit', label: 'Hóa đơn GTGT', pages: [{ src: `/flights/${id}/invoice.svg`, ...A4 }] },
]

// eForm box coords
const EF = {
  pax: { x: 325, y: 172, width: 340, height: 34 },
  depdate: { x: 325, y: 260, width: 200, height: 34 },
  airfare: { x: 620, y: 486, width: 220, height: 34 },
}
// invoice box coords
const INV = {
  sohd: { x: 373, y: 118, width: 150, height: 30 },
  mstban: { x: 222, y: 212, width: 190, height: 30 },
  mstmua: { x: 222, y: 302, width: 190, height: 30 },
  line: { x: 60, y: 418, width: 780, height: 34 },
  vat: { x: 760, y: 530, width: 80, height: 30 },
  tong: { x: 620, y: 568, width: 220, height: 34 },
}

export const flights: CtvFolder[] = [
  {
    id: 'le-hoang-nam', name: 'Lê Hoàng Nam', product: 'HAN-SGN-HAN · VJ',
    heading: 'Vé máy bay', status: 'pending', exempt: false, docs: docs('le-hoang-nam'),
    fields: [
      { key: 'pax', label: 'Khách đi', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'LÊ HOÀNG NAM', sources: [
        { docId: 'eform', page: 0, value: 'Lê Hoàng Nam', bbox: EF.pax, confidence: 0.96 } ] },
      { key: 'route', label: 'Hành trình', group: 'Chuyến đi', check: 'compare', kind: 'name', expected: 'HANSGNHAN', sources: [
        { docId: 'invoice', page: 0, value: '4Q3CN9 HANSGNHAN', bbox: INV.line, confidence: 0.9 } ] },
      { key: 'depdate', label: 'Ngày đi', group: 'Chuyến đi', check: 'compare', kind: 'date', expected: '05/05/2026', sources: [
        { docId: 'eform', page: 0, value: '05/05/2026', bbox: EF.depdate, confidence: 0.95 } ] },
      { key: 'fare', label: 'Tổng tiền vé (đã VAT)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '5.682.000 ₫', sources: [
        { docId: 'eform', page: 0, value: '5.628.000', bbox: EF.airfare, confidence: 0.95 },
        { docId: 'invoice', page: 0, value: '5.682.000', bbox: INV.tong, confidence: 0.97 } ] },
      { key: 'vat', label: 'Thuế suất VAT', group: 'Thanh toán', check: 'compare', kind: 'text', expected: '8%', sources: [
        { docId: 'invoice', page: 0, value: '8%', bbox: INV.vat, confidence: 0.95 } ] },
      { key: 'invno', label: 'Số hóa đơn', group: 'Chứng từ', check: 'compare', kind: 'number', expected: '2865', sources: [
        { docId: 'invoice', page: 0, value: '00002865', bbox: INV.sohd, confidence: 0.98 } ] },
      { key: 'mstseller', label: 'MST bên bán', group: 'Chứng từ', check: 'compare', kind: 'text', expected: '0312244033', sources: [
        { docId: 'invoice', page: 0, value: '0312244033', bbox: INV.mstban, confidence: 0.97 } ] },
      { key: 'mstbuyer', label: 'MST bên mua', group: 'Chứng từ', check: 'compare', kind: 'text', expected: '0304851362', sources: [
        { docId: 'invoice', page: 0, value: '0304851362', bbox: INV.mstmua, confidence: 0.97 } ] },
    ],
  },
  {
    id: 'tran-van-minh', name: 'Trần Văn Minh', product: 'SGN-HAN-SGN · VJ',
    heading: 'Vé máy bay', status: 'pending', exempt: false, docs: docs('tran-van-minh'),
    fields: [
      { key: 'pax', label: 'Khách đi', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'TRẦN VĂN MINH', sources: [
        { docId: 'eform', page: 0, value: 'Trần Văn Minh', bbox: EF.pax, confidence: 0.96 } ] },
      { key: 'route', label: 'Hành trình', group: 'Chuyến đi', check: 'compare', kind: 'name', expected: 'SGNHANSGN', sources: [
        { docId: 'invoice', page: 0, value: 'N9HR7N SGNHANSGN', bbox: INV.line, confidence: 0.91 } ] },
      { key: 'depdate', label: 'Ngày đi', group: 'Chuyến đi', check: 'compare', kind: 'date', expected: '14/04/2026', sources: [
        { docId: 'eform', page: 0, value: '14/04/2026', bbox: EF.depdate, confidence: 0.95 } ] },
      { key: 'fare', label: 'Tổng tiền vé (đã VAT)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '1.537.000 ₫', sources: [
        { docId: 'eform', page: 0, value: '1.537.000', bbox: EF.airfare, confidence: 0.95 },
        { docId: 'invoice', page: 0, value: '1.537.000', bbox: INV.tong, confidence: 0.97 } ] },
      { key: 'vat', label: 'Thuế suất VAT', group: 'Thanh toán', check: 'compare', kind: 'text', expected: '8%', sources: [
        { docId: 'invoice', page: 0, value: '8%', bbox: INV.vat, confidence: 0.95 } ] },
      { key: 'invno', label: 'Số hóa đơn', group: 'Chứng từ', check: 'compare', kind: 'number', expected: '2865', sources: [
        { docId: 'invoice', page: 0, value: '00002865', bbox: INV.sohd, confidence: 0.98 } ] },
      { key: 'mstseller', label: 'MST bên bán', group: 'Chứng từ', check: 'compare', kind: 'text', expected: '0312244033', sources: [
        { docId: 'invoice', page: 0, value: '0312244033', bbox: INV.mstban, confidence: 0.97 } ] },
      { key: 'mstbuyer', label: 'MST bên mua', group: 'Chứng từ', check: 'compare', kind: 'text', expected: '0304851362', sources: [
        { docId: 'invoice', page: 0, value: '0304851362', bbox: INV.mstmua, confidence: 0.97 } ] },
    ],
  },
]
