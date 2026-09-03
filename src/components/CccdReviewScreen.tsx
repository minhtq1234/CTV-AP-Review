// Ver 3 step 1: the reviewer confirms which CCCD card belongs to which packet
// before opening the packet list. Exceptions first; everything already attached
// sits behind a collapsed section, so a wrong automatic match is still findable.
import { useCallback, useEffect, useRef, useState } from 'react'
import { assignCccdCard, cccdCardImageUrl, listCccdCards } from '../upload/api'
import type { CccdCard, CccdSummary, PacketMeta } from '../upload/api'
import { buildCccdReview } from '../logic/cccdReview'
import {
  describeCard,
  type CccdAttachedRow,
  type CccdCardRow,
  type CccdPacketRow,
  type CccdReview,
} from '../logic/cccdReview'
import CccdCardPicker from './CccdCardPicker'

export interface CccdReviewViewProps {
  caseId: string
  caseName: string
  /** Null before the first load resolves — nothing is known yet, so nothing
   * about which packets need a card should be claimed yet either. */
  review: CccdReview | null
  busy: boolean
  error: string | null
  /** The ingest's verdict on the card workbook, when there is one. */
  workbook?: CccdSummary | null
  onAssign: (packetIndex: number, packetLabel: string) => void
  onDetach: (cardId: string) => void
  onRetry: () => void
  onContinue: () => void
}

// One shape for every card image now: capped at native size, never
// upscaled (see .cccd-review-tile-image img). The trigger only exists when
// there is a second side to reveal -- with images capped at native size,
// clicking can no longer make the image bigger, only show the back, so a
// single-sided card (nothing more to show) renders a plain image, no
// button: a click that would change nothing is the same class of lie as
// the shrink-on-click affordance this replaces.
function CardThumb({ caseId, card }: { caseId: string; card: CccdCard }) {
  // Whether the full-size viewer is open for THIS card. Pure UI state: it
  // never reads or writes card data, so it lives here rather than in the
  // container that owns cards/error/busy.
  const [open, setOpen] = useState(false)
  const front = card.sides.find(side => side.side === 'front') ?? card.sides[0]
  if (!front) return <span className="cccd-review-nothumb">Không có ảnh</span>

  // No width/height attributes: the recorded side dimensions are transposed
  // on any case ingested before fccded7 (the JPEG parser returned header
  // order, height before width), and every existing case predates that fix.
  // The image file is the only trustworthy source of its own size, so
  // .cccd-review-tile-image img caps it at native (width: auto; max-width:
  // 100%) rather than trusting a declared width/height.
  const image = (
    <img
      src={cccdCardImageUrl(caseId, card.cardId, front.side)}
      alt={`Ảnh CCCD ${card.cardId}`}
      loading="lazy"
    />
  )

  if (card.sides.length <= 1) {
    return <div className="cccd-review-tile-image">{image}</div>
  }

  return (
    <>
      <button
        type="button"
        className="cccd-review-tile-image"
        aria-label={`Xem cả hai mặt của ảnh CCCD ${card.cardId}`}
        onClick={() => setOpen(true)}
      >
        {image}
      </button>
      {open && (
        <CccdCardViewer caseId={caseId} card={card} onClose={() => setOpen(false)} />
      )}
    </>
  )
}

// Every card image is already shown at native size (see CardThumb), so
// clicking cannot make it bigger -- what it reveals is the back, the side
// the tile does not have room for. View-only: no assign, no detach, nothing
// that mutates. Reuses CccdCardPicker's backdrop (.cccd-picker-backdrop) for
// the dim/centering and its backdrop-click + Escape pattern; the panel
// below is a sibling class, not the picker's, since this always shows
// exactly one card's own sides rather than a grid of candidates to choose
// from.
function CccdCardViewer({ caseId, card, onClose }: {
  caseId: string
  card: CccdCard
  onClose: () => void
}) {
  return (
    <div
      className="cccd-picker-backdrop"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        className="cccd-card-viewer"
        role="dialog"
        aria-modal="true"
        aria-label={`Ảnh CCCD ${card.cardId}`}
        onKeyDown={event => { if (event.key === 'Escape') onClose() }}
      >
        <header className="cccd-card-viewer-head">
          <h2>Ảnh CCCD {card.cardId}</h2>
          <button type="button" onClick={onClose}>Đóng</button>
        </header>
        <div className="cccd-card-viewer-images">
          {/* No width/height attributes here either, and no CSS box to
              reserve one at: the recorded side dimensions are transposed on
              any case ingested before fccded7, so only the image file's own
              (loaded) size is trustworthy. .cccd-card-viewer-images img
              fills the panel width instead, same convention as the picker's
              .cccd-card-images img. */}
          {card.sides.map(side => (
            <img
              key={side.side}
              src={cccdCardImageUrl(caseId, card.cardId, side.side)}
              alt={`Ảnh CCCD ${card.cardId} mặt ${side.side}`}
            />
          ))}
        </div>
      </section>
    </div>
  )
}

