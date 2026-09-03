import { useEffect, useId, useRef, useState } from 'react'
import {
  assignCccdCard,
  cccdCardImageUrl,
  listCccdCards,
  type CccdCard,
} from '../upload/api'
import { useDialogFocus } from './useDialogFocus'

interface Props {
  caseId: string
  packetIndex: number
  /** Name shown in the title so the reviewer knows who they are matching to. */
  packetLabel: string
  onCancel: () => void
  /** The assign PUT's own card list. The parent used to learn the assignment
   *  through a second, independently-failable GET -- and when that GET failed
   *  the screen kept its pre-assign rows while the server had the card
   *  attached, so the row still offered `Gán thẻ` and re-picking answered
   *  `packet-already-has-card` for a packet showing no card and no `Gỡ`.
   *  `detach` on the same screen already renders straight from its own PUT. */
  onAssigned: (cards: CccdCard[]) => void
}

const ERROR_TEXT: Record<string, string> = {
  'packet-already-has-card': 'Gói này đã có ảnh CCCD. Gỡ ảnh cũ trước.',
  'card-not-found': 'Không tìm thấy ảnh này.',
  'unknown-packet': 'Không tìm thấy gói hồ sơ.',
  'no-cccd-workbook': 'Hồ sơ này không có file CCCD.',
  // Without these three the fallback asks the reviewer to try again, which
  // cannot work: the card has no image, or the attach/reconcile already failed
  // server-side. Say so instead.
  'card-has-no-image': 'Ảnh này không có tệp hình để gán.',
  'attach-failed': 'Không đính kèm được ảnh vào gói. Thử ảnh khác.',
  'reconcile-failed': 'Đã gán nhưng không cập nhật được hồ sơ. Tải lại trang.',
}

// The reviewer picks by eye: OCR already failed on these cards (that is why
// they are unassigned), so the number under each image is a hint at best and
// usually empty. The image is the evidence.
export default function CccdCardPicker({
  caseId,
  packetIndex,
  packetLabel,
  onCancel,
  onAssigned,
}: Props) {
  const [cards, setCards] = useState<CccdCard[] | null>(null)
  const [busyCardId, setBusyCardId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const titleId = useId()
  const panel = useRef<HTMLElement | null>(null)
  const mounted = useRef(true)
  useEffect(() => () => { mounted.current = false }, [])

  // One PUT rewrites up to 25 manifests, so the in-flight window is not tight.
  // Dismissing during it used to commit the assign anyway and then close
  // whichever picker was open by then -- the parent's setPicking(null) closes
  // what is open, not the caller. All three gestures are gated: Đóng, the
  // backdrop, and Escape.
  const busy = busyCardId !== null
  const dismiss = () => { if (!busy) onCancel() }
  useDialogFocus(panel, dismiss)

  useEffect(() => {
    let cancelled = false
    listCccdCards(caseId)
      .then(result => {
        // Only cards nothing has claimed yet are offered here.
        if (!cancelled) {
          setCards(result.filter(c => c.attachedPacketIndex === null))
        }
      })
      .catch(() => { if (!cancelled) setError('Không tải được danh sách ảnh.') })
    return () => { cancelled = true }
  }, [caseId])

  const assign = async (cardId: string) => {
    setBusyCardId(cardId)
    setError(null)
    try {
      const result = await assignCccdCard(caseId, cardId, packetIndex)
      onAssigned(result.cards)
    } catch (caught) {
      const code = caught instanceof Error ? caught.message : ''
      // A dismissal mid-flight unmounts this, and setError on an unmounted
      // component threw the message away silently -- a rejected
      // `packet-already-has-card` vanished without trace. The dismissals are
      // gated on `busyCardId` now, so this is the belt to that braces.
      if (!mounted.current) return
      setError(ERROR_TEXT[code] ?? 'Không gán được ảnh. Vui lòng thử lại.')
      setBusyCardId(null)
    }
  }


  return (
    <div
      className="cccd-picker-backdrop"
      onMouseDown={event => {
        if (event.target === event.currentTarget) dismiss()
      }}
    >
      <section
        ref={panel}
        tabIndex={-1}
        className="cccd-picker"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header className="cccd-picker-head">
          <div>
            <h2 id={titleId}>Chọn ảnh CCCD cho {packetLabel}</h2>
            <p>
              Máy không đọc được số trên những ảnh này — bạn chọn bằng mắt.
            </p>
          </div>
          <button type="button" disabled={busy} onClick={dismiss}>Đóng</button>
        </header>

        {error && <p className="cccd-picker-error" role="alert">{error}</p>}

        {cards === null && <p className="cccd-picker-empty">Đang tải…</p>}

        {cards !== null && cards.length === 0 && (
          <p className="cccd-picker-empty">
            Không còn ảnh CCCD nào chưa được gán.
          </p>
        )}

        {cards !== null && cards.length > 0 && (
          <ul className="cccd-card-grid">
            {cards.map(card => (
              <li key={card.cardId} className="cccd-card">
                <div className="cccd-card-images">
                  {card.sides.map(side => (
                    <img
                      key={side.side}
                      src={cccdCardImageUrl(caseId, card.cardId, side.side)}
                      alt={`Ảnh CCCD ${side.side}`}
                      loading="lazy"
                    />
                  ))}
                </div>
                <div className="cccd-card-foot">
                  <span className="cccd-card-number">
                    {card.number || 'Không đọc được số'}
                  </span>
                  <button
                    type="button"
                    disabled={busyCardId !== null}
                    onClick={() => { void assign(card.cardId) }}
                  >
                    {busyCardId === card.cardId ? 'Đang gán…' : 'Gán vào gói này'}
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
