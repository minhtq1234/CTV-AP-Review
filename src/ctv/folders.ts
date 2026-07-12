import type { CtvFolder } from './types'

// Hand-made folders: synthetic evidence documents (public/folders/<id>/*.svg) plus the
// Excel-row "claimed" values and seeded AI extractions (value + which doc + box + confidence).
const CARD = { width: 1010, height: 636 }
const A4 = { width: 1010, height: 1400 }

export const folders: CtvFolder[] = [
  {
    id: 'le-thi-mai-anh',
    name: 'Lê Thị Mai Anh',
    product: 'Crossfire: Legends',
    status: 'pending',
    exempt: false,
    docs: [
      { id: 'id_front', kind: 'id_front', label: 'CCCD mặt trước', src: '/folders/le-thi-mai-anh/cccd-front.svg', ...CARD },
      { id: 'id_back', kind: 'id_back', label: 'CCCD mặt sau', src: '/folders/le-thi-mai-anh/cccd-back.svg', ...CARD },
      { id: 'contract', kind: 'contract', label: 'Hợp đồng dịch vụ', src: '/folders/le-thi-mai-anh/contract.svg', ...A4 },
    ],
    fields: [
      { key: 'name', label: 'Họ và tên', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'Lê Thị Mai Anh',
        extract: { value: 'LÊ THỊ MAI ANH', docId: 'id_front', bbox: { x: 315, y: 318, width: 475, height: 44 }, confidence: 0.96 } },
      { key: 'cccd', label: 'Số CCCD', group: 'Danh tính', check: 'compare', kind: 'text', expected: '079198004321',
        extract: { value: '079198004321', docId: 'id_front', bbox: { x: 435, y: 224, width: 305, height: 44 }, confidence: 0.98 } },
      { key: 'dob', label: 'Ngày sinh', group: 'Danh tính', check: 'compare', kind: 'date', expected: '03/05/1998',
        extract: { value: '03/05/1998', docId: 'id_front', bbox: { x: 555, y: 372, width: 175, height: 34 }, confidence: 0.97 } },
      { key: 'expiry', label: 'Hiệu lực CCCD', group: 'Danh tính', check: 'expiry', kind: 'date', expected: 'Còn hiệu lực',
        extract: { value: '03/05/2023', docId: 'id_front', bbox: { x: 245, y: 574, width: 175, height: 34 }, confidence: 0.92 } },

      { key: 'bank_acct', label: 'Số tài khoản', group: 'Ngân hàng', check: 'compare', kind: 'text', expected: '19001234567',
        extract: { value: '0071000998877', docId: 'contract', bbox: { x: 235, y: 495, width: 285, height: 34 }, confidence: 0.95 } },
      { key: 'bank_name', label: 'Ngân hàng', group: 'Ngân hàng', check: 'compare', kind: 'name', expected: 'Techcombank',
        extract: { value: 'Vietcombank - CN Kỳ Đồng, TP.HCM', docId: 'contract', bbox: { x: 295, y: 535, width: 445, height: 34 }, confidence: 0.9 } },

      { key: 'gross', label: 'Phí dịch vụ (Gross)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '10.000.000 ₫',
        extract: { value: '10.000.000', docId: 'contract', bbox: { x: 335, y: 822, width: 235, height: 36 }, confidence: 0.97 } },
      { key: 'pit', label: 'Thuế PIT (10%)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '1.000.000 ₫', extract: null },
      { key: 'net', label: 'Thực nhận (Gross − PIT)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '9.000.000 ₫', extract: null },

      { key: 'policy', label: 'Miễn thuế / Cam kết', group: 'Chính sách', check: 'policy', kind: 'text', expected: 'Khấu trừ 10%', extract: null },
    ],
  },
  {
    id: 'tran-minh-khoa',
    name: 'Trần Minh Khoa',
    product: 'Play Together',
    status: 'pending',
    exempt: false,
    docs: [
      { id: 'id_front', kind: 'id_front', label: 'CCCD mặt trước', src: '/folders/tran-minh-khoa/cccd-front.svg', ...CARD },
      { id: 'id_back', kind: 'id_back', label: 'CCCD mặt sau', src: '/folders/tran-minh-khoa/cccd-back.svg', ...CARD },
      { id: 'contract', kind: 'contract', label: 'Hợp đồng dịch vụ', src: '/folders/tran-minh-khoa/contract.svg', ...A4 },
    ],
    fields: [
      { key: 'name', label: 'Họ và tên', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'Trần Minh Khoa',
        extract: { value: 'TRẦN MINH KHOA', docId: 'id_front', bbox: { x: 315, y: 318, width: 475, height: 44 }, confidence: 0.96 } },
      { key: 'cccd', label: 'Số CCCD', group: 'Danh tính', check: 'compare', kind: 'text', expected: '079200011234',
        extract: { value: '079200011234', docId: 'id_front', bbox: { x: 435, y: 224, width: 305, height: 44 }, confidence: 0.97 } },
      { key: 'dob', label: 'Ngày sinh', group: 'Danh tính', check: 'compare', kind: 'date', expected: '14/03/2000',
        extract: { value: '14/03/2000', docId: 'id_front', bbox: { x: 555, y: 372, width: 175, height: 34 }, confidence: 0.98 } },
      { key: 'expiry', label: 'Hiệu lực CCCD', group: 'Danh tính', check: 'expiry', kind: 'date', expected: 'Còn hiệu lực',
        extract: { value: '14/03/2033', docId: 'id_front', bbox: { x: 245, y: 574, width: 175, height: 34 }, confidence: 0.95 } },

      { key: 'bank_acct', label: 'Số tài khoản', group: 'Ngân hàng', check: 'compare', kind: 'text', expected: '0071000512345',
        extract: { value: '0071000512345', docId: 'contract', bbox: { x: 235, y: 495, width: 285, height: 34 }, confidence: 0.96 } },
      { key: 'bank_name', label: 'Ngân hàng', group: 'Ngân hàng', check: 'compare', kind: 'name', expected: 'Vietcombank',
        extract: { value: 'Vietcombank - CN Quận 1, TP.HCM', docId: 'contract', bbox: { x: 295, y: 535, width: 445, height: 34 }, confidence: 0.93 } },

      { key: 'gross', label: 'Phí dịch vụ (Gross)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '8.000.000 ₫',
        extract: { value: '8.000.000', docId: 'contract', bbox: { x: 335, y: 822, width: 235, height: 36 }, confidence: 0.97 } },
      { key: 'pit', label: 'Thuế PIT (10%)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '800.000 ₫', extract: null },
      { key: 'net', label: 'Thực nhận (Gross − PIT)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '7.200.000 ₫', extract: null },

      { key: 'policy', label: 'Miễn thuế / Cam kết', group: 'Chính sách', check: 'policy', kind: 'text', expected: 'Khấu trừ 10%', extract: null },
    ],
  },
  {
    id: 'pham-quoc-hung',
    name: 'Phạm Quốc Hưng',
    product: 'Danh Tướng 3Q',
    status: 'pending',
    exempt: true,
    docs: [
      { id: 'id_front', kind: 'id_front', label: 'CCCD mặt trước', src: '/folders/pham-quoc-hung/cccd-front.svg', ...CARD },
      { id: 'id_back', kind: 'id_back', label: 'CCCD mặt sau', src: '/folders/pham-quoc-hung/cccd-back.svg', ...CARD },
      { id: 'contract', kind: 'contract', label: 'Hợp đồng dịch vụ', src: '/folders/pham-quoc-hung/contract.svg', ...A4 },
    ],
    fields: [
      { key: 'name', label: 'Họ và tên', group: 'Danh tính', check: 'compare', kind: 'name', expected: 'Phạm Quốc Hưng',
        extract: { value: 'PHẠM QUỐC HƯNG', docId: 'id_front', bbox: { x: 315, y: 318, width: 475, height: 44 }, confidence: 0.95 } },
      { key: 'cccd', label: 'Số CCCD', group: 'Danh tính', check: 'compare', kind: 'text', expected: '079090003210',
        extract: { value: '079090003210', docId: 'id_front', bbox: { x: 435, y: 224, width: 305, height: 44 }, confidence: 0.55 } },
      { key: 'dob', label: 'Ngày sinh', group: 'Danh tính', check: 'compare', kind: 'date', expected: '22/09/1990',
        extract: { value: '22/09/1990', docId: 'id_front', bbox: { x: 555, y: 372, width: 175, height: 34 }, confidence: 0.9 } },
      { key: 'expiry', label: 'Hiệu lực CCCD', group: 'Danh tính', check: 'expiry', kind: 'date', expected: 'Còn hiệu lực',
        extract: { value: '22/09/2030', docId: 'id_front', bbox: { x: 245, y: 574, width: 175, height: 34 }, confidence: 0.94 } },

      { key: 'bank_acct', label: 'Số tài khoản', group: 'Ngân hàng', check: 'compare', kind: 'text', expected: '0451000778899',
        extract: { value: '0451000778899', docId: 'contract', bbox: { x: 235, y: 495, width: 285, height: 34 }, confidence: 0.95 } },
      { key: 'bank_name', label: 'Ngân hàng', group: 'Ngân hàng', check: 'compare', kind: 'name', expected: 'ACB',
        extract: { value: 'ACB - CN Tân Bình, TP.HCM', docId: 'contract', bbox: { x: 295, y: 535, width: 445, height: 34 }, confidence: 0.92 } },

      { key: 'gross', label: 'Phí dịch vụ (Gross)', group: 'Thanh toán', check: 'compare', kind: 'number', expected: '15.000.000 ₫',
        extract: { value: '15.000.000', docId: 'contract', bbox: { x: 335, y: 822, width: 235, height: 36 }, confidence: 0.97 } },
      { key: 'pit', label: 'Thuế PIT (miễn)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '0 ₫', extract: null },
      { key: 'net', label: 'Thực nhận (Gross − PIT)', group: 'Thanh toán', check: 'math', kind: 'number', expected: '15.000.000 ₫', extract: null },

      { key: 'policy', label: 'Miễn thuế / Cam kết', group: 'Chính sách', check: 'policy', kind: 'text', expected: 'Có bản cam kết', extract: null },
    ],
  },
]