// Đã gán is a scan for a wrong automatic match, not a data table, so it is a
// tile rather than a row: head line (identity), then the image, then a foot
// line with the OCR number, the match reason and the one action this
// section offers. Cần xử lý's orphan cards (below, in CccdReviewView) are
// the same tile shape -- one visual language, every card image the same way.
function AttachedTile({ caseId, row, busy, onDetach }: {
  caseId: string
  row: CccdAttachedRow
  busy: boolean
  onDetach: (cardId: string) => void
}) {
  const card = row.card
  return (
    <li
      className="cccd-review-tile"
      aria-label={`Gói ${row.packetIndex + 1} ${row.name}: ${describeCard(card)}`}
    >
      <div className="cccd-review-tile-head">
        <span className="cccd-review-tile-stt">{row.packetIndex + 1}</span>
        <span className="cccd-review-tile-name">{row.name}</span>
      </div>
      <CardThumb caseId={caseId} card={card} />
      <div className="cccd-review-tile-foot">
        <span className="cccd-review-tile-number">{card.number || 'Không đọc được số'}</span>
        <span className="cccd-review-tile-state">{describeCard(card)}</span>
        <button type="button" disabled={busy} onClick={() => onDetach(card.cardId)}>Gỡ</button>
      </div>
    </li>
  )
}

// Cần xử lý's own tile: an orphan card has no packet identity yet (nothing
// has claimed it), so the head line carries the one thing it does have --
// its cardId -- instead of an STT and a name. No Gỡ button (nothing
// attached to detach), and still no assign control of its own: assignment
// goes through the packet's own "Gán thẻ" row above, unchanged.
function OrphanTile({ caseId, card }: { caseId: string; card: CccdCard }) {
  return (
    <li
      className="cccd-review-tile"
      aria-label={`Ảnh ${card.cardId}: ${describeCard(card)}`}
    >
      <div className="cccd-review-tile-head">
        <span className="cccd-review-tile-name">{card.cardId}</span>
      </div>
      <CardThumb caseId={caseId} card={card} />
      <div className="cccd-review-tile-foot">
        <span className="cccd-review-tile-number">{card.number || 'Không đọc được số'}</span>
        <span className="cccd-review-tile-state">{describeCard(card)}</span>
        <span className="cccd-review-hint">Gán từ dòng của gói cần thẻ.</span>
      </div>
    </li>
  )
}

