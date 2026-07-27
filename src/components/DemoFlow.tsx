import { useState } from 'react'
import { folders as seedFolders } from '../ctv/folders'
import { normalizePacketReview, type PacketReview } from '../upload/api'
import {
  packetDashboardStatus,
  PACKET_DASHBOARD_LABELS,
  type PacketDashboardStatus,
} from '../logic/packetDashboard'
import FolderReview from './FolderReview'
import ReviewHeader from './ReviewHeader'

// Offline demo entry for the single-file export (chosen in App when window.__ASSETS__
// is present). The live app is a *client* of the FastAPI backend (upload → split → OCR),
// which can't run inside a file:// document, and the real submissions carry PII that must
// never be inlined into a shareable file. So the export showcases the part that CAN stand
// alone — the reviewer — against three synthetic, PII-free CTV folders (public/folders/*,
// inlined as data: URIs by scripts/build-single.mjs). Same loupe / doc-tab / packet-nav /
// review UI as the real tool; review state lives in memory only (no backend to persist to).
export default function DemoFlow() {
  const folders = seedFolders
  const [idx, setIdx] = useState<number | null>(null)
  const [reviews, setReviews] = useState<Record<string, PacketReview>>({})

  const reviewFor = (id: string): PacketReview => (
    reviews[id] ?? normalizePacketReview(undefined)
  )

  const statusClass: Record<PacketDashboardStatus, string> = {
    unseen: 'ready',
    reviewing: 'processing',
    completed: 'done',
    flagged: 'error',
  }

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
          {folders.map((f, i) => {
            const st = packetDashboardStatus({ review: reviewFor(f.id) })
            return (
              <div key={f.id} className="case-row" onClick={() => setIdx(i)}>
                <div className="case-row-main">
                  <span className="case-row-name">{f.name}</span>
                  <span className="case-row-date">{f.product}</span>
                </div>
                <span className={`case-pill ${statusClass[st]}`}>{PACKET_DASHBOARD_LABELS[st]}</span>
                <span className="case-row-progress">{f.docs.length} chứng từ</span>
              </div>
            )
          })}
        </div>
      </div>
    )
  }

  const prev = idx > 0 ? idx - 1 : null
  const next = idx < folders.length - 1 ? idx + 1 : null
  const folder = folders[idx]
  const pageCount = folder.docs.reduce((sum, doc) => sum + doc.pages.length, 0)
  return (
    <div className="review-flow">
      <ReviewHeader
        name={folder.name}
        product={folder.product}
        pages={[0, Math.max(0, pageCount - 1)]}
        matchedBy="cccd"
        position={idx}
        count={folders.length}
        canPrevious={prev != null}
        canNext={next != null}
        onBack={() => setIdx(null)}
        onPrevious={() => prev != null && setIdx(prev)}
        onNext={() => next != null && setIdx(next)}
        backLabel="Danh sách demo"
      />
      <FolderReview
        key={folder.id}
        folder={folder}
        review={reviewFor(folder.id)}
        onReview={r => setReviews(m => ({ ...m, [folder.id]: r }))}
        onCommitReview={async r => {
          setReviews(current => ({ ...current, [folder.id]: r }))
        }}
      />
    </div>
  )
}
