interface ActionBarProps {
  done: boolean
  seenCount: number
  total: number
  hint?: string
  onFinish: () => void
}

export default function ActionBar({ done, seenCount, total, hint, onFinish }: ActionBarProps) {
  const remaining = total - seenCount
  const canFinish = remaining <= 0
  if (done) {
    return (
      <div className="action-bar">
        <span className="final approved">✓ Đã xem xong</span>
      </div>
    )
  }
  return (
    <div className="action-bar">
      <span className="hint">{hint ?? '↑↓ chuyển trường'}</span>
      <div className="actions">
        <span className="seen-progress">{seenCount}/{total} đã xem</span>
        <button className="btn primary" disabled={!canFinish} onClick={onFinish}
          title={canFinish ? 'Đánh dấu đã xem xong' : `Còn ${remaining} trường chưa xem`}>
          ✓ Xong
        </button>
      </div>
    </div>
  )
}
