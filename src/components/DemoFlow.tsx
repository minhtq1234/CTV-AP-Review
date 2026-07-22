import { useState } from 'react'
import type { CtvFolder } from '../ctv/types'
import { folders as seedFolders } from '../ctv/folders'
import FolderReview from './FolderReview'

// Offline demo entry for the single-file export (chosen in App when window.__ASSETS__
// is present). The live app is a *client* of the FastAPI backend (upload → split → OCR),
// which can't run inside a file:// document, and the real submissions carry PII that must
// never be inlined into a shareable file. So the export showcases the part that CAN stand
// alone — the reviewer — against three synthetic, PII-free CTV folders (public/folders/*,
// inlined as data: URIs by scripts/build-single.mjs). Same loupe / auto-focus / doc-tab /
// packet-nav UI as the real tool; decisions live in memory only (no backend to persist to).
export default function DemoFlow() {
  const [folders, setFolders] = useState<CtvFolder[]>(seedFolders)
  const [idx, setIdx] = useState<number | null>(null)

  const statusText = (s: CtvFolder['status']) =>
    s === 'approved' ? 'Đã duyệt' : s === 'rejected' ? 'Đã từ chối' : 'Chờ duyệt'
  // reuse the case-pill palette: pending→ready, approved→done, rejected→error
  const statusClass = (s: CtvFolder['status']) =>
    s === 'approved' ? 'done' : s === 'rejected' ? 'error' : 'ready'

  if (idx == null) {
    return (
      <div className="case-list">
        <div className="case-list-head">
          <h2>Bản demo ngoại tuyến</h2>
        </div>
        <p className="case-list-empty">
          Tệp này minh hoạ giao diện duyệt trên 3 hồ sơ CTV mẫu (dữ liệu giả, không có
          thông tin thật). Luồng đầy đủ — tải PDF lớn → tách → OCR — cần máy chủ xử lý.
        </p>
        <div className="case-rows">
          {folders.map((f, i) => (
            <div key={f.id} className="case-row" onClick={() => setIdx(i)}>
              <div className="case-row-main">
                <span className="case-row-name">{f.name}</span>
                <span className="case-row-date">{f.product}</span>
              </div>
              <span className={`case-pill ${statusClass(f.status)}`}>{statusText(f.status)}</span>
              <span className="case-row-progress">{f.docs.length} chứng từ</span>
            </div>
          ))}
        </div>
      </div>
    )
  }

  // Prev/next scrub across the demo folders — mirrors the live review shell so the
  // export demonstrates the packet-nav feature too.
  const prev = idx > 0 ? idx - 1 : null
  const next = idx < folders.length - 1 ? idx + 1 : null
  return (
    <div className="review-flow">
      <div className="review-back-bar">
        <button className="btn" onClick={() => setIdx(null)}>← Danh sách demo</button>
        <div className="review-nav">
          <button
            className="btn"
            disabled={prev == null}
            title={prev != null ? `Gói trước: ${folders[prev].name}` : undefined}
            onClick={() => prev != null && setIdx(prev)}
          >
            ← Gói trước
          </button>
          <span className="review-nav-pos">Gói {idx + 1} / {folders.length}</span>
          <button
            className="btn"
            disabled={next == null}
            title={next != null ? `Gói sau: ${folders[next].name}` : undefined}
            onClick={() => next != null && setIdx(next)}
          >
            Gói sau →
          </button>
        </div>
      </div>
      <FolderReview
        key={folders[idx].id}
        folder={folders[idx]}
        onUpdate={f => setFolders(list => list.map((x, i) => (i === idx ? f : x)))}
      />
    </div>
  )
}
