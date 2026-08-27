// Ver 3 step 1: the reviewer confirms which CCCD card belongs to which packet
// before opening the packet list. Exceptions first; everything already attached
// sits behind a collapsed section, so a wrong automatic match is still findable.
import { cccdCardImageUrl } from '../upload/api'
import type { CccdCard } from '../upload/api'
import {
  describeCard,
  type CccdAttachedRow,
  type CccdReview,
} from '../logic/cccdReview'

export interface CccdReviewViewProps {
  caseId: string
  caseName: string
  review: CccdReview
  busy: boolean
  error: string | null
  onAssign: (packetIndex: number, packetLabel: string) => void
  onDetach: (cardId: string) => void
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
    <li className="cccd-review-row">
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
  onContinue,
}: CccdReviewViewProps) {
  const { needsAction, attached, counts } = review
  return (
    <div className="cccd-review">
      <div className="case-detail-head">
        <h2>{caseName}</h2>
      </div>

      <div className="banner result-banner">
        <b>Ghép ảnh CCCD</b>
        <span>
          {counts.attached} đã gắn · {counts.unattachedCards} chưa ghép ·{' '}
          {counts.packetsWithoutCard} gói chưa có thẻ
        </span>
      </div>

      {error && <p className="cccd-review-error" role="alert">{error}</p>}

      <section className="cccd-review-section" aria-label="Cần xử lý">
        <h3>Cần xử lý</h3>
        {needsAction.length === 0 && (
          <p className="cccd-review-empty">Mọi gói đều đã có thẻ CCCD.</p>
        )}
        <ul className="cccd-review-list">
          {needsAction.map(row => (
            row.kind === 'packet' ? (
              <li className="cccd-review-row" key={`packet-${row.packetIndex}`}>
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
              <li className="cccd-review-row cccd-review-orphan" key={`card-${row.card.cardId}`}>
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
        <summary>Đã gán ({attached.length})</summary>
        <ul className="cccd-review-list">
          {attached.map(row => (
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

      <div className="cccd-review-foot">
        <button className="btn primary" type="button" onClick={onContinue}>
          Tiếp tục →
        </button>
      </div>
    </div>
  )
}
