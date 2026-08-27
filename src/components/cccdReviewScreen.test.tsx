import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { CccdCard, PacketMeta } from '../upload/api'
import { buildCccdReview } from '../logic/cccdReview'
import { CccdReviewView } from './CccdReviewScreen'

function packet(index: number, name: string): PacketMeta {
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
    review: { done: false, fields: {}, rejection: null },
    reviewFieldCount: 6,
  }
}

function card(cardId: string, attachedPacketIndex: number | null,
              overrides: Partial<CccdCard> = {}): CccdCard {
  return {
    cardId,
    state: attachedPacketIndex === null ? 'conflict' : 'exact',
    attachedPacketIndex,
    number: '',
    issues: [],
    sides: [{ side: 'front', width: 1059, height: 668 }],
    ...overrides,
  }
}

const packets = [packet(0, 'Synthetic A'), packet(1, 'Synthetic B')]

function render(cards: CccdCard[]) {
  return renderToStaticMarkup(
    <CccdReviewView
      caseId="case-1"
      caseName="FA-SYNTHETIC.pdf"
      review={buildCccdReview(packets, cards)}
      busy={false}
      error={null}
      onAssign={() => {}}
      onDetach={() => {}}
      onRetry={() => {}}
      onContinue={() => {}}
    />,
  )
}

describe('CccdReviewView', () => {
  it('shows all three counts, kept apart', () => {
    const html = render([card('card-00', 0), card('card-09', null)])
    expect(html).toContain('1 đã gắn')
    expect(html).toContain('1 chưa ghép')
    expect(html).toContain('1 gói chưa có thẻ')
  })

  it('lists a packet needing a card with an assign button', () => {
    const html = render([card('card-00', 0)])
    expect(html).toContain('Synthetic B')
    expect(html).toContain('Gán thẻ')
  })

  it('shows an unattached card with its reason, and no assign button of its own', () => {
    const html = render([
      card('card-00', 0),
      card('card-09', null, { state: 'conflict', issues: ['duplicate-cccd'] }),
    ])
    expect(html).toContain('Xung đột · Trùng số CCCD')
    expect(html).toContain('card-09')
    const orphan = html.match(
      /<li class="cccd-review-row cccd-review-orphan"[\s\S]*?<\/li>/,
    )?.[0] ?? ''
    expect(orphan).toContain('card-09')
    expect(orphan).not.toContain('<button')
  })

  it('renders attached packets inside a collapsed details element', () => {
    const html = render([card('card-00', 0), card('card-01', 1)])
    expect(html).toContain('<details')
    expect(html).not.toContain('<details open')
    expect(html).toContain('Đã gán (2)')
    expect(html).toContain('Gỡ')
    expect(html).toContain('width="1059"')
  })

  it('says so plainly when nothing needs action', () => {
    const html = render([card('card-00', 0), card('card-01', 1)])
    expect(html).toContain('Mọi gói đều đã có thẻ CCCD.')
  })

  it('always offers the way forward', () => {
    expect(render([])).toContain('Tiếp tục')
  })

  it('surfaces an error when one is passed', () => {
    const html = renderToStaticMarkup(
      <CccdReviewView
        caseId="case-1"
        caseName="FA-SYNTHETIC.pdf"
        review={buildCccdReview(packets, [])}
        busy={false}
        error="Gói này đã có ảnh CCCD. Gỡ ảnh cũ trước."
        onAssign={() => {}}
        onDetach={() => {}}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('Gỡ ảnh cũ trước')
  })

  it('shows a loading state and hides both sections when the review is not ready yet', () => {
    const html = renderToStaticMarkup(
      <CccdReviewView
        caseId="case-1"
        caseName="FA-SYNTHETIC.pdf"
        review={null}
        busy={true}
        error={null}
        onAssign={() => {}}
        onDetach={() => {}}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('Đang tải…')
    expect(html).not.toContain('Cần xử lý')
    expect(html).not.toContain('<details')
    expect(html).toContain('Tiếp tục')
  })

  it('offers a retry alongside the error while the review is not ready yet', () => {
    const html = renderToStaticMarkup(
      <CccdReviewView
        caseId="case-1"
        caseName="FA-SYNTHETIC.pdf"
        review={null}
        busy={true}
        error="Không tải được danh sách ảnh."
        onAssign={() => {}}
        onDetach={() => {}}
        onRetry={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('Không tải được danh sách ảnh.')
    expect(html).toContain('Thử lại')
  })
})
