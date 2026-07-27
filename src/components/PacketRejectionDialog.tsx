import { useEffect, useId, useRef, useState } from 'react'
import type { PacketRejection, PacketRejectionReason } from '../upload/api'
import {
  normalizeRejectionDraft,
  PACKET_REJECTION_OPTIONS,
} from '../logic/packetRejection'

interface Props {
  rejection: PacketRejection | null
  saving: boolean
  error: string | null
  onCancel: () => void
  onSubmit: (rejection: PacketRejection) => void
  onUndo?: () => void
}

export default function PacketRejectionDialog({
  rejection,
  saving,
  error,
  onCancel,
  onSubmit,
  onUndo,
}: Props) {
  const [reasons, setReasons] = useState<PacketRejectionReason[]>(
    rejection?.reasons ?? [],
  )
  const [note, setNote] = useState(rejection?.note ?? '')
  const [validationError, setValidationError] = useState<string | null>(null)
  const titleId = useId()
  const firstReasonRef = useRef<HTMLInputElement>(null)
  const editing = rejection !== null

  useEffect(() => { firstReasonRef.current?.focus() }, [])

  const toggleReason = (reason: PacketRejectionReason) => {
    setValidationError(null)
    setReasons(current => current.includes(reason)
      ? current.filter(value => value !== reason)
      : [...current, reason])
  }

  const submit = () => {
    try {
      const normalized = normalizeRejectionDraft(reasons, note)
      setValidationError(null)
      onSubmit(normalized)
    } catch (caught) {
      setValidationError(caught instanceof Error
        ? caught.message
        : 'Chọn ít nhất một lý do')
    }
  }

  const cancel = () => {
    if (!saving) onCancel()
  }

  return (
    <div
      className="packet-rejection-backdrop"
      onMouseDown={event => {
        if (event.target === event.currentTarget) cancel()
      }}
    >
      <section
        className="packet-rejection-dialog"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={event => {
          if (event.key === 'Escape') {
            event.preventDefault()
            event.stopPropagation()
            cancel()
          }
        }}
      >
        <h2 id={titleId}>
          {editing ? 'Sửa lý do từ chối' : 'Từ chối gói hồ sơ'}
        </h2>

        <fieldset className="packet-rejection-reasons" disabled={saving}>
          <legend>Lý do</legend>
          {PACKET_REJECTION_OPTIONS.map((option, index) => (
            <label key={option.value}>
              <input
                ref={index === 0 ? firstReasonRef : undefined}
                type="checkbox"
                checked={reasons.includes(option.value)}
                onChange={() => toggleReason(option.value)}
              />
              <span>{option.label}</span>
            </label>
          ))}
        </fieldset>

        <label className="packet-rejection-note">
          <span>Ghi chú</span>
          <textarea
            value={note}
            disabled={saving}
            rows={3}
            placeholder="Ghi chú (tuỳ chọn)"
            onChange={event => {
              setValidationError(null)
              setNote(event.target.value)
            }}
          />
        </label>

        {(validationError || error) && (
          <p className="packet-rejection-error" role="alert">
            {validationError || error}
          </p>
        )}

        <div className="packet-rejection-actions">
          {editing && onUndo && (
            <button
              type="button"
              className="btn packet-rejection-undo"
              disabled={saving}
              onClick={onUndo}
            >
              Hoàn tác từ chối
            </button>
          )}
          <span className="packet-rejection-actions-spacer" />
          <button type="button" className="btn" disabled={saving} onClick={cancel}>
            Hủy
          </button>
          <button
            type="button"
            className="btn packet-rejection-confirm"
            disabled={saving}
            onClick={submit}
          >
            {saving
              ? 'Đang lưu…'
              : editing ? 'Lưu thay đổi' : 'Xác nhận từ chối'}
          </button>
        </div>
      </section>
    </div>
  )
}
