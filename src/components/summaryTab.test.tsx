import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { SummaryCriterion } from '../upload/api'
import { SummaryCriterionCard } from './SummaryTab'

function criterion(overrides: Partial<SummaryCriterion> = {}): SummaryCriterion {
  return {
    stt: 31,
    code: '31',
    label: 'Không trùng thanh toán cùng CTV + số tiền + kỳ thanh toán',
    group: 'TH',
    kind: 'compare',
    docs: ['Bảng kê', 'Hợp đồng', 'BBNT'],
    how: 'Tìm các dòng có cùng CTV hoặc CCCD/MST, cùng số tiền, nội dung dịch '
      + 'vụ và kỳ thanh toán trong một bộ hồ sơ. Chỉ cảnh báo trùng, không tự '
      + 'động xóa dòng.',
    status: 'no',
    message: 'Có dấu hiệu thanh toán trùng: 9 CTV có nhiều hơn một gói.',
    detail: ['gói 3 + 4', 'gói 8 + 9'],
    ...overrides,
  }
}

describe('SummaryCriterionCard', () => {
  it('shows the finding, not just the verdict', () => {
    // Acc's own requirement: "Không chỉ báo 'Không khớp'; phải nêu trường sai,
    // giá trị tại từng chứng từ, chênh lệch và nội dung cần kiểm tra lại."
    const html = renderToStaticMarkup(
      <SummaryCriterionCard criterion={criterion()} />,
    )

    expect(html).toContain('9 CTV có nhiều hơn một gói')
    expect(html).toContain('gói 3 + 4')
    expect(html).toContain('gói 8 + 9')
  })

  it('names the documents the criterion reconciles across', () => {
    const html = renderToStaticMarkup(
      <SummaryCriterionCard criterion={criterion()} />,
    )
    expect(html).toContain('Bảng kê · Hợp đồng · BBNT')
  })

  it('labels a pending criterion as unchecked, never as passing', () => {
    const html = renderToStaticMarkup(
      <SummaryCriterionCard criterion={criterion({ status: 'pending' })} />,
    )

    expect(html).toContain('Chưa kiểm tra được')
    expect(html).not.toContain('Đạt')
    expect(html).toContain('summary-criterion unknown')
  })

  it('keeps Acc’s instruction one click away', () => {
    const html = renderToStaticMarkup(
      <SummaryCriterionCard criterion={criterion()} />,
    )

    expect(html).toContain('Cách kiểm tra')
    expect(html).toContain('aria-expanded="false"')
    // collapsed by default, so the card stays scannable
    expect(html).not.toContain('Chỉ cảnh báo trùng')
  })

  it('gives the status an accessible name tied to the criterion', () => {
    const html = renderToStaticMarkup(
      <SummaryCriterionCard criterion={criterion({ status: 'rv' })} />,
    )

    expect(html).toContain(
      'aria-label="Không trùng thanh toán cùng CTV + số tiền + kỳ thanh toán: '
      + 'Cần người kiểm tra"',
    )
  })

  it('renders a clean criterion without an empty detail list', () => {
    const html = renderToStaticMarkup(
      <SummaryCriterionCard
        criterion={criterion({ status: 'ok', detail: [] })}
      />,
    )

    expect(html).toContain('Đạt')
    expect(html).not.toContain('summary-criterion-detail')
  })
})
