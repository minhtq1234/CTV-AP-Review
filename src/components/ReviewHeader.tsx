import type { MatchedBy } from '../upload/api'
import MatchKeyStrip from './MatchKeyStrip'

interface Props {
  name: string
  product: string
  pages: [number, number]
  matchedBy: MatchedBy
  position: number
  count: number
  canPrevious: boolean
  canNext: boolean
  onBack: () => void
  onPrevious: () => void
  onNext: () => void
  backLabel?: string
}

export default function ReviewHeader({
  name,
  product,
  pages,
  matchedBy,
  position,
  count,
  canPrevious,
  canNext,
  onBack,
  onPrevious,
  onNext,
  backLabel = 'Quay lại hồ sơ',
}: Props) {
  return (
    <header className="review-header">
      <button className="review-header-back" onClick={onBack} aria-label={backLabel} title={backLabel}>
        ←
      </button>
      <div className="review-header-identity">
        <span className="review-header-eyebrow">HỒ SƠ CTV</span>
        <strong className="review-header-name">{name || 'Chưa khớp tên'}</strong>
        <span className="review-header-meta">
          {product || 'Chưa xác định sản phẩm'} · Trang {pages[0] + 1}–{pages[1] + 1}
        </span>
      </div>
      <MatchKeyStrip matchedBy={matchedBy} />
      <nav className="review-header-nav" aria-label="Điều hướng gói hồ sơ">
        <button
          disabled={!canPrevious}
          onClick={onPrevious}
          aria-label="Gói trước"
          title="Gói trước"
        >
          ←
        </button>
        <span>Gói {position + 1} / {count}</span>
        <button
          disabled={!canNext}
          onClick={onNext}
          aria-label="Gói sau"
          title="Gói sau"
        >
          →
        </button>
      </nav>
    </header>
  )
}
