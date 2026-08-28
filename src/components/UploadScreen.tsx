import { useEffect, useRef, useState } from 'react'
import {
  canStartUpload,
  cccdRequirementMessage,
} from '../upload/cccd'
import {
  inspectUpload,
  RosterRejected,
  type UploadInspection,
} from '../upload/api'
import {
  imageColumnLine,
  needsAttention,
  rosterLine,
} from '../logic/uploadInspection'

interface Props {
  onStart: (pdf: File, roster?: File, cccd?: File) => void
  busy: boolean
}

type InspectState =
  | { status: 'idle' }
  | { status: 'loading' }
  | { status: 'rejected'; reason: string }
  | { status: 'done'; inspection: UploadInspection }

// The very first screen of the "Tải hồ sơ" flow: pick the scanned PDF (required)
// and, optionally, the Excel roster to reconcile against, then kick off a backend job.
export default function UploadScreen({ onStart, busy }: Props) {
  const [pdf, setPdf] = useState<File | null>(null)
  const [roster, setRoster] = useState<File | null>(null)
  const [cccd, setCccd] = useState<File | null>(null)
  const pdfInput = useRef<HTMLInputElement>(null)
  const rosterInput = useRef<HTMLInputElement>(null)
  const cccdInput = useRef<HTMLInputElement>(null)
  const [inspect, setInspect] = useState<InspectState>({ status: 'idle' })

  // Declare what the workbooks were read as, before the reviewer commits to a
  // run that takes the better part of an hour. Re-runs whenever either workbook
  // changes; a stale answer is retired rather than rendered under new files.
  useEffect(() => {
    if (!roster) { setInspect({ status: 'idle' }); return }
    let live = true
    setInspect({ status: 'loading' })
    inspectUpload(roster, cccd ?? undefined)
      .then(inspection => { if (live) setInspect({ status: 'done', inspection }) })
      .catch(error => {
        if (!live) return
        setInspect(error instanceof RosterRejected
          ? { status: 'rejected', reason: error.reason }
          : { status: 'idle' })
      })
    return () => { live = false }
  }, [roster, cccd])

  const validationMessage = cccdRequirementMessage(!!roster, !!cccd)
  const canStart = canStartUpload(!!pdf, !!roster, !!cccd, busy)
    && inspect.status !== 'rejected'

  return (
    <div className="upload-screen">
      <div className="upload-card">
        <h2>Tải hồ sơ CTV</h2>
        <p className="upload-hint">
          Tải lên bản scan PDF gồm nhiều hồ sơ CTV (và bảng kê Excel nếu có) để tự động
          tách gói, đọc dữ liệu (OCR) và đối chiếu với bảng kê.
        </p>

        <label className="dropzone">
          <input
            ref={pdfInput}
            type="file"
            accept="application/pdf"
            className="dropzone-input"
            onChange={e => setPdf(e.target.files?.[0] ?? null)}
          />
          <span className="dropzone-icon">📄</span>
          <span className="dropzone-label">{pdf ? pdf.name : 'Chọn file PDF scan (bắt buộc)'}</span>
        </label>

        <label className="dropzone dropzone-sm">
          <input
            ref={rosterInput}
            type="file"
            accept=".xlsx"
            className="dropzone-input"
            onChange={e => setRoster(e.target.files?.[0] ?? null)}
          />
          <span className="dropzone-icon">📊</span>
          <span className="dropzone-label">{roster ? roster.name : 'Chọn bảng kê Excel (tuỳ chọn)'}</span>
        </label>

        <label className="dropzone dropzone-sm">
          <input
            ref={cccdInput}
            type="file"
            accept=".xlsx"
            className="dropzone-input"
            onChange={event => setCccd(event.target.files?.[0] ?? null)}
          />
          <span className="dropzone-icon">🪪</span>
          <span className="dropzone-label">
            {cccd ? cccd.name : 'Chọn file ảnh CCCD Excel (tuỳ chọn)'}
          </span>
          <span className="upload-helper">
            Nên dùng ảnh gốc hoặc ảnh độ phân giải cao, được chèn trực tiếp trong file .xlsx.
          </span>
        </label>

        {cccd && (
          <button
            type="button"
            className="upload-file-clear"
            onClick={() => {
              setCccd(null)
              if (cccdInput.current) cccdInput.current.value = ''
            }}
          >
            Bỏ file CCCD
          </button>
        )}

        {/* What the tool read these workbooks as. Confirmed in seconds here,
            rather than discovered after a run that takes ~50 minutes. */}
        {inspect.status === 'loading' && (
          <p className="upload-inspect-state">Đang đọc bảng kê…</p>
        )}

        {inspect.status === 'rejected' && (
          <div className="upload-inspect rejected" role="alert">
            <p className="upload-inspect-title">Không dùng được bảng kê này</p>
            <p className="upload-inspect-reason">{inspect.reason}</p>
          </div>
        )}

        {inspect.status === 'done' && (
          <div className={`upload-inspect${needsAttention(inspect.inspection) ? ' attention' : ''}`}>
            <p className="upload-inspect-title">Đã đọc được</p>
            <p className="upload-inspect-roster">{rosterLine(inspect.inspection)}</p>
            {inspect.inspection.images.length > 0 && (
              <ul className="upload-inspect-images">
                {inspect.inspection.images.map(image => (
                  <li
                    key={`${image.sheet}:${image.column}`}
                    className={image.kind === null ? 'unrecognised' : undefined}
                  >
                    {imageColumnLine(image)}
                  </li>
                ))}
              </ul>
            )}
            {needsAttention(inspect.inspection) && (
              <p className="upload-inspect-warn">
                Hãy kiểm tra lại trước khi chạy — có mục chưa nhận dạng được.
              </p>
            )}
          </div>
        )}

        {validationMessage && (
          <p className="upload-validation" role="alert">
            {validationMessage}
          </p>
        )}

        <button
          type="button"
          className="btn primary upload-start"
          disabled={!canStart}
          onClick={() => pdf && onStart(
            pdf,
            roster ?? undefined,
            cccd ?? undefined,
          )}
        >
          {busy ? 'Đang tải lên…' : 'Bắt đầu xử lý'}
        </button>
      </div>
    </div>
  )
}
