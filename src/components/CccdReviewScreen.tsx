// Ver 3 step 1: the reviewer confirms which CCCD card belongs to which packet
// before opening the packet list. Exceptions first; everything already attached
// sits behind a collapsed section, so a wrong automatic match is still findable.
import { useCallback, useEffect, useRef, useState } from 'react'
import { assignCccdCard, cccdCardImageUrl, listCccdCards } from '../upload/api'
import type { CccdCard, PacketMeta } from '../upload/api'
import { buildCccdReview } from '../logic/cccdReview'
import {
  describeCard,
  type CccdAttachedRow,
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
  onAssign: (packetIndex: number, packetLabel: string) => void
  onDetach: (cardId: string) => void
  onRetry: () => void
  onContinue: () => void
}

// `variant` picks the visual treatment only -- the state, the button, the
// viewer and its label are identical either way. 'row' is the small,
// fixed-160x101 thumbnail (Cần xử lý, unchanged); 'tile' is Đã gán's
// tile-filling image, sized entirely by CSS on .cccd-review-tile-image so
// the row's fixed box never applies to it.
function CardThumb({ caseId, card, variant = 'row' }: {
  caseId: string
  card: CccdCard
  variant?: 'row' | 'tile'
}) {
  // Whether the full-size viewer is open for THIS card. Pure UI state: it
  // never reads or writes card data, so it lives here rather than in the
  // container that owns cards/error/busy.
  const [open, setOpen] = useState(false)
  const front = card.sides.find(side => side.side === 'front') ?? card.sides[0]
  if (!front) return <span className="cccd-review-nothumb">Không có ảnh</span>
  return (
    <>
      <button
        type="button"
        className={variant === 'tile' ? 'cccd-review-tile-image' : 'cccd-review-thumb-btn'}
        aria-label={`Xem ảnh CCCD ${card.cardId} ở kích thước đầy đủ`}
        onClick={() => setOpen(true)}
      >
        {/* No width/height attributes: the recorded side dimensions are
            transposed on any case ingested before fccded7 (the JPEG parser
            returned header order, height before width), and every existing
            case predates that fix. The image file is the only trustworthy
            source of its own size, so the box is reserved by CSS instead
            (width/height/aspect-ratio on .cccd-review-thumb for the row;
            .cccd-review-tile-image img's width: 100%; height: auto for the
            tile, uncapped since these crops are not a uniform shape). */}
        <img
          className={variant === 'tile' ? undefined : 'cccd-review-thumb'}
          src={cccdCardImageUrl(caseId, card.cardId, front.side)}
          alt={`Ảnh CCCD ${card.cardId}`}
          loading="lazy"
        />
      </button>
      {open && (
        <CccdCardViewer caseId={caseId} card={card} onClose={() => setOpen(false)} />
      )}
    </>
  )
}

// The row thumbnail is barely big enough to place a face at a glance -- the
// reviewer decides by eye, so seeing the card at full size has to be one
// click away. View-only: no assign, no detach, nothing that mutates.
// Reuses CccdCardPicker's backdrop (.cccd-picker-backdrop) for the dim /
// centering and its backdrop-click + Escape pattern; the panel below is a
// sibling class, not the picker's, since this always shows exactly one
// card's own sides rather than a grid of candidates to choose from.
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
// tile rather than a row: head line (identity), then the image big enough to
// place a face, then a foot line with the OCR number, the match reason and
// the one action this section offers. Cần xử lý (below, in CccdReviewView)
// is untouched and still uses the row grid.
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
      <CardThumb caseId={caseId} card={card} variant="tile" />
      <div className="cccd-review-tile-foot">
        <span className="cccd-review-tile-number">{card.number || 'Không đọc được số'}</span>
        <span className="cccd-review-tile-state">{describeCard(card)}</span>
        <button type="button" disabled={busy} onClick={() => onDetach(card.cardId)}>Gỡ</button>
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
  onAssign,
  onDetach,
  onRetry,
  onContinue,
}: CccdReviewViewProps) {
  return (
    <div className="cccd-review">
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
            <ul className="cccd-review-list">
              {review.needsAction.map(row => (
                row.kind === 'packet' ? (
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
                ) : (
                  <li
                    className="cccd-review-row cccd-review-orphan"
                    aria-label={`Ảnh ${row.card.cardId}: ${describeCard(row.card)}`}
                    key={`card-${row.card.cardId}`}
                  >
                    <CardThumb caseId={caseId} card={row.card} />
                    <span className="cccd-review-number">
                      {row.card.number || 'Không đọc được số'}
                    </span>
                    <span className="cccd-review-state">{describeCard(row.card)}</span>
                    <span className="cccd-review-cardid">{row.card.cardId}</span>
                    <span className="cccd-review-hint">
                      Gán từ dòng của gói cần thẻ.
                    </span>
                  </li>
                )
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
  onContinue: () => void
}

export default function CccdReviewScreen({
  caseId,
  caseName,
  packets,
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
