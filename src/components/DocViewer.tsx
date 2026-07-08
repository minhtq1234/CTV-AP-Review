import { useLayoutEffect, useRef, useState } from 'react'
import type { Bbox, DocPage, Frame } from '../types'
import { boxToViewport, loupeFrame } from '../logic/loupe'

interface DocViewerProps {
  pages: DocPage[]; page: number; focusBbox: Bbox | null
  lockView: boolean; onPageChange: (p: number) => void; onToggleLock: () => void
}

export default function DocViewer({ pages, page, focusBbox, lockView, onPageChange, onToggleLock }: DocViewerProps) {
  const ref = useRef<HTMLDivElement>(null)
  const [vp, setVp] = useState({ w: 0, h: 0 })
  const [frame, setFrame] = useState<Frame>({ scale: 1, tx: 0, ty: 0 })
  const nat = { w: pages[page].width, h: pages[page].height }

  useLayoutEffect(() => {
    const el = ref.current!
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useLayoutEffect(() => {
    if (lockView || vp.w === 0) return
    setFrame(loupeFrame(focusBbox, nat, vp))
  }, [focusBbox, vp.w, vp.h, page, lockView])

  const zoom = (factor: number) => setFrame(f => {
    const s = Math.max(0.1, Math.min(6, f.scale * factor))
    const cx = (vp.w / 2 - f.tx) / f.scale, cy = (vp.h / 2 - f.ty) / f.scale
    return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
  })
  const fit = () => setFrame(loupeFrame(null, nat, vp))

  const hl = focusBbox ? boxToViewport(focusBbox, frame) : null

  return (
    <section className="doc-pane" ref={ref}>
      <div className="doc-page" style={{ transform: `translate(${frame.tx}px, ${frame.ty}px) scale(${frame.scale})` }}>
        <img src={pages[page].src} width={nat.w} height={nat.h} alt="" />
      </div>
      {hl && <div className="doc-hl" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />}

      <div className="doc-badge">Trang {page + 1} / {pages.length}{pages[page].label ? ` · ${pages[page].label}` : ''}</div>

      <div className="doc-nav">
        <button disabled={page === 0} onClick={() => onPageChange(page - 1)} aria-label="Trang trước">‹</button>
        <button disabled={page === pages.length - 1} onClick={() => onPageChange(page + 1)} aria-label="Trang sau">›</button>
      </div>

      <div className="doc-tools">
        <button onClick={fit} aria-label="Vừa khung">⤢</button>
        <button onClick={() => zoom(0.8)} aria-label="Thu nhỏ">−</button>
        <span>{Math.round(frame.scale * 100)}%</span>
        <button onClick={() => zoom(1.25)} aria-label="Phóng to">+</button>
        <button className={lockView ? 'on' : ''} onClick={onToggleLock} aria-label="Khoá khung nhìn">🔒</button>
      </div>
    </section>
  )
}