export function CccdReviewView({
  caseId,
  caseName,
  review,
  busy,
  error,
  workbook,
  onAssign,
  onDetach,
  onRetry,
  onContinue,
}: CccdReviewViewProps) {
  // The ingest could not read the card workbook at all, so there is nothing to
  // assign from. Without saying so the screen shows a row and a "Gán thẻ" button
  // per packet -- 25 of them on a real case -- each opening an empty picker,
  // under a headline ("0 đã gắn · 0 chưa ghép") that reads as "nothing matched
  // yet" rather than "the file could not be read".
  const workbookFailed = workbook?.status === 'error'
  return (
    <div className="cccd-review">
      {/* Scrolls on its own so the footer below is a sibling, never an
          overlay: a sticky bar covers whatever is under it, and its own
          right-aligned button lands exactly where every row's action
          does, so a click meant for "Gán thẻ" fired "Tiếp tục" and
          passed a hard gate with cards still unassigned. */}
      <div className="cccd-review-body">
        <div className="case-detail-head">
          <h2>{caseName}</h2>
        </div>

        <div className="banner result-banner">
          <b>Ghép ảnh CCCD</b>
          <span>
            {review
              ? `${review.counts.attached} đã gắn · ${review.counts.unattachedCards} chưa ghép · ${review.counts.packetsWithoutCard} gói chưa có thẻ`
              : 'Đang tải…'}
          </span>
        </div>

        {workbookFailed && (
          <div className="cccd-review-failed" role="alert">
            <p>
              <b>Không đọc được file ảnh CCCD.</b> Không có ảnh nào để gán, nên
              các gói bên dưới sẽ không thể ghép thẻ ở bước này.
            </p>
            <p className="cccd-review-failed-hint">
              Kiểm tra lại file đã tải lên (mã lỗi: {workbook?.errorCode || 'không rõ'}),
              hoặc bấm “Tiếp tục →” để duyệt hồ sơ mà chưa ghép ảnh CCCD.
            </p>
          </div>
        )}

        {error && (
          <>
            <p className="cccd-review-error" role="alert">{error}</p>
            <button type="button" className="btn" onClick={onRetry}>Thử lại</button>
          </>
        )}

        {review && (
          <>
            <section className="cccd-review-section" aria-label="Cần xử lý">
              <h3>Cần xử lý</h3>
              {review.needsAction.length === 0 && (
                <p className="cccd-review-empty">Mọi gói đều đã có thẻ CCCD.</p>
              )}
              {/* The packets waiting for a card, then the cards waiting for a
                  packet: a compact row list first (no image, nothing to
                  enlarge), then the orphan cards as tiles below it, in the
                  same section -- reusing Đã gán's own .cccd-review-grid, since
                  an orphan card gets no less scrutiny than an attached one;
                  if anything it gets more, since there is no name to confirm
                  it against. */}
              <ul className="cccd-review-list">
                {review.needsAction
                  .filter((row): row is CccdPacketRow => row.kind === 'packet')
                  .map(row => (
                    <li
                      className="cccd-review-row cccd-review-needs"
                      aria-label={`Gói ${row.packetIndex + 1} ${row.name}: chưa có thẻ CCCD`}
                      key={`packet-${row.packetIndex}`}
                    >
                      <span className="cccd-review-stt">{row.packetIndex + 1}</span>
                      <span className="cccd-review-name">{row.name}</span>
                      <span className="cccd-review-state">Chưa có thẻ CCCD</span>
                      <button
                        type="button"
                        disabled={busy}
                        onClick={() => onAssign(row.packetIndex, row.name)}
                      >
                        Gán thẻ
                      </button>
                    </li>
                  ))}
              </ul>
              <ul className="cccd-review-grid">
                {review.needsAction
                  .filter((row): row is CccdCardRow => row.kind === 'card')
                  .map(row => (
                    <OrphanTile key={`card-${row.card.cardId}`} caseId={caseId} card={row.card} />
                  ))}
              </ul>
            </section>

            <details className="cccd-review-section">
              <summary>Đã gán ({review.attached.length})</summary>
              <ul className="cccd-review-grid">
                {review.attached.map(row => (
                  <AttachedTile
                    key={`attached-${row.packetIndex}`}
                    caseId={caseId}
                    row={row}
                    busy={busy}
                    onDetach={onDetach}
                  />
                ))}
              </ul>
            </details>
          </>
        )}
      </div>

      <div className="cccd-review-foot">
        <button className="btn primary" type="button" onClick={onContinue}>
          Tiếp tục →
        </button>
      </div>
    </div>
  )
}

const LOAD_ERROR = 'Không tải được danh sách ảnh.'

// Same codes CccdCardPicker maps, same wording — one vocabulary for one API.
const ERROR_TEXT: Record<string, string> = {
  'packet-already-has-card': 'Gói này đã có ảnh CCCD. Gỡ ảnh cũ trước.',
  'card-not-found': 'Không tìm thấy ảnh này.',
  'unknown-packet': 'Không tìm thấy gói hồ sơ.',
  'no-cccd-workbook': 'Hồ sơ này không có file CCCD.',
}

