import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { PacketMeta, PacketReview } from '../upload/api'
import type { CaseDetail as CaseDetailT } from '../upload/api'
import CaseDetail, {
  PacketListRow,
  PacketDashboardView,
  type PacketDashboardViewProps,
} from './CaseDetail'

function review(overrides: Partial<PacketReview> = {}): PacketReview {
  return {
    done: false,
    fields: {},
    rejection: null,
    ...overrides,
  }
}

function packet(
  index: number,
  name: string,
  packetReview: PacketReview,
  overrides: Partial<PacketMeta> = {},
): PacketMeta {
  return {
    index,
    name,
    pages: [index * 2, index * 2 + 1],
    n_pages: 2,
    confidence: 'green',
    flags: [],
    matchedBy: 'cccd',
    ocrIdentity: { cccd: 'synthetic', name },
    rosterIdentity: { cccd: 'synthetic', name },
    review: packetReview,
    reviewFieldCount: 6,
    taxCommitmentDetected: false,
    boundaryAssessment: {
      status: 'clear',
      suspectedMultiplePackets: false,
      reasons: [],
      candidateStarts: [],
    },
    ...overrides,
  }
}

const packets: PacketMeta[] = [
  packet(0, 'Synthetic Unseen', review(), {
    dashboardSummary: {
      taxCommitmentDetected: true,
      documents: { present: 5, total: 5, missing: [] },
      aiResult: 'mismatch',
    },
  } as any),
  packet(1, 'Synthetic Reviewing', review({
    fields: {
      a: { seen: true, flag: null },
      b: { seen: true, flag: null },
    },
  }), {
    matchedBy: 'name',
    dashboardSummary: {
      taxCommitmentDetected: false,
      documents: { present: 4, total: 4, missing: [] },
      aiResult: 'review',
    },
  } as any),
  packet(2, 'Synthetic Completed', review({ done: true }), {
    flags: ['auto-merged'],
    dashboardSummary: {
      taxCommitmentDetected: false,
      documents: { present: 4, total: 4, missing: [] },
      aiResult: 'match',
    },
  } as any),
  packet(3, 'Synthetic Field Flagged', review({
    fields: {
      a: {
        seen: true,
        flag: { reason: 'synthetic one', note: '' },
      },
      b: {
        seen: false,
        flag: { reason: 'synthetic two', note: '' },
      },
    },
  }), {
    dashboardSummary: {
      taxCommitmentDetected: false,
      documents: { present: 3, total: 4, missing: ['BBNT'] },
      aiResult: 'mismatch',
    },
  } as any),
  packet(4, 'Synthetic Rejected', review({
    done: true,
    fields: {
      a: {
        seen: true,
        flag: { reason: 'synthetic field flag', note: '' },
      },
    },
    rejection: { reasons: ['missing_documents'], note: 'Synthetic note' },
  }), { matchedBy: 'unmatched', flags: ['roster-unmatched'] }),
]

function renderView(overrides: Partial<PacketDashboardViewProps> = {}): string {
  return renderToStaticMarkup(
    <PacketDashboardView
      packets={packets}
      filter="all"
      attentionFirst={false}
      onFilter={() => undefined}
      onAttentionFirst={() => undefined}
      onOpenPacket={() => undefined}
      {...overrides}
    />,
  )
}

function textOf(node: ReactNode): string {
  if (typeof node === 'string' || typeof node === 'number') return String(node)
  if (Array.isArray(node)) return node.map(textOf).join('')
  if (!isValidElement(node)) return ''
  return textOf((node.props as { children?: ReactNode }).children)
}

function findButton(
  node: ReactNode,
  predicate: (element: ReactElement) => boolean,
): ReactElement | null {
  if (Array.isArray(node)) {
    for (const child of node) {
      const match = findButton(child, predicate)
      if (match) return match
    }
    return null
  }
  if (!isValidElement(node)) return null
  if (node.type === 'button' && predicate(node)) return node
  return findButton((node.props as { children?: ReactNode }).children, predicate)
}

