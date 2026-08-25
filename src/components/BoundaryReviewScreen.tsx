import { useMemo, useState } from 'react'
import {
  API_BASE,
  type BoundaryCandidate,
  type BoundaryProposal,
  type BoundaryResolution,
} from '../upload/api'

interface Props {
  proposal: BoundaryProposal
  onResolve: (resolution: BoundaryResolution) => void | Promise<void>
  onBack: () => void
}

const SIGNAL_LABELS: Record<BoundaryCandidate['signals'][number], string> = {
  visual: 'Ranh giới hiện tại',
  'contract-title': 'Tiêu đề hợp đồng',
  'identity-change': 'Danh tính thay đổi',
  cadence: 'Nhịp trang phù hợp',
}

const CONFIDENCE_LABELS: Record<BoundaryCandidate['confidence'], string> = {
  high: 'Tin cậy cao',
  medium: 'Tin cậy vừa',
}

export function boundaryPreviewSrc(
  caseId: string,
  candidate: Pick<BoundaryCandidate, 'packetIndex' | 'relativePage'>,
): string {
  return `${API_BASE}/api/cases/${caseId}/packets/${candidate.packetIndex}/page/pg${candidate.relativePage}.png`
}

export default function BoundaryReviewScreen({ proposal, onResolve, onBack }: Props) {
  const initialStarts = useMemo(
    () => proposal.candidateStarts.map(candidate => candidate.page),
    [proposal],
  )
  const [selectedStarts, setSelectedStarts] = useState<number[]>(initialStarts)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const affected = useMemo(() => {
    const affectedIndexes = new Set(proposal.affectedPacketIndexes)
    return proposal.candidateStarts.filter(candidate => (
      affectedIndexes.has(candidate.packetIndex)
    ))
  }, [proposal])
  const firstSourceStart = Math.min(...initialStarts)
  const validStarts = selectedStarts.length > 0
    && selectedStarts[0] === firstSourceStart
    && selectedStarts.every((page, index) => (
      Number.isInteger(page)
      && page >= 0
      && (index === 0 || selectedStarts[index - 1] < page)
    ))

  const toggleStart = (page: number) => {
    setSelectedStarts(current => (
      current.includes(page)
        ? current.filter(candidate => candidate !== page)
        : [...current, page].sort((left, right) => left - right)
    ))
  }

  const resolve = async (resolution: BoundaryResolution) => {
    if (busy || !proposal.correctionEnabled) return
    setBusy(true)
    setError(null)
    try {
      await onResolve(resolution)
    } catch {
      setError('Không thể lưu xác nhận ranh giới. Vui lòng thử lại.')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="boundary-review-screen">
      <header className="boundary-review-header">
        <button className="btn" type="button" disabled={busy} onClick={onBack}>
          Quay lại
        </button>
        <div>
          <h2>Kiểm tra ranh giới hồ sơ</h2>
          <p>Chỉ hiển thị các vùng cần người duyệt xác nhận.</p>
        </div>
      </header>

      {!proposal.correctionEnabled && (
        <div className="boundary-shadow-banner" role="status">
          <strong>Đang chạy thử đề xuất ranh giới</strong>
          <span>Chế độ chỉ đọc — chưa thể lưu thay đổi.</span>
        </div>
      )}

      <div className="boundary-review-summary">
        <span>{proposal.currentPacketCount} gói hiện tại</span>
        <span>
          {proposal.expectedPacketCount == null
            ? 'Không có số lượng đối chiếu'
            : `${proposal.expectedPacketCount} gói theo bảng kê`}
        </span>
      </div>

      <main className="boundary-range-list">
        {affected.map(candidate => {
          const selected = selectedStarts.includes(candidate.page)
          return (
            <article className="boundary-candidate" key={`${candidate.packetIndex}-${candidate.page}`}>
              <div className="boundary-thumbnail">
                <img
                  src={boundaryPreviewSrc(proposal.sourceCaseId, candidate)}
                  alt={`Bản xem trước Trang ${candidate.page + 1}`}
                />
              </div>
              <div className="boundary-candidate-body">
                <div className="boundary-candidate-title">
                  <strong>Trang {candidate.page + 1}</strong>
                  <span className={`boundary-confidence ${candidate.confidence}`}>
                    {CONFIDENCE_LABELS[candidate.confidence]}
                  </span>
                </div>
                <div className="boundary-signals" aria-label={`Tín hiệu Trang ${candidate.page + 1}`}>
                  {candidate.signals.map(signal => (
                    <span key={signal}>{SIGNAL_LABELS[signal]}</span>
                  ))}
                </div>
                {proposal.correctionEnabled && (
                  <button
                    className="btn boundary-start-toggle"
                    type="button"
                    disabled={busy}
                    aria-pressed={selected}
                    onClick={() => toggleStart(candidate.page)}
                  >
                    {selected ? 'Bỏ' : 'Thêm'} ranh giới Trang {candidate.page + 1}
                  </button>
                )}
              </div>
            </article>
          )
        })}
      </main>

      {error && <p className="boundary-review-error" role="alert">{error}</p>}

      {proposal.correctionEnabled && (
        <footer className="boundary-review-actions">
          <button
            className="btn"
            type="button"
            disabled={busy}
            onClick={() => resolve({ action: 'keep-current' })}
          >
            Giữ ranh giới hiện tại
          </button>
          <button
            className="btn primary"
            type="button"
            disabled={busy || !validStarts}
            onClick={() => resolve({
              action: 'create-revision',
              starts: selectedStarts,
            })}
          >
            Tạo phiên bản đã sửa
          </button>
        </footer>
      )}
    </div>
  )
}
