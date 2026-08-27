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

function CardThumb({ caseId, card }: { caseId: string; card: CccdCard }) {
  const front = card.sides.find(side => side.side === 'front') ?? card.sides[0]
  if (!front) return <span className="cccd-review-nothumb">Không có ảnh</span>
  return (
    <img
      className="cccd-review-thumb"
      src={cccdCardImageUrl(caseId, card.cardId, front.side)}
      alt={`Ảnh CCCD ${card.cardId}`}
      width={front.width}
      height={front.height}
      loading="lazy"
    />
  )
}

function AttachedRow({ caseId, row, busy, onDetach }: {
  caseId: string
  row: CccdAttachedRow
  busy: boolean
  onDetach: (cardId: string) => void
}) {
  const card = row.card
  return (
    <li
      className="cccd-review-row"
      aria-label={`Gói ${row.packetIndex + 1} ${row.name}: ${describeCard(card)}`}
    >
      <span className="cccd-review-stt">{row.packetIndex + 1}</span>
      <span className="cccd-review-name">{row.name}</span>
      <CardThumb caseId={caseId} card={card} />
      <span className="cccd-review-number">{card.number || 'Không đọc được số'}</span>
      <span className="cccd-review-state">{describeCard(card)}</span>
      <button type="button" disabled={busy} onClick={() => onDetach(card.cardId)}>Gỡ</button>
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
                    className="cccd-review-row"
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
            <ul className="cccd-review-list">
              {review.attached.map(row => (
                <AttachedRow
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
    try {
      const result = await listCccdCards(caseId)
      if (liveCaseIdRef.current === caseId) setCards(result)
    } catch {
      if (liveCaseIdRef.current === caseId) setError(LOAD_ERROR)
    }
  }, [caseId])

  const load = useCallback(() => fetchCards(true), [fetchCards])
  const refresh = useCallback(() => fetchCards(false), [fetchCards])

  useEffect(() => {
    liveCaseIdRef.current = caseId
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
      // Unguarded on purpose: `busy` tracks this mutation, not the case. Skipping
      // it after a swap would leave the new case's buttons disabled for good.
      setBusy(false)
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