describe('packet dashboard presentation', () => {
  it('renders a list header, exact filters, exclusive counts, lifecycle rows, and summaries', () => {
    const html = renderView()
    expect(html).toContain('Tất cả')
    expect(html).toContain('Chưa xem')
    expect(html).toContain('Đang xem')
    expect(html).toContain('Đã xong')
    expect(html).toContain('Flagged')
    expect(html).toContain('Tất cả</span><span class="packet-filter-count">5')
    expect(html).toContain('Chưa xem</span><span class="packet-filter-count">1')
    expect(html).toContain('Đang xem</span><span class="packet-filter-count">1')
    expect(html).toContain('Đã xong</span><span class="packet-filter-count">1')
    expect(html).toContain('Flagged</span><span class="packet-filter-count">2')
    expect(html).toContain('STT')
    expect(html).toContain('Họ và tên')
    expect(html).toContain('Phạm vi trang')
    expect(html).toContain('Trạng thái')
    expect(html).toContain('Kết quả kiểm tra')
    expect(html).toContain('Cam kết thuế')
    expect(html).toContain('Chứng từ')
    expect(html).toContain('Kết quả AI')
    expect(html).toContain('Đầy đủ (5/5)')
    expect(html).toContain('Thiếu (3/4)')
    expect(html).toContain('Thiếu: BBNT')
    expect(html).toContain('Không hợp lệ')
    expect(html).toContain('Cần review')
    expect(html).toContain('Hợp lệ')
    expect(html).toContain('packet-list-row unseen')
    expect(html).toContain('packet-list-row reviewing')
    expect(html).toContain('packet-list-row completed')
    expect(html).toContain('packet-list-row flagged')
    expect(html).not.toContain('packet-grid')
    expect(html).not.toContain('packet-card ')
    expect(html).toContain('2/6 đã xem')
    expect(html).toContain('2 trường đã đánh dấu')
    expect(html).toContain('Đã từ chối · Thiếu chứng từ')
    expect(html).not.toContain('Đã từ chối · Thiếu chứng từ · 1 trường')
  })

  it('uses a progress fallback and keeps attention separate from lifecycle', () => {
    const fallbackPackets = packets.map(packet => (
      packet.index === 1 ? { ...packet, reviewFieldCount: 0 } : packet
    ))
    const html = renderView({ packets: fallbackPackets })
    expect(html).toContain('2 trường đã xem')
    expect(html).toContain('packet-list-row reviewing')
    expect(html).toContain('packet-attention')
    expect(html).toContain('Chỉ khớp theo tên')
    expect(html).toContain('Cần xác nhận ranh giới')
    expect(html).toContain('Không khớp bảng kê')
  })

  it('renders tax commitment as included or not included without a read state', () => {
    const included = renderToStaticMarkup(
      <PacketListRow
        packet={{
          ...packets[0],
          taxCommitmentDetected: true,
          dashboardSummary: undefined,
        } as any}
        onOpen={() => undefined}
      />,
    )
    const notIncluded = renderToStaticMarkup(
      <PacketListRow
        packet={{
          ...packets[0],
          taxCommitmentDetected: false,
          dashboardSummary: undefined,
        } as any}
        onOpen={() => undefined}
      />,
    )

    expect(included).toContain('packet-tax-commitment')
    expect(included).toContain('Có')
    expect(notIncluded).toContain('packet-tax-commitment')
    expect(notIncluded).toContain('Không')
    expect(included).toContain('packet-ai-pill review')
    expect(included).toContain('Cần review')
    expect(notIncluded).toContain('packet-ai-pill review')
    expect(notIncluded).toContain('Cần review')
    expect((included.match(/Chưa đọc/g) ?? [])).toHaveLength(1)
    expect((notIncluded.match(/Chưa đọc/g) ?? [])).toHaveLength(1)
  })

  it('surfaces a suspected mixed packet as an AI review exception', () => {
    const html = renderToStaticMarkup(
      <PacketListRow
        packet={{
          ...packets[0],
          flags: ['length-out-of-range'],
          boundaryAssessment: {
            status: 'review',
            suspectedMultiplePackets: true,
            reasons: ['length-out-of-range', 'multiple-contract-starts'],
            candidateStarts: [121, 129],
          },
          dashboardSummary: {
            taxCommitmentDetected: true,
            documents: { present: 5, total: 5, missing: [] },
            aiResult: 'review',
          },
        }}
        onOpen={() => undefined}
      />,
    )

    expect(html).toContain('Cần review')
    expect(html).toContain('Nghi ngờ nhiều hồ sơ trong một gói')
  })

  it('filters controlled packet rows and renders an explicit empty state', () => {
    const reviewing = renderView({ filter: 'reviewing' })
    expect(reviewing).toContain('Synthetic Reviewing')
    expect(reviewing).not.toContain('Synthetic Unseen')
    expect(reviewing).not.toContain('Synthetic Completed')

    const empty = renderView({
      packets: packets.filter(packet => packet.index !== 2),
      filter: 'completed',
    })
    expect(empty).toContain('Không có gói hồ sơ ở trạng thái này.')
  })

  it('sends filter and priority changes through the real controls', () => {
    let selected = ''
    let priority = false
    const tree = PacketDashboardView({
      packets,
      filter: 'all',
      attentionFirst: false,
      onFilter: filter => { selected = filter },
      onAttentionFirst: active => { priority = active },
      onOpenPacket: () => undefined,
    })
    const reviewing = findButton(tree, element => textOf(element).includes('Đang xem'))
    const attention = findButton(tree, element => textOf(element).includes('Cần chú ý trước'))
    expect(reviewing).not.toBeNull()
    expect(attention).not.toBeNull()

    ;(reviewing!.props as { onClick: () => void }).onClick()
    ;(attention!.props as { onClick: () => void }).onClick()

    expect(selected).toBe('reviewing')
    expect(priority).toBe(true)
  })

  it('stably prioritizes attention, restores base order, and keeps rows clickable', () => {
    const base = renderView()
    const prioritized = renderView({ attentionFirst: true })
    expect(base.indexOf('Synthetic Unseen'))
      .toBeLessThan(base.indexOf('Synthetic Reviewing'))
    expect(prioritized.indexOf('Synthetic Reviewing'))
      .toBeLessThan(prioritized.indexOf('Synthetic Completed'))
    expect(prioritized.indexOf('Synthetic Completed'))
      .toBeLessThan(prioritized.indexOf('Synthetic Rejected'))
    expect(prioritized.indexOf('Synthetic Rejected'))
      .toBeLessThan(prioritized.indexOf('Synthetic Unseen'))

    let opened = -1
    const tree = PacketListRow({
      packet: packets[1],
      onOpen: index => { opened = index },
    })
    const row = findButton(tree, element => (
      String((element.props as { className?: string }).className)
        .includes('packet-list-row')
    ))
    expect(row).not.toBeNull()
    ;(row!.props as { onClick: () => void }).onClick()
    expect(opened).toBe(1)
  })

  it('re-derives counts and membership from a newly saved review', () => {
    const before = renderView({ packets: [packets[0]], filter: 'unseen' })
    expect(before).toContain('Chưa xem</span><span class="packet-filter-count">1')
    expect(before).toContain('Synthetic Unseen')

    const saved = {
      ...packets[0],
      review: review({ done: true }),
    }
    const after = renderView({ packets: [saved], filter: 'unseen' })
    expect(after).toContain('Chưa xem</span><span class="packet-filter-count">0')
    expect(after).toContain('Đã xong</span><span class="packet-filter-count">1')
    expect(after).not.toContain('Synthetic Unseen')
    expect(after).toContain('Không có gói hồ sơ ở trạng thái này.')
  })
})

