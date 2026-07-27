import { isValidElement } from 'react'
import type { ReactElement, ReactNode } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { PacketMeta, PacketReview } from '../upload/api'
import {
  PacketCard,
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
    ...overrides,
  }
}

const packets: PacketMeta[] = [
  packet(0, 'Synthetic Unseen', review()),
  packet(1, 'Synthetic Reviewing', review({
    fields: {
      a: { seen: true, flag: null },
      b: { seen: true, flag: null },
    },
  }), { matchedBy: 'name' }),
  packet(2, 'Synthetic Completed', review({ done: true }), {
    flags: ['auto-merged'],
  }),
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
  })),
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
  it('renders exact filters, exclusive counts, lifecycle classes, and summaries', () => {
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
    expect(html).toContain('packet-card unseen')
    expect(html).toContain('packet-card reviewing')
    expect(html).toContain('packet-card completed')
    expect(html).toContain('packet-card flagged')
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
    expect(html).toContain('packet-card reviewing')
    expect(html).toContain('packet-attention')
    expect(html).toContain('Chỉ khớp theo tên')
    expect(html).toContain('Cần xác nhận ranh giới')
    expect(html).toContain('Không khớp bảng kê')
  })

  it('filters controlled packet cards and renders an explicit empty state', () => {
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

  it('stably prioritizes attention, restores base order, and keeps cards clickable', () => {
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
    const tree = PacketCard({
      packet: packets[1],
      onOpen: index => { opened = index },
    })
    const card = findButton(tree, element => (
      String((element.props as { className?: string }).className)
        .includes('packet-card')
    ))
    expect(card).not.toBeNull()
    ;(card!.props as { onClick: () => void }).onClick()
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
