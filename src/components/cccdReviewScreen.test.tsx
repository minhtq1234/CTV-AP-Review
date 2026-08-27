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
    // The only button here opens the full-size viewer -- assigning this card
    // still has to go through the packet's own "Gán thẻ" row, not this one.
    const orphanButtons = orphan.match(/<button[\s\S]*?<\/button>/g) ?? []
    expect(orphanButtons).toHaveLength(1)
    expect(orphanButtons[0]).toContain('Xem ảnh CCCD card-09 ở kích thước đầy đủ')
  })

  it('renders attached packets inside a collapsed details element', () => {
    const html = render([card('card-00', 0), card('card-01', 1)])
    expect(html).toContain('<details')
    expect(html).not.toContain('<details open')
    expect(html).toContain('Đã gán (2)')
    expect(html).toContain('Gỡ')
  })

  // The recorded side dimensions are transposed on any case ingested before
  // fccded7 (the JPEG parser returned header order, height before width) --
  // only the image file itself knows its real size, so neither the row
  // thumbnail (Cần xử lý) nor the tile image (Đã gán) may assert a
  // width/height that came from that untrustworthy manifest. Re-targeted
  // from a single "the thumbnail" test into one per section, since an
  // attached card no longer renders a `.cccd-review-thumb` at all.
  it('does not put the recorded (possibly transposed) dimensions on the row thumbnail', () => {
    const html = render([card('card-09', null)])
    const thumb = html.match(/<img[^>]*class="cccd-review-thumb"[^>]*>/)?.[0] ?? ''
    expect(thumb).not.toBe('')
    expect(thumb).not.toMatch(/\bwidth=/)
    expect(thumb).not.toMatch(/\bheight=/)
  })

  it('does not put the recorded (possibly transposed) dimensions on the tile image', () => {
    const html = render([card('card-00', 0)])
    const tileButton = html.match(
      /<button[^>]*aria-label="Xem ảnh CCCD card-00[^"]*"[^>]*>[\s\S]*?<\/button>/,
    )?.[0] ?? ''
    expect(tileButton).not.toBe('')
    const img = tileButton.match(/<img[^>]*>/)?.[0] ?? ''
    expect(img).not.toBe('')
    expect(img).not.toMatch(/\bwidth=/)
    expect(img).not.toMatch(/\bheight=/)
  })

  // Re-targeted: this used to check both sections' thumbnails for the same
  // `cccd-review-thumb` class. Đã gán's tile image now fills the tile
  // instead (no fixed 160x101 box), so the two sections are checked for
  // their own, separate classes rather than one shared one.
  it('renders every thumbnail inside a button with an accessible label, in both sections', () => {
    const html = render([
      card('card-00', 0),
      card('card-09', null, { state: 'conflict', issues: ['duplicate-cccd'] }),
    ])
    for (const cardId of ['card-00', 'card-09']) {
      const label = `Xem ảnh CCCD ${cardId} ở kích thước đầy đủ`
      expect(html).toContain(`aria-label="${label}"`)
    }
    // Cần xử lý keeps the small, fixed-size row thumbnail.
    const orphanButton = html.match(
      /<button[^>]*aria-label="Xem ảnh CCCD card-09[^"]*"[^>]*>[\s\S]*?<\/button>/,
    )?.[0] ?? ''
    expect(orphanButton).toContain('class="cccd-review-thumb"')
    // Đã gán's tile image fills the tile -- a different class, and the
    // fixed-size row thumbnail class must not leak onto it.
    const tileButton = html.match(
      /<button[^>]*aria-label="Xem ảnh CCCD card-00[^"]*"[^>]*>[\s\S]*?<\/button>/,
    )?.[0] ?? ''
    expect(tileButton).toContain('class="cccd-review-tile-image"')
    expect(tileButton).not.toContain('cccd-review-thumb')
  })

  // A future change must not silently merge the two sections' markup back
  // together -- Cần xử lý is an unchanged list, Đã gán is now a tile grid.
  it('keeps the exceptions list and the attached grid as separate structures', () => {
    const html = render([card('card-00', 0), card('card-09', null)])
    expect(html).toContain('<ul class="cccd-review-list">')
    expect(html).toContain('<ul class="cccd-review-grid">')
  })

  it('does not render the full-size card dialog until a thumbnail is clicked', () => {
    const html = render([card('card-00', 0)])
    expect(html).not.toContain('role="dialog"')
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
