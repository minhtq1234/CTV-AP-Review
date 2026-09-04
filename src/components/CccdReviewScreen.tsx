// Ver 3 step 1: the reviewer confirms which CCCD card belongs to which packet
// before opening the packet list. Exceptions first; everything already attached
// sits behind a collapsed section, so a wrong automatic match is still findable.
import { useCallback, useEffect, useRef, useState } from 'react'
import { assignCccdCard, cccdCardImageUrl, listCccdCards } from '../upload/api'
import type { CccdCard, CccdSummary, PacketMeta } from '../upload/api'
import { buildCccdReview } from '../logic/cccdReview'
import { useDialogFocus } from './useDialogFocus'
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
  /** A mutation is in flight. Gates the row actions AND the way out. */
  busy: boolean
  /** The first card list has not arrived. Gates the row actions but NOT the
   *  footer: a failed GET leaves this true for ever, and folding it into
   *  `busy` disabled the only way off the screen permanently -- next to an
   *  alert saying the load failed and a live region still claiming
   *  "Đang cập nhật…". `Thử lại` only re-issues the same GET. */
  loading: boolean
  /** `load` can be retried by reloading; `mutate` cannot -- reloading
   *  re-issues no PUT and blanks the screen. */
  error: { text: string; kind: 'load' | 'mutate' } | null
  /** The ingest's verdict on the card workbook, when there is one. */
  workbook?: CccdSummary | null
  onAssign: (packetIndex: number, packetLabel: string) => void
  onDetach: (cardId: string) => void
  onRetry: () => void
  onDismissError: () => void
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
  const panel = useRef<HTMLElement | null>(null)
  useDialogFocus(panel, onClose)

  return (
    <div
      className="cccd-picker-backdrop"
      onMouseDown={event => {
        if (event.target === event.currentTarget) onClose()
      }}
    >
      <section
        ref={panel}
        tabIndex={-1}
        className="cccd-card-viewer"
        role="dialog"
        aria-modal="true"
        aria-label={`Ảnh CCCD ${card.cardId}`}
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
        <button
          type="button"
          disabled={busy}
          aria-label={`Gỡ ảnh CCCD khỏi gói ${row.packetIndex + 1} ${row.name}`}
          onClick={() => onDetach(card.cardId)}
        >
          Gỡ
        </button>
      </div>
    </li>
  )
}

// Cần xử lý's own tile: an orphan card has no packet identity yet (nothing
// has claimed it), so the head line carries the one thing it does have --
// its cardId -- instead of an STT and a name. No Gỡ button (nothing
// attached to detach), and still no assign control of its own: assignment
// goes through the packet's own "Gán thẻ" row above, unchanged.
function OrphanTile({ caseId, card, assignable }: {
  caseId: string
  card: CccdCard
  /** Whether any packet still needs a card. When none does, the hint below
   *  would send the reviewer to a row that is not on the screen: placing this
   *  card means detaching another packet's first, and nothing here says so. */
  assignable: boolean
}) {
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
        <span className="cccd-review-hint">
          {assignable
            ? 'Gán từ dòng của gói cần thẻ.'
            : 'Mọi gói đã có thẻ — gỡ thẻ của một gói trước khi gán ảnh này.'}
        </span>
      </div>
    </li>
  )
}

