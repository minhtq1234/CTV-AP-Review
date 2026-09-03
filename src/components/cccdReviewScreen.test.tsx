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

// Two sides by default: the one real case checked had 42/42 cards with both
// a front and a back, and having both is what makes the viewer trigger exist
// at all (CardThumb renders no button for a single-sided card). Tests that
// specifically want the single-sided, no-button case override `sides`.
function card(cardId: string, attachedPacketIndex: number | null,
              overrides: Partial<CccdCard> = {}): CccdCard {
  return {
    cardId,
    state: attachedPacketIndex === null ? 'conflict' : 'exact',
    attachedPacketIndex,
    number: '',
    issues: [],
    sides: [
      { side: 'front', width: 1059, height: 668 },
      { side: 'back', width: 1059, height: 668 },
    ],
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
      onDismissError={() => {}}
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
      /<li class="cccd-review-tile" aria-label="Ảnh card-09[\s\S]*?<\/li>/,
    )?.[0] ?? ''
    expect(orphan).toContain('card-09')
    // The only button here opens the viewer -- assigning this card still
    // has to go through the packet's own "Gán thẻ" row, not this one.
    const orphanButtons = orphan.match(/<button[\s\S]*?<\/button>/g) ?? []
    expect(orphanButtons).toHaveLength(1)
    expect(orphanButtons[0]).toContain('Xem cả hai mặt của ảnh CCCD card-09')
  })

  // Newly required: orphan cards used to be their own row shape
  // (.cccd-review-row.cccd-review-orphan); they are tiles now, in the
  // section's own grid, same as an attached card.
  it('renders an orphan card as a tile in the grid, not as a row', () => {
    const html = render([card('card-09', null)])
    const grid = html.match(/<ul class="cccd-review-grid">[\s\S]*?<\/ul>/)?.[0] ?? ''
    expect(grid).toContain('class="cccd-review-tile"')
    expect(grid).toContain('card-09')
    expect(html).not.toContain('cccd-review-orphan')
  })

  it("shows the orphan tile's head as the cardId, not an STT and name", () => {
    const html = render([card('card-09', null)])
    const tile = html.match(/<li class="cccd-review-tile"[\s\S]*?<\/li>/)?.[0] ?? ''
    const head = tile.match(/<div class="cccd-review-tile-head">[\s\S]*?<\/div>/)?.[0] ?? ''
    expect(head).toContain('>card-09<')
    expect(head).not.toContain('cccd-review-tile-stt')
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
  // only the image file itself knows its real size, so neither tile kind
  // may assert a width/height that came from that untrustworthy manifest.
  it('does not put the recorded (possibly transposed) dimensions on the orphan tile image', () => {
    const html = render([card('card-09', null)])
    const orphanButton = html.match(
      /<button[^>]*aria-label="Xem cả hai mặt của ảnh CCCD card-09"[^>]*>[\s\S]*?<\/button>/,
    )?.[0] ?? ''
    expect(orphanButton).not.toBe('')
    const img = orphanButton.match(/<img[^>]*>/)?.[0] ?? ''
    expect(img).not.toBe('')
    expect(img).not.toMatch(/\bwidth=/)
    expect(img).not.toMatch(/\bheight=/)
  })

  it('does not put the recorded (possibly transposed) dimensions on the attached tile image', () => {
    const html = render([card('card-00', 0)])
    const tileButton = html.match(
      /<button[^>]*aria-label="Xem cả hai mặt của ảnh CCCD card-00"[^>]*>[\s\S]*?<\/button>/,
    )?.[0] ?? ''
    expect(tileButton).not.toBe('')
    const img = tileButton.match(/<img[^>]*>/)?.[0] ?? ''
    expect(img).not.toBe('')
    expect(img).not.toMatch(/\bwidth=/)
    expect(img).not.toMatch(/\bheight=/)
  })

  // Re-targeted: this used to check the orphan row and the attached tile for
  // two DIFFERENT classes (.cccd-review-orphan-thumb vs .cccd-review-tile-
  // image), pinning that they did not share a box. That distinction is gone
  // by design this round -- both are the same tile now -- so this checks
  // the new, opposite invariant: both really do share the one class.
  it('renders every thumbnail inside a button with an accessible label, in both sections', () => {
    const html = render([
      card('card-00', 0),
      card('card-09', null, { state: 'conflict', issues: ['duplicate-cccd'] }),
    ])
    for (const cardId of ['card-00', 'card-09']) {
      expect(html).toContain(`aria-label="Xem cả hai mặt của ảnh CCCD ${cardId}"`)
    }
    const orphanButton = html.match(
      /<button[^>]*aria-label="Xem cả hai mặt của ảnh CCCD card-09"[^>]*>[\s\S]*?<\/button>/,
    )?.[0] ?? ''
    const tileButton = html.match(
      /<button[^>]*aria-label="Xem cả hai mặt của ảnh CCCD card-00"[^>]*>[\s\S]*?<\/button>/,
    )?.[0] ?? ''
    expect(orphanButton).toContain('class="cccd-review-tile-image"')
    expect(tileButton).toContain('class="cccd-review-tile-image"')
  })

  // The trigger no longer enlarges (images are already at native size) --
  // it reveals the back, so the label has to say that, not "full size".
  it('names both sides in the trigger label, not "full size"', () => {
    const html = render([card('card-00', 0)])
    expect(html).toContain('aria-label="Xem cả hai mặt của ảnh CCCD card-00"')
    expect(html).not.toContain('ở kích thước đầy đủ')
  })

  // The one most likely to regress: a single-sided card has nothing more to
  // reveal, so it must get no clickable trigger at all -- just the image.
  it('renders no viewer button for a single-sided card, only for a two-sided one', () => {
    const html = render([
      card('card-00', 0, { sides: [{ side: 'front', width: 1059, height: 668 }] }),
      card('card-01', 1),
    ])
    expect(html).not.toContain('aria-label="Xem cả hai mặt của ảnh CCCD card-00"')
    expect(html).toContain('aria-label="Xem cả hai mặt của ảnh CCCD card-01"')
    // The single-sided card's image still renders, just not inside a button.
    expect(html).toContain('alt="Ảnh CCCD card-00"')
    const plain = html.match(/<div class="cccd-review-tile-image">[\s\S]*?<\/div>/)?.[0] ?? ''
    expect(plain).toContain('card-00')
  })

  // Re-targeted: originally pinned that Cần xử lý was list-only and Đã gán
  // was grid-only. Cần xử lý now holds both shapes in one section (a list
  // for packets-needing-a-card, a grid for orphan tiles), so this pins the
  // piece that still matters -- a packet-needing-a-card row never becomes a
  // tile, and a card image never renders as a plain list row.
  it('keeps packets-needing-a-card as rows and every card image as a tile', () => {
    const html = render([card('card-00', 0), card('card-09', null)])
    const list = html.match(/<ul class="cccd-review-list">[\s\S]*?<\/ul>/)?.[0] ?? ''
    expect(list).toContain('Synthetic B')
    expect(list).not.toContain('cccd-review-tile')
    expect(html).toContain('<ul class="cccd-review-grid">')
    expect(html).not.toContain('cccd-review-orphan')
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
        error={{ text: 'Gói này đã có ảnh CCCD. Gỡ ảnh cũ trước.',
                 kind: 'mutate' }}
        onAssign={() => {}}
        onDetach={() => {}}
        onRetry={() => {}}
        onDismissError={() => {}}
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
        onDismissError={() => {}}
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
        error={{ text: 'Không tải được danh sách ảnh.', kind: 'load' }}
        onAssign={() => {}}
        onDetach={() => {}}
        onRetry={() => {}}
        onDismissError={() => {}}
        onContinue={() => {}}
      />,
    )
    expect(html).toContain('Không tải được danh sách ảnh.')
    expect(html).toContain('Thử lại')
  })
})

