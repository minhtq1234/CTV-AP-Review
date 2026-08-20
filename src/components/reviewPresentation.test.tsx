import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import type { RankedCtv } from '../ctv/checks'
import {
  fieldSelection,
  overviewSelection,
  type ReviewSelection,
} from '../logic/reviewSelection'
import type { MatchedBy, PacketReview } from '../upload/api'
import FolderFieldsPanel from './FolderFieldsPanel'
import FolderReview from './FolderReview'
import MatchKeyStrip from './MatchKeyStrip'
import PacketBoundaryWarning from './PacketBoundaryWarning'
import ReviewHeader from './ReviewHeader'

const ranked: RankedCtv[] = [{
  field: {
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
  },
  index: 0,
  verdict: 'match',
  actual: 'Giá trị mẫu',
  sources: [{
    verdict: 'match',
    source: {
      docId: 'contract',
      page: 0,
      value: 'Giá trị mẫu',
      bbox: { x: 100, y: 100, width: 200, height: 40 },
      confidence: 0.99,
    },
  }],
}]

const financialRow: RankedCtv = {
  field: {
    key: 'phi',
    label: 'Phí dịch vụ',
    group: 'Thanh toán',
    check: 'compare',
    kind: 'number',
    expected: '6111111',
    sources: [{
      docId: 'contract',
      page: 0,
      value: '6.111.111',
      bbox: { x: 100, y: 200, width: 180, height: 30 },
      confidence: 0.9,
    }],
  },
  index: 0,
  verdict: 'match',
  actual: '6.111.111',
  sources: [{
    verdict: 'match',
    source: {
      docId: 'contract',
      page: 0,
      value: '6.111.111',
      bbox: { x: 100, y: 200, width: 180, height: 30 },
      confidence: 0.9,
    },
  }],
}

const renderPanel = (
  review: PacketReview,
  rows: RankedCtv[] = ranked,
  selection: ReviewSelection = fieldSelection('field-a'),
) => renderToStaticMarkup(
  <FolderFieldsPanel
    ranked={rows}
    selection={selection}
    onSelectOverview={() => undefined}
    onSelectField={() => undefined}
    review={review}
    onToggleFlag={() => undefined}
    onOpenPacketRejection={() => undefined}
  />,
)

describe('flat field panel', () => {
  it('formats a financial Excel value as Vietnamese đồng', () => {
    const html = renderPanel(
      { done: false, fields: {}, rejection: null },
      [financialRow],
    )
    expect(html).toContain('Kê khai (Excel): <b>6.111.111 ₫</b>')
    expect(html).not.toContain('<b>6111111</b>')
  })

  it('keeps the field row but removes repetitive source pills', () => {
    const html = renderPanel({ done: false, fields: {}, rejection: null })
    expect(html).toContain('Trường mẫu')
    expect(html).not.toContain('Đối chiếu')
    expect(html).not.toContain('srcchip')
  })

  it('uses the full inactive and active flag action labels', () => {
    expect(renderPanel({ done: false, fields: {}, rejection: null })).toContain('⚑ Đánh dấu')
    expect(renderPanel({
      done: false,
      fields: { 'field-a': { seen: true, flag: { reason: '', note: '' } } },
      rejection: null,
    })).toContain('Bỏ đánh dấu')
  })

  it('shows only viewed or not-viewed status, regardless of AI verdict', () => {
    const reviewVerdictRows: RankedCtv[] = [{ ...ranked[0], verdict: 'review' }]
    const unseen = renderPanel({
      done: false, fields: {}, rejection: null,
    }, reviewVerdictRows)
    expect(unseen).toContain('Chưa xem')
    expect(unseen).not.toContain('cần xem')
    expect(unseen).not.toContain('✓')

    const seen = renderPanel({
      done: false,
      fields: { 'field-a': { seen: true, flag: null } },
      rejection: null,
    }, reviewVerdictRows)
    expect(seen).toContain('Đã xem')
    expect(seen).not.toContain('cần xem')
  })

  it('selects a row before opening its flag editor', () => {
    let selectedKey = ''
    let flaggedKey = ''
    const tree = FolderFieldsPanel({
      ranked,
      selection: fieldSelection('field-a'),
      onSelectOverview: () => undefined,
      onSelectField: key => { selectedKey = key },
      review: { done: false, fields: {}, rejection: null },
      onToggleFlag: key => { flaggedKey = key },
      onOpenPacketRejection: () => undefined,
    })

    const findFlagButton = (node: ReactNode): ReactElement | null => {
      if (Array.isArray(node)) {
        for (const child of node) {
          const match = findFlagButton(child)
          if (match) return match
        }
        return null
      }
      if (!isValidElement(node)) return null
      const props = node.props as {
        className?: string
        children?: ReactNode
      }
      if (props.className?.split(' ').includes('flag-btn')) return node
      return findFlagButton(props.children)
    }

    const flagButton = findFlagButton(tree)
    expect(flagButton).not.toBeNull()
    const props = flagButton!.props as {
      onClick: (event: { stopPropagation: () => void }) => void
    }
    props.onClick({ stopPropagation: () => undefined })

    expect(selectedKey).toBe('field-a')
    expect(flaggedKey).toBe('field-a')
  })

  it('renders selected Overview first without changing field totals', () => {
    const html = renderPanel(
      { done: false, fields: {}, rejection: null },
      ranked,
      overviewSelection(),
    )

    expect(html).toContain('data-review-selection="overview"')
    expect(html).toContain('Tổng quan')
    expect(html).toContain('Xem nhanh toàn bộ chứng từ')
    expect(html).toContain('Từ chối hồ sơ')
    expect(html.indexOf('Tổng quan')).toBeLessThan(html.indexOf('Trường mẫu'))
    expect(html).toContain('1 mục kiểm tra')
    expect(html).toContain('0/1 đã xem')
    expect(html).not.toContain('Từ chối gói hồ sơ')
  })

  it('renders a persistent rejection summary without disabling fields', () => {
    const html = renderPanel({
      done: true,
      fields: {
        'field-a': {
          seen: true,
          flag: { reason: 'sai', note: 'Giữ nguyên' },
        },
      },
      rejection: {
        reasons: ['missing_documents', 'missing_signature'],
        note: 'Bổ sung bộ hồ sơ',
      },
    })
    expect(html).toContain('Đã từ chối')
    expect(html).toContain('Thiếu chứng từ')
    expect(html).toContain('Thiếu chữ ký')
    expect(html).toContain('Bổ sung bộ hồ sơ')
    expect(html).toContain('Sửa lý do')
    expect(html).toContain('Trường mẫu')
    expect(html).toContain('Bỏ đánh dấu')
    expect(html).not.toContain('disabled=""')
  })
})

