import type { DocRecap, EvidenceDoc, CtvFolder } from './types'
import { RECAP_DISCLAIMER } from '../logic/recap'

// Hand-made folders: synthetic evidence documents (public/folders/<id>/*.svg) plus the
// Excel-row "claimed" values and seeded AI extractions. Each field is cross-checked against
// every document it appears in (sources[]); the field flags if any source disagrees with Excel.
const CARD = { width: 1010, height: 636 }
const A4 = { width: 1010, height: 1400 }

const contractRecap = (product: string): DocRecap => ({
  bullets: [
    `Hợp đồng cung ứng dịch vụ CTV cho sản phẩm ${product}.`,
    'Phạm vi: cung ứng dịch vụ theo thoả thuận; phí chi trả một lần.',
    'Trang cuối có mục chữ ký & con dấu của hai bên.',
  ],
  nhanDinh: 'Nội dung hợp đồng phù hợp phạm vi CTV; chưa thấy mâu thuẫn với bảng kê.',
  disclaimer: RECAP_DISCLAIMER,
})
const bbntRecap = (product: string): DocRecap => ({
  bullets: [
    `Biên bản nghiệm thu dịch vụ ${product}.`,
    'Xác nhận đã hoàn thành khối lượng công việc trong kỳ.',
    'Thời gian nghiệm thu nằm trong kỳ thanh toán.',
  ],
  nhanDinh: 'Nội dung & thời gian khớp BBNT; không thấy mâu thuẫn — có thể xác nhận C1.',
  disclaimer: RECAP_DISCLAIMER,
})
const appendixRecap = (product: string): DocRecap => ({
  bullets: [
    `Phụ lục đánh giá SOW/KPI cho sản phẩm ${product}, kỳ Quý I/2026.`,
    'Các hạng mục KPI đều đạt chỉ tiêu; khối lượng thực hiện khớp cam kết.',
    'Thời gian thực hiện nằm trong kỳ nghiệm thu.',
  ],
  nhanDinh: 'Nội dung Phụ lục phù hợp phạm vi hợp đồng; thời gian khớp — hỗ trợ xác nhận C1.',
  disclaimer: RECAP_DISCLAIMER,
})

type FolderRecaps = { contract?: DocRecap; bbnt?: DocRecap }
const docsFor = (id: string, recaps: FolderRecaps = {}): EvidenceDoc[] => [
  { id: 'id_front', kind: 'id_front', label: 'CCCD mặt trước', pages: [{ src: `/folders/${id}/cccd-front.svg`, ...CARD }] },
  { id: 'id_back', kind: 'id_back', label: 'CCCD mặt sau', pages: [{ src: `/folders/${id}/cccd-back.svg`, ...CARD }] },
  { id: 'contract', kind: 'contract', label: 'Hợp đồng (5 trang)', recap: recaps.contract, pages: [
    { src: `/folders/${id}/contract.svg`, ...A4 },
    { src: '/folders/_shared/contract-2.svg', ...A4 },
    { src: '/folders/_shared/contract-3.svg', ...A4 },
    { src: '/folders/_shared/contract-4.svg', ...A4 },
    { src: `/folders/${id}/contract-5.svg`, ...A4 },
  ] },
  { id: 'pit', kind: 'pit', label: 'Tờ khai PIT', pages: [{ src: `/folders/${id}/pit.svg`, ...A4 }] },
  { id: 'bbnt', kind: 'bbnt', label: 'Biên bản nghiệm thu', recap: recaps.bbnt, pages: [{ src: `/folders/${id}/bbnt.svg`, ...A4 }] },
]

