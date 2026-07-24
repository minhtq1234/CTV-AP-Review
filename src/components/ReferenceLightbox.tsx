import { useEffect } from 'react'
import { assetUrl } from '../assets'

interface Props { src: string | null; title: string; onClose: () => void }

// #6: a modal over the scan pane showing a blank reference template (the
// submitted doc stays underneath). Esc / backdrop / ✕ close it. No review state.
export default function ReferenceLightbox({ src, title, onClose }: Props) {
  useEffect(() => {
    if (!src) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [src, onClose])
  if (!src) return null
  return (
    <div className="ref-backdrop" onClick={onClose}>
      <div className="ref-panel" onClick={e => e.stopPropagation()}>
        <div className="ref-head">
          <strong>{title}</strong>
          <button className="ref-close" onClick={onClose} aria-label="Đóng">✕</button>
        </div>
        <div className="ref-body">
          <img src={assetUrl(src)} alt={title} draggable={false} />
        </div>
      </div>
    </div>
  )
}