describe('when the card workbook could not be read', () => {
  const failed = { status: 'error' as const, candidates: 0, attached: 0,
                   unresolved: 0, errorCode: 'invalid-workbook' }

  it('says so, instead of looking like nothing has matched yet', () => {
    // Measured on a real case (cccdWorkbook.status "error", 0 candidates): the
    // screen rendered 25 rows and 25 "Gán thẻ" buttons against 0 card tiles,
    // with no mention of an error anywhere. Each button could only ever open an
    // empty picker.
    const html = renderToStaticMarkup(
      <CccdReviewView
        caseId="case-1"
        caseName="c1.pdf"
        review={null}
        busy={false}
        error={null}
        workbook={failed}
        onAssign={() => undefined}
        onDetach={() => undefined}
        onRetry={() => undefined}
        onDismissError={() => undefined}
        onContinue={() => undefined}
      />,
    )

    expect(html).toContain('Không đọc được file ảnh CCCD')
    expect(html).toContain('invalid-workbook')
    expect(html).toContain('role="alert"')
  })

  it('still offers the way forward, so the case is not a dead end', () => {
    const html = renderToStaticMarkup(
      <CccdReviewView
        caseId="case-1"
        caseName="c1.pdf"
        review={null}
        busy={false}
        error={null}
        workbook={failed}
        onAssign={() => undefined}
        onDetach={() => undefined}
        onRetry={() => undefined}
        onDismissError={() => undefined}
        onContinue={() => undefined}
      />,
    )

    expect(html).toContain('Tiếp tục')
  })

  it('says nothing when the workbook read fine', () => {
    const html = renderToStaticMarkup(
      <CccdReviewView
        caseId="case-1"
        caseName="c1.pdf"
        review={null}
        busy={false}
        error={null}
        workbook={{ status: 'ready', candidates: 25, attached: 7, unresolved: 18 }}
        onAssign={() => undefined}
        onDetach={() => undefined}
        onRetry={() => undefined}
        onDismissError={() => undefined}
        onContinue={() => undefined}
      />,
    )

    expect(html).not.toContain('Không đọc được file ảnh CCCD')
  })
})