describe('CCCD aggregate summary', () => {
  it('renders aggregate counts without changing v1 dashboard controls', () => {
    const detail: CaseDetailT = {
      id: 'synthetic-case',
      name: 'Synthetic Case',
      createdAt: null,
      status: 'ready',
      pdfName: 'packet.pdf',
      rosterName: 'roster.xlsx',
      cccdName: 'cards.xlsx',
      cccdSummary: {
        status: 'ready',
        candidates: 3,
        attached: 2,
        unresolved: 1,
      },
      summary: {
        found: packets.length,
        roster_n: packets.length,
        matched: packets.length,
        auto_merged: 0,
      },
      error: null,
      packets,
      progress: { done: 1, total: packets.length, flagged: 2 },
      boundaryStatus: { status: 'clear', packetIndexes: [], reasons: [] },
      publicationBlocked: false,
    }

    const html = renderToStaticMarkup(
      <CaseDetail
        detail={detail}
        onOpenPacket={() => undefined}
        onBack={() => undefined}
        onExport={() => undefined}
        onReviewBoundary={() => undefined}
      />,
    )

    expect(html).toContain('CCCD: 2 đã gắn · 1 chưa ghép')
    expect(html).toContain('Cần chú ý trước')
    expect(html).toContain('Xuất báo cáo gửi lại')
  })

  it('shows boundary review only for unresolved review status', () => {
    const base: CaseDetailT = {
      id: 'synthetic-case',
      name: 'Synthetic Case',
      createdAt: null,
      status: 'ready',
      pdfName: 'packet.pdf',
      rosterName: null,
      cccdName: null,
      cccdSummary: null,
      summary: null,
      error: null,
      packets,
      progress: { done: 0, total: packets.length, flagged: 0 },
      boundaryStatus: { status: 'clear', packetIndexes: [], reasons: [] },
      publicationBlocked: false,
    }
    const renderDetail = (detail: CaseDetailT) => renderToStaticMarkup(
      <CaseDetail
        detail={detail}
        onOpenPacket={() => undefined}
        onBack={() => undefined}
        onExport={() => undefined}
        onReviewBoundary={() => undefined}
      />,
    )

    expect(renderDetail(base)).not.toContain('Kiểm tra ranh giới')
    expect(renderDetail({
      ...base,
      boundaryStatus: {
        status: 'review',
        packetIndexes: [1],
        reasons: ['multiple-contract-starts'],
      },
      publicationBlocked: true,
    })).toContain('Kiểm tra ranh giới')
    expect(renderDetail({
      ...base,
      boundaryStatus: {
        status: 'accepted',
        packetIndexes: [1],
        reasons: ['multiple-contract-starts'],
      },
    })).not.toContain('Kiểm tra ranh giới')
  })

  it('labels an accepted source packet as reviewer-confirmed', () => {
    const html = renderToStaticMarkup(
      <PacketListRow
        packet={{
          ...packets[0],
          boundaryAssessment: {
            status: 'accepted',
            suspectedMultiplePackets: true,
            reasons: ['multiple-contract-starts'],
            candidateStarts: [0, 8],
          },
        }}
        onOpen={() => undefined}
      />,
    )

    expect(html).toContain('Ranh giới đã xác nhận')
    expect(html).not.toContain('Nghi ngờ nhiều hồ sơ trong một gói')
  })
})
