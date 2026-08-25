import { useMemo, useState } from 'react'
import {
  API_BASE,
  type BoundaryAffectedRange,
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

const READ_ONLY_STATUS_COPY: Record<
  Exclude<BoundaryProposal['status'], 'review_required'>,
  { title: string; recovery: string }
> = {
  accepted_current: {
    title: 'Ranh giới hiện tại đã được xác nhận',
    recovery: 'Quay lại hồ sơ để tiếp tục duyệt.',
  },
  superseded: {
    title: 'Đã tạo phiên bản ranh giới đã sửa',
    recovery: 'Mở phiên bản đã sửa từ chi tiết hồ sơ.',
  },
  not_needed: {
    title: 'Không cần sửa ranh giới',
    recovery: 'Không còn vùng ranh giới nào cần xác nhận.',
  },
}

export function boundaryPreviewSrc(
  caseId: string,
  location: Pick<BoundaryCandidate, 'packetIndex' | 'relativePage'>,
): string {
  return `${API_BASE}/api/cases/${caseId}/packets/${location.packetIndex}/page/pg${location.relativePage}.png`
}

function pagesInRange(range: BoundaryAffectedRange) {
  return Array.from(
    { length: range.endPage - range.startPage + 1 },
    (_, relativePage) => ({
      page: range.startPage + relativePage,
      packetIndex: range.packetIndex,
      relativePage,
    }),
  )
}

export default function BoundaryReviewScreen({ proposal, onResolve, onBack }: Props) {
  const initialStarts = useMemo(
    () => [...new Set(
      proposal.candidateStarts
        .map(candidate => candidate.page)
        .filter(Number.isInteger),
    )].sort((left, right) => left - right),
    [proposal],
  )
  const [selectedStarts, setSelectedStarts] = useState<number[]>(initialStarts)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const candidatesByPage = useMemo(() => {
    const candidates = new Map<number, BoundaryCandidate>()
    for (const candidate of proposal.candidateStarts) {
      candidates.set(candidate.page, candidate)
    }
    return candidates
  }, [proposal])
  const affectedRanges = useMemo(() => (
    proposal.affectedRanges.filter(range => (
      Number.isInteger(range.packetIndex)
      && Number.isInteger(range.startPage)
      && Number.isInteger(range.endPage)
      && range.packetIndex >= 0
      && range.startPage >= 0
      && range.endPage >= range.startPage
    ))
  ), [proposal])
  const canMutate = proposal.status === 'review_required'
    && proposal.correctionEnabled
  const readOnlyCopy = proposal.status === 'review_required'
    ? null
    : READ_ONLY_STATUS_COPY[proposal.status]
  const firstSourceStart = initialStarts[0]
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
    if (busy || !canMutate) return
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

      {readOnlyCopy && (
        <div className="boundary-recovery-banner" role="status">
          <strong>{readOnlyCopy.title}</strong>
          <span>{readOnlyCopy.recovery}</span>
        </div>
      )}

      {proposal.status === 'review_required' && !proposal.correctionEnabled && (
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
        {affectedRanges.map(range => (
          <section
            className="boundary-range"
            key={`${range.packetIndex}-${range.startPage}-${range.endPage}`}
          >
            <header className="boundary-range-header">
              <strong>Gói {range.packetIndex + 1}</strong>
              <span>Trang {range.startPage + 1}–{range.endPage + 1}</span>
            </header>
            <div className="boundary-page-grid">
              {pagesInRange(range).map(location => {
                const candidate = candidatesByPage.get(location.page)
                const selected = selectedStarts.includes(location.page)
                const current = candidate?.signals.includes('visual') ?? false
                const publicSignals = candidate?.signals.filter(signal => signal !== 'visual') ?? []
                return (
                  <article
                    className="boundary-candidate"
                    key={`${location.packetIndex}-${location.page}`}
                  >
                    <div className="boundary-thumbnail">
                      <img
                        src={boundaryPreviewSrc(proposal.sourceCaseId, location)}
                        alt={`Bản xem trước Trang ${location.page + 1}`}
                      />
                    </div>
                    <div className="boundary-candidate-body">
                      <div className="boundary-candidate-title">
                        <strong>Trang {location.page + 1}</strong>
                        {candidate && (
                          <span className={`boundary-confidence ${candidate.confidence}`}>
                            {CONFIDENCE_LABELS[candidate.confidence]}
                          </span>
                        )}
                      </div>
                      <div
                        className="boundary-signals"
                        aria-label={`Tín hiệu Trang ${location.page + 1}`}
                      >
                        {current && <span>Ranh giới hiện tại</span>}
                        {selected && <span className="proposed">Ranh giới đề xuất</span>}
                        {publicSignals.map(signal => (
                          <span key={signal}>{SIGNAL_LABELS[signal]}</span>
                        ))}
                        {!current && publicSignals.length === 0 && (
                          <span>Không có tín hiệu AI</span>
                        )}
                      </div>
                      {canMutate && (
                        <button
                          className="btn boundary-start-toggle"
                          type="button"
                          disabled={busy}
                          aria-pressed={selected}
                          onClick={() => toggleStart(location.page)}
                        >
                          {selected ? 'Bỏ' : 'Thêm'} ranh giới Trang {location.page + 1}
                        </button>
                      )}
                    </div>
                  </article>
                )
              })}
            </div>
          </section>
        ))}
      </main>

      {error && <p className="boundary-review-error" role="alert">{error}</p>}

      {canMutate && (
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