const MUTATE_ERROR = 'Không cập nhật được ảnh. Vui lòng thử lại.'

interface Props {
  caseId: string
  caseName: string
  packets: PacketMeta[]
  /** The ingest's own verdict on the card workbook. When it is `error` there are
   *  no cards to assign at all, and saying so is the difference between a
   *  reviewer re-uploading and clicking 25 buttons that cannot work. */
  workbook?: CccdSummary | null
  onContinue: () => void
}

export default function CccdReviewScreen({
  caseId,
  caseName,
  packets,
  workbook,
  onContinue,
}: Props) {
  const [cards, setCards] = useState<CccdCard[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [picking, setPicking] = useState<{ packetIndex: number; label: string } | null>(null)

  // Which case the screen is live on — null once unmounted. Every response is
  // checked against the case it was asked for, so an unmount or a `caseId` swap
  // mid-flight retires the answer instead of rendering one case's cards over
  // another's. A shared boolean cannot express the swap: the effect that re-arms
  // it runs in the same commit as the cleanup that set it.
  const liveCaseIdRef = useRef<string | null>(null)

  const fetchCards = useCallback(async (clearFirst: boolean) => {
    // `clearFirst` is the difference between "we know nothing yet" and "we have
    // rows and are updating them". Nulling `cards` mid-update would collapse the
    // whole screen for a one-row change.
    if (clearFirst) setCards(null)
    setError(null)
    // A refetch holds `busy` too. Without it, a refresh that deliberately keeps
    // the rows on screen also keeps the buttons live, and a detach started
    // mid-refetch races it — last write wins, silently.
    setBusy(true)
    try {
      const result = await listCccdCards(caseId)
      if (liveCaseIdRef.current === caseId) setCards(result)
    } catch {
      if (liveCaseIdRef.current === caseId) setError(LOAD_ERROR)
    } finally {
      // Guarded like the setters above: a request for a case the screen has left
      // must not clear the `busy` that the live case's own operation set. Every
      // caseId change fires that case's own load, so `busy` is never stranded.
      if (liveCaseIdRef.current === caseId) setBusy(false)
    }
  }, [caseId])

  const load = useCallback(() => fetchCards(true), [fetchCards])
  const refresh = useCallback(() => fetchCards(false), [fetchCards])

  useEffect(() => {
    liveCaseIdRef.current = caseId
    // A picker opened against the previous case would submit that case's
    // packetIndex to this one — a silent attach to the wrong packet. Close it.
    setPicking(null)
    void load()
    return () => { liveCaseIdRef.current = null }
  }, [caseId, load])

  const detach = async (cardId: string) => {
    setBusy(true)
    setError(null)
    try {
      const result = await assignCccdCard(caseId, cardId, null)
      if (liveCaseIdRef.current === caseId) setCards(result.cards)
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : ''
      if (liveCaseIdRef.current === caseId) setError(ERROR_TEXT[code] ?? MUTATE_ERROR)
    } finally {
      // Guarded like the setters above: a request for a case the screen has left
      // must not clear the `busy` that the live case's own operation set. Every
      // caseId change fires that case's own load, so `busy` is never stranded.
      if (liveCaseIdRef.current === caseId) setBusy(false)
    }
  }

  return (
    <>
      <CccdReviewView
        caseId={caseId}
        caseName={caseName}
        review={cards === null ? null : buildCccdReview(packets, cards)}
        busy={busy || cards === null}
        error={error}
        workbook={workbook}
        onAssign={(packetIndex, label) => { setPicking({ packetIndex, label }) }}
        onDetach={cardId => { void detach(cardId) }}
        onRetry={() => { void load() }}
        onContinue={onContinue}
      />

      {picking && (
        <CccdCardPicker
          caseId={caseId}
          packetIndex={picking.packetIndex}
          packetLabel={picking.label}
          onCancel={() => setPicking(null)}
          onAssigned={() => {
            // The picker keeps its own response, so refresh rather than guess —
            // but keep today's rows on screen while that GET is in flight.
            setPicking(null)
            void refresh()
          }}
        />
      )}
    </>
  )
}