export function CccdReviewView({
  caseId,
  caseName,
  review,
  busy,
  loading,
  error,
  workbook,
  onAssign,
  onDetach,
  onRetry,
  onDismissError,
  onContinue,
}: CccdReviewViewProps) {
  // The ingest could not read the card workbook at all, so there is nothing to
  // assign from. Without saying so the screen shows a row and a "Gán thẻ" button
  // per packet -- 25 of them on a real case -- each opening an empty picker,
  // under a headline ("0 đã gắn · 0 chưa ghép") that reads as "nothing matched
  // yet" rather than "the file could not be read".
  const workbookFailed = workbook?.status === 'error'
  const errorRef = useRef<HTMLDivElement | null>(null)

  // role="alert" already announces, so this defect was scoped to sighted
  // reviewers -- the primary population.
  useEffect(() => {
    const node = errorRef.current
    if (!error || !node) return
    // Guarded: jsdom implements neither, and neither is load-bearing -- the
    // message is sticky and `role="alert"` announces it either way.
    if (typeof node.scrollIntoView === 'function') {
      node.scrollIntoView({ block: 'nearest' })
    }
    if (typeof node.focus === 'function') node.focus()
  }, [error])

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

        {/* The counts changed silently: only errors had a live region, so an
            assign or a detach reorganised the queue with nothing announced.
            It matters most for the destructive direction, `Gỡ`. */}
        <p className="sr-only" role="status">
          {loading
            ? 'Đang tải danh sách ảnh…'
            : busy
            ? 'Đang cập nhật…'
            : review
              ? `${review.counts.attached} thẻ đã gắn, `
                + `${review.counts.packetsWithoutCard} gói chưa có thẻ, `
                + `${review.counts.unattachedCards} ảnh chưa ghép.`
              : ''}
        </p>

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

        {/* Sticky, and scrolled to. Every `Gỡ` sits inside the collapsed
            `Đã gán` disclosure at the very end of the list, so on a real case
            a failed detach reported itself 3,869-6,163px above the viewport
            with nothing perceptible at the click site -- a MutationObserver
            caught the button's `disabled` set and cleared 5.5ms apart, i.e.
            never painted. On the 41-packet July case, where `Gỡ` is the only
            mutating control, the message was unreachable even on the first
            button. */}
        {error && (
          <div className="cccd-review-error" role="alert" ref={errorRef}
               tabIndex={-1}>
            <p>{error.text}</p>
            {error.kind === 'load' ? (
              <button type="button" className="btn" onClick={onRetry}>
                Thử lại
              </button>
            ) : (
              // Not `Thử lại`: it re-issued no PUT and unmounted the review
              // subtree, so the screen blanked and `Đã gán` reopened collapsed.
              <button type="button" className="btn" onClick={onDismissError}>
                Đóng thông báo
              </button>
            )}
          </div>
        )}

        {review && (
          <>
            <section className="cccd-review-section" aria-label="Cần xử lý">
              <h3>Cần xử lý</h3>
              {/* Gated on packets, not on needsAction: needsAction holds
                  orphan CARD rows too, so one leftover card suppressed this
                  on a case where every packet really did have its card --
                  which is the shape of the 41-packet July submission. */}
              {review.counts.packetsWithoutCard === 0 && (
                <p className="cccd-review-empty">Mọi gói đều đã có thẻ CCCD.</p>
              )}
              {/* The packets waiting for a card: a compact row list, no
                  image and nothing to enlarge. The cards waiting for a packet
                  used to follow here in the same section; they are their own
                  section below `Đã gán` now, and still get Đã gán's own
                  .cccd-review-grid -- an orphan card gets no less scrutiny
                  than an attached one, and arguably more, since there is no
                  name to confirm it against. */}
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
                      {/* The identity is on the <li>, which is announced when
                          browsing a list but not when Tab lands on a
                          descendant -- and the first 18 tab stops here are 18
                          consecutively identical "Gán thẻ". */}
                      <button
                        type="button"
                        disabled={busy || loading || workbookFailed}
                        title={workbookFailed
                          ? 'Không đọc được file ảnh CCCD nên chưa có ảnh để gán.'
                          : undefined}
                        aria-label={`Gán thẻ cho gói ${row.packetIndex + 1} ${row.name}`}
                        onClick={() => onAssign(row.packetIndex, row.name)}
                      >
                        Gán thẻ
                      </button>
                    </li>
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
                    busy={busy || loading}
                    onDetach={onDetach}
                  />
                ))}
              </ul>
            </details>

            {/* Last, and no longer inside `Cần xử lý`. These tiles are large
                images -- 18 of them on a real case -- and they sat between
                the queue and the `Đã gán` disclosure, which put that
                disclosure 4,277px below the fold. It is the reason this
                component exists (a wrong automatic match has to stay
                findable), so it cannot be the thing at the bottom. An orphan
                card is reference material rather than a control: it is
                assigned from a packet's own row above, and the picker shows
                these same images again when it is. */}
            {review.counts.unattachedCards > 0 && (
              <section className="cccd-review-section"
                       aria-label="Ảnh chưa ghép">
                <h3>Ảnh chưa ghép ({review.counts.unattachedCards})</h3>
                <ul className="cccd-review-grid">
                  {review.needsAction
                    .filter((row): row is CccdCardRow => row.kind === 'card')
                    .map(row => (
                      <OrphanTile
                        key={`card-${row.card.cardId}`}
                        caseId={caseId}
                        card={row.card}
                        assignable={review.counts.packetsWithoutCard > 0}
                      />
                    ))}
                </ul>
              </section>
            )}
          </>
        )}
      </div>

      <div className="cccd-review-foot">
        {/* Gated on an in-flight mutation, and deliberately NOT on `loading`.
            Leaving mid-mutation defeats the single getCase that
            continueFromCccdReview does, because a mutation moves the summary
            and the per-packet rollups. But a failed card GET leaves `loading`
            true for ever, and gating on it disabled the only way off this
            screen permanently -- beside an alert saying the load failed. */}
        <button className="btn primary" type="button" disabled={busy}
                onClick={onContinue}>
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
  // Kinded, because the two failures need different offers. `Thử lại` reloads,
  // which is right for a load failure and wrong for a mutation: it re-issued no
  // PUT, nulled `cards` and so unmounted the whole review subtree -- the screen
  // blanked to "Đang tải…" and the DOM-owned <details> came back collapsed.
  const [error, setError] =
    useState<{ text: string; kind: 'load' | 'mutate' } | null>(null)
  const [busy, setBusy] = useState(false)
  const [picking, setPicking] = useState<{ packetIndex: number; label: string } | null>(null)

  // Which case the screen is live on — null once unmounted. Every response is
  // checked against the case it was asked for, so an unmount or a `caseId` swap
  // mid-flight retires the answer instead of rendering one case's cards over
  // another's. A shared boolean cannot express the swap: the effect that re-arms
  // it runs in the same commit as the cleanup that set it.
  const liveCaseIdRef = useRef<string | null>(null)

  // Always clears first. There used to be a `clearFirst: false` mode for the
  // post-assign refetch, so a one-row change would not collapse the screen --
  // but both mutations now render from their own PUT response, so the only
  // fetch left is the one that owns the whole screen and has nothing to keep.
  const fetchCards = useCallback(async () => {
    setCards(null)
    setError(null)
    // The fetch holds `busy` too: without it a detach started mid-fetch races
    // it, and last write wins silently.
    setBusy(true)
    try {
      const result = await listCccdCards(caseId)
      if (liveCaseIdRef.current === caseId) setCards(result)
    } catch {
      if (liveCaseIdRef.current === caseId)
        setError({ text: LOAD_ERROR, kind: 'load' })
    } finally {
      // Guarded like the setters above: a request for a case the screen has left
      // must not clear the `busy` that the live case's own operation set. Every
      // caseId change fires that case's own load, so `busy` is never stranded.
      if (liveCaseIdRef.current === caseId) setBusy(false)
    }
  }, [caseId])

  const load = useCallback(() => fetchCards(), [fetchCards])

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
      if (liveCaseIdRef.current === caseId)
        setError({ text: ERROR_TEXT[code] ?? MUTATE_ERROR, kind: 'mutate' })
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
        busy={busy}
        loading={cards === null}
        error={error}
        workbook={workbook}
        onAssign={(packetIndex, label) => { setPicking({ packetIndex, label }) }}
        onDetach={cardId => { void detach(cardId) }}
        onRetry={() => { void load() }}
        onDismissError={() => setError(null)}
        onContinue={onContinue}
      />

      {picking && (
        <CccdCardPicker
          caseId={caseId}
          packetIndex={picking.packetIndex}
          packetLabel={picking.label}
          onCancel={() => setPicking(null)}
          onAssigned={next => {
            // Render straight from the PUT's own response, exactly as detach
            // does. Going back for a second GET meant the assignment could be
            // lost to an independently-failable request: when it rejected, the
            // screen kept its pre-assign rows while the server had the card
            // attached, so the row still offered `Gán thẻ` and re-picking
            // answered `packet-already-has-card` for a packet showing no card
            // and no `Gỡ`. Also drops a round trip, 3 per assign to 2.
            setPicking(null)
            setError(null)
            setCards(next)
          }}
        />
      )}
    </>
  )
}
