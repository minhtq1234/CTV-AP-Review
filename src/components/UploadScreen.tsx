import { useRef, useState } from 'react'
import {
  canStartUpload,
  cccdRequirementMessage,
} from '../upload/cccd'

interface Props {
  onStart: (pdf: File, roster?: File, cccd?: File) => void
  busy: boolean
}

// The very first screen of the "Tải hồ sơ" flow: pick the scanned PDF (required)
// and, optionally, the Excel roster to reconcile against, then kick off a backend job.
export default function UploadScreen({ onStart, busy }: Props) {
  const [pdf, setPdf] = useState<File | null>(null)
  const [roster, setRoster] = useState<File | null>(null)
  const [cccd, setCccd] = useState<File | null>(null)
  const pdfInput = useRef<HTMLInputElement>(null)
  const rosterInput = useRef<HTMLInputElement>(null)
  const cccdInput = useRef<HTMLInputElement>(null)

  const validationMessage = cccdRequirementMessage(!!roster, !!cccd)
  const canStart = canStartUpload(!!pdf, !!roster, !!cccd, busy)

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