// box coordinates per document layout (natural px)
const ID = {
  no: { x: 435, y: 224, width: 305, height: 44 }, name: { x: 315, y: 318, width: 475, height: 44 },
  dob: { x: 555, y: 372, width: 175, height: 34 }, expiry: { x: 245, y: 574, width: 175, height: 34 },
}
const CT = {
  name: { x: 245, y: 335, width: 340, height: 34 }, cccd: { x: 405, y: 415, width: 250, height: 34 },
  acct: { x: 235, y: 495, width: 285, height: 34 }, bank: { x: 295, y: 535, width: 445, height: 34 },
  amount: { x: 335, y: 822, width: 235, height: 36 },
}
const PT = {
  name: { x: 325, y: 335, width: 410, height: 34 }, cccd: { x: 325, y: 447, width: 300, height: 34 },
  income: { x: 600, y: 597, width: 255, height: 34 }, tax: { x: 600, y: 667, width: 255, height: 34 },
}
const BB = { name: { x: 325, y: 335, width: 410, height: 34 }, cccd: { x: 325, y: 392, width: 300, height: 34 } }

export const folders: CtvFolder[] = [
  {
    id: 'le-thi-mai-anh', name: 'Lê Thị Mai Anh', product: 'Crossfire: Legends',
    status: 'pending', exempt: false,
    docs: [
      ...docsFor('le-thi-mai-anh', { contract: contractRecap('Crossfire: Legends'), bbnt: bbntRecap('Crossfire: Legends') }),
      { id: 'commitment', kind: 'commitment', label: 'Bản cam kết', pages: [{ src: `/folders/le-thi-mai-anh/bancamket.svg`, ...A4 }] },
      { id: 'appendix', kind: 'appendix', label: 'Phụ lục (SOW/KPI)', recap: appendixRecap('Crossfire: Legends'),
        pages: [{ src: '/folders/le-thi-mai-anh/appendix.svg', ...A4 }] },
    ],
    fields: [
      { key: 'name', label: 'Họ và tên', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'Lê Thị Mai Anh', sources: [
        { docId: 'id_front', page: 0, value: 'LÊ THỊ MAI ANH', bbox: ID.name, confidence: 0.96 },
        { docId: 'contract', page: 0, value: 'LÊ THỊ MAI ANH', bbox: CT.name, confidence: 0.95 },
        { docId: 'pit', page: 0, value: 'LÊ THỊ MAI ANH', bbox: PT.name, confidence: 0.94 },
        { docId: 'bbnt', page: 0, value: 'LÊ THỊ MAI ANH', bbox: BB.name, confidence: 0.93 },
      ] },
      { key: 'cccd', label: 'Số CCCD', group: 'Danh tính', check: 'compare', kind: 'text', expected: '079198004321', sources: [
        { docId: 'id_front', page: 0, value: '079198004321', bbox: ID.no, confidence: 0.98 },
        { docId: 'contract', page: 0, value: '079198004321', bbox: CT.cccd, confidence: 0.96 },
        { docId: 'pit', page: 0, value: '079198004327', bbox: PT.cccd, confidence: 0.9 },
        { docId: 'bbnt', page: 0, value: '079198004321', bbox: BB.cccd, confidence: 0.93 },
      ] },
      { key: 'dob', label: 'Ngày sinh', group: 'Danh tính', check: 'compare', kind: 'date', expected: '03/05/1998', sources: [
        { docId: 'id_front', page: 0, value: '03/05/1998', bbox: ID.dob, confidence: 0.97 },
      ] },
      { key: 'expiry', label: 'Hiệu lực CCCD', group: 'Danh tính', check: 'expiry', kind: 'date', expected: 'Còn hiệu lực', sources: [
        { docId: 'id_front', page: 0, value: '03/05/2023', bbox: ID.expiry, confidence: 0.92 },
      ] },
      { key: 'bank_acct', label: 'Số tài khoản', group: 'Ngân hàng', check: 'compare', kind: 'text', expected: '19001234567', sources: [
        { docId: 'contract', page: 0, value: '0071000998877', bbox: CT.acct, confidence: 0.95 },
      ] },
      { key: 'bank_name', label: 'Ngân hàng', group: 'Ngân hàng', check: 'compare', kind: 'name', expected: 'Techcombank', sources: [
        { docId: 'contract', page: 0, value: 'Vietcombank - CN Kỳ Đồng, TP.HCM', bbox: CT.bank, confidence: 0.9 },
      ] },
      { key: 'gross', label: 'Phí dịch vụ (Gross)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '10.000.000 ₫', sources: [
        { docId: 'contract', page: 0, value: '10.000.000', bbox: CT.amount, confidence: 0.97 },
        { docId: 'pit', page: 0, value: '10.000.000', bbox: PT.income, confidence: 0.95 },
      ] },
      { key: 'pit', label: 'Thuế PIT (10%)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '1.000.000 ₫', sources: [
        { docId: 'pit', page: 0, value: '1.000.000', bbox: PT.tax, confidence: 0.95 },
      ] },
      { key: 'net', label: 'Thực nhận (Gross − PIT)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '9.000.000 ₫', sources: [] },
      { key: 'policy', label: 'Miễn thuế / Cam kết', group: 'Chính sách', check: 'policy', kind: 'text', expected: 'Khấu trừ 10%', sources: [] },
    ],
  },
  {
    id: 'tran-minh-khoa', name: 'Trần Minh Khoa', product: 'Play Together',
    status: 'pending', exempt: false, docs: docsFor('tran-minh-khoa', { contract: contractRecap('Play Together'), bbnt: bbntRecap('Play Together') }),
    fields: [
      { key: 'name', label: 'Họ và tên', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'Trần Minh Khoa', sources: [
        { docId: 'id_front', page: 0, value: 'TRẦN MINH KHOA', bbox: ID.name, confidence: 0.96 },
        { docId: 'contract', page: 0, value: 'TRẦN MINH KHOA', bbox: CT.name, confidence: 0.95 },
        { docId: 'pit', page: 0, value: 'TRẦN MINH KHOA', bbox: PT.name, confidence: 0.94 },
        { docId: 'bbnt', page: 0, value: 'TRẦN MINH KHOA', bbox: BB.name, confidence: 0.93 },
      ] },
      { key: 'cccd', label: 'Số CCCD', group: 'Danh tính', check: 'compare', kind: 'text', expected: '079200011234', sources: [
        { docId: 'id_front', page: 0, value: '079200011234', bbox: ID.no, confidence: 0.97 },
        { docId: 'contract', page: 0, value: '079200011234', bbox: CT.cccd, confidence: 0.96 },
        { docId: 'pit', page: 0, value: '079200011234', bbox: PT.cccd, confidence: 0.95 },
        { docId: 'bbnt', page: 0, value: '079200011234', bbox: BB.cccd, confidence: 0.94 },
      ] },
      { key: 'dob', label: 'Ngày sinh', group: 'Danh tính', check: 'compare', kind: 'date', expected: '14/03/2000', sources: [
        { docId: 'id_front', page: 0, value: '14/03/2000', bbox: ID.dob, confidence: 0.98 },
      ] },
      { key: 'expiry', label: 'Hiệu lực CCCD', group: 'Danh tính', check: 'expiry', kind: 'date', expected: 'Còn hiệu lực', sources: [
        { docId: 'id_front', page: 0, value: '14/03/2033', bbox: ID.expiry, confidence: 0.95 },
      ] },
      { key: 'bank_acct', label: 'Số tài khoản', group: 'Ngân hàng', check: 'compare', kind: 'text', expected: '0071000512345', sources: [
        { docId: 'contract', page: 0, value: '0071000512345', bbox: CT.acct, confidence: 0.96 },
      ] },
      { key: 'bank_name', label: 'Ngân hàng', group: 'Ngân hàng', check: 'compare', kind: 'name', expected: 'Vietcombank', sources: [
        { docId: 'contract', page: 0, value: 'Vietcombank - CN Quận 1, TP.HCM', bbox: CT.bank, confidence: 0.93 },
      ] },
      { key: 'gross', label: 'Phí dịch vụ (Gross)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '8.000.000 ₫', sources: [
        { docId: 'contract', page: 0, value: '8.000.000', bbox: CT.amount, confidence: 0.97 },
        { docId: 'pit', page: 0, value: '8.000.000', bbox: PT.income, confidence: 0.95 },
      ] },
      { key: 'pit', label: 'Thuế PIT (10%)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '800.000 ₫', sources: [
        { docId: 'pit', page: 0, value: '800.000', bbox: PT.tax, confidence: 0.95 },
      ] },
      { key: 'net', label: 'Thực nhận (Gross − PIT)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '7.200.000 ₫', sources: [] },
      { key: 'policy', label: 'Miễn thuế / Cam kết', group: 'Chính sách', check: 'policy', kind: 'text', expected: 'Khấu trừ 10%', sources: [] },
    ],
  },
  {
    id: 'pham-quoc-hung', name: 'Phạm Quốc Hưng', product: 'Danh Tướng 3Q',
    status: 'pending', exempt: true, docs: docsFor('pham-quoc-hung', { contract: contractRecap('Danh Tướng 3Q'), bbnt: bbntRecap('Danh Tướng 3Q') }),
    fields: [
      { key: 'name', label: 'Họ và tên', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'Phạm Quốc Hưng', sources: [
        { docId: 'id_front', page: 0, value: 'PHẠM QUỐC HƯNG', bbox: ID.name, confidence: 0.95 },
        { docId: 'contract', page: 0, value: 'PHẠM QUỐC HƯNG', bbox: CT.name, confidence: 0.94 },
        { docId: 'pit', page: 0, value: 'PHẠM QUỐC HƯNG', bbox: PT.name, confidence: 0.93 },
        { docId: 'bbnt', page: 0, value: 'PHẠM QUỐC HƯNG', bbox: BB.name, confidence: 0.92 },
      ] },
      { key: 'cccd', label: 'Số CCCD', group: 'Danh tính', check: 'compare', kind: 'text', expected: '079090003210', sources: [
        { docId: 'id_front', page: 0, value: '079090003210', bbox: ID.no, confidence: 0.55 },
        { docId: 'contract', page: 0, value: '079090003210', bbox: CT.cccd, confidence: 0.95 },
        { docId: 'pit', page: 0, value: '079090003210', bbox: PT.cccd, confidence: 0.94 },
        { docId: 'bbnt', page: 0, value: '079090003210', bbox: BB.cccd, confidence: 0.93 },
      ] },
      { key: 'dob', label: 'Ngày sinh', group: 'Danh tính', check: 'compare', kind: 'date', expected: '22/09/1990', sources: [
        { docId: 'id_front', page: 0, value: '22/09/1990', bbox: ID.dob, confidence: 0.9 },
      ] },
      { key: 'expiry', label: 'Hiệu lực CCCD', group: 'Danh tính', check: 'expiry', kind: 'date', expected: 'Còn hiệu lực', sources: [
        { docId: 'id_front', page: 0, value: '22/09/2030', bbox: ID.expiry, confidence: 0.94 },
      ] },
      { key: 'bank_acct', label: 'Số tài khoản', group: 'Ngân hàng', check: 'compare', kind: 'text', expected: '0451000778899', sources: [
        { docId: 'contract', page: 0, value: '0451000778899', bbox: CT.acct, confidence: 0.95 },
      ] },
      { key: 'bank_name', label: 'Ngân hàng', group: 'Ngân hàng', check: 'compare', kind: 'name', expected: 'ACB', sources: [
        { docId: 'contract', page: 0, value: 'ACB - CN Tân Bình, TP.HCM', bbox: CT.bank, confidence: 0.92 },
      ] },
      { key: 'gross', label: 'Phí dịch vụ (Gross)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '15.000.000 ₫', sources: [
        { docId: 'contract', page: 0, value: '15.000.000', bbox: CT.amount, confidence: 0.97 },
        { docId: 'pit', page: 0, value: '15.000.000', bbox: PT.income, confidence: 0.95 },
      ] },
      { key: 'pit', label: 'Thuế PIT (miễn)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '0 ₫', sources: [
        { docId: 'pit', page: 0, value: '0', bbox: PT.tax, confidence: 0.95 },
      ] },
      { key: 'net', label: 'Thực nhận (Gross − PIT)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '15.000.000 ₫', sources: [] },
      { key: 'policy', label: 'Miễn thuế / Cam kết', group: 'Chính sách', check: 'policy', kind: 'text', expected: 'Có bản cam kết', sources: [] },
    ],
  },
]