describe('review presentation', () => {
  it('opens on the package grid without publishing a field review', () => {
    const onReview = vi.fn()
    const html = renderToStaticMarkup(
      <FolderReview
        folder={{
          id: 'synthetic-overview',
          name: 'Synthetic CTV',
          product: 'Synthetic Product',
          status: 'pending',
          exempt: false,
          docs: [{
            id: 'contract',
            kind: 'contract',
            label: 'Synthetic contract',
            pages: [{ src: '/synthetic.svg', width: 1000, height: 1400 }],
          }],
          fields: [ranked[0].field],
        }}
        review={{ done: false, fields: {}, rejection: null }}
        onReview={onReview}
        onCommitReview={async () => undefined}
      />,
    )

    expect(onReview).not.toHaveBeenCalled()
    expect(html).toContain('aria-pressed="true" class="on">Dạng bảng')
    expect(html).toContain('aria-label="Dạng bảng đối chiếu chứng từ"')
    expect(html).not.toContain('class="panes"')
    expect(html).toContain('0/1 đã xem')
    expect(html).not.toContain('roster-callout')
  })

  it('uses the same formatted amount in the field row and bbox callout', () => {
    const field = financialRow.field
    const html = renderToStaticMarkup(
      <FolderReview
        folder={{
          id: 'synthetic',
          name: 'Synthetic CTV',
          product: 'Synthetic Product',
          status: 'pending',
          exempt: false,
          docs: [{
            id: 'contract',
            kind: 'contract',
            label: 'Synthetic contract',
            pages: [{ src: '/synthetic.svg', width: 1000, height: 1400 }],
          }],
          fields: [field],
        }}
        review={{ done: false, fields: {}, rejection: null }}
        onReview={() => undefined}
        onCommitReview={async () => undefined}
      />,
    )
    expect(html.match(/6\.111\.111 ₫/g)).toHaveLength(1)
    expect(html).not.toContain('>6111111<')
    expect(html).not.toContain('roster-callout')
  })
})

describe('packet boundary warning', () => {
  it('explains unresolved mixed-packet evidence', () => {
    const html = renderToStaticMarkup(
      <PacketBoundaryWarning assessment={{
        status: 'review',
        suspectedMultiplePackets: true,
        reasons: ['length-out-of-range', 'multiple-contract-starts'],
        candidateStarts: [121, 129],
      }} />,
    )

    expect(html).toContain('Nghi ngờ nhiều hồ sơ trong một gói')
    expect(html).toContain(
      'AI phát hiện ranh giới hoặc danh tính không nhất quán. Hãy kiểm tra và xác nhận ranh giới trước khi kết luận hồ sơ.',
    )
  })

  it('renders nothing for a clear packet boundary', () => {
    const html = renderToStaticMarkup(
      <PacketBoundaryWarning assessment={{
        status: 'clear',
        suspectedMultiplePackets: false,
        reasons: [],
        candidateStarts: [],
      }} />,
    )

    expect(html).toBe('')
  })
})

describe('mapping pill', () => {
  const labels: Record<MatchedBy, string> = {
    cccd: 'Khớp theo CCCD',
    name: 'Khớp theo họ tên',
    unmatched: 'Chưa khớp bảng kê',
    'no-roster': 'Không có bảng kê',
  }

  for (const [matchedBy, label] of Object.entries(labels) as [MatchedBy, string][]) {
    it(`renders ${matchedBy} as one compact approved label`, () => {
      const html = renderToStaticMarkup(
        <MatchKeyStrip
          matchedBy={matchedBy}
          ocr={{ cccd: 'synthetic', name: 'Synthetic Person' }}
          roster={{ cccd: 'other-synthetic', name: 'Other Synthetic Person' }}
        />,
      )
      expect(html).toContain(label)
      expect(html).not.toContain('<table')
    })
  }
})

describe('compact review header', () => {
  it('contains case return, packet identity, mapping, range, and packet navigation in one row', () => {
    const html = renderToStaticMarkup(
      <ReviewHeader
        name="Synthetic CTV"
        product="Synthetic Product"
        pages={[4, 7]}
        matchedBy="cccd"
        position={2}
        count={5}
        canPrevious
        canNext
        onBack={() => undefined}
        onPrevious={() => undefined}
        onNext={() => undefined}
      />,
    )
    expect(html).toContain('HỒ SƠ CTV')
    expect(html).toContain('Synthetic CTV')
    expect(html).toContain('Synthetic Product')
    expect(html).toContain('Trang 5–8')
    expect(html).toContain('Gói 3 / 5')
    expect(html).toContain('Khớp theo CCCD')
    expect(html.match(/<header/g)).toHaveLength(1)
  })
})
