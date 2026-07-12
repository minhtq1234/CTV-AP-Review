import { useLayoutEffect, useRef, useState } from 'react'
import type { Bbox, Frame } from '../types'
import type { EvidenceDoc } from '../ctv/types'
import { boxToViewport, loupeFrame } from '../logic/loupe'

interface Props {
  docs: EvidenceDoc[]
  activeDocId: string
  focusBbox: Bbox | null
  lockView: boolean
  onSelectDoc: (id: string) => void
  onToggleLock: () => void
}

export default function EvidenceViewer({ docs, activeDocId, focusBbox, lockView, onSelectDoc, onToggleLock }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [vp, setVp] = useState({ w: 0, h: 0 })
  const [frame, setFrame] = useState<Frame>({ scale: 1, tx: 0, ty: 0 })
  const doc = docs.find(d => d.id === activeDocId) ?? docs[0]
  const nat = { w: doc.width, h: doc.height }

  useLayoutEffect(() => {
    const el = ref.current!
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useLayoutEffect(() => {
    if (lockView || vp.w === 0) return
    setFrame(loupeFrame(focusBbox, nat, vp))
  }, [focusBbox, vp.w, vp.h, activeDocId, lockView])

  const zoom = (factor: number) => setFrame(f => {
    const s = Math.max(0.1, Math.min(6, f.scale * factor))
    const cx = (vp.w / 2 - f.tx) / f.scale, cy = (vp.h / 2 - f.ty) / f.scale
    return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
  })
  const fit = () => setFrame(loupeFrame(null, nat, vp))
  const hl = focusBbox ? boxToViewport(focusBbox, frame) : null

  return (
    <section className="ev">
      <div className="ev-tabs">
        {docs.map(d => (
          <button key={d.id} className={d.id === doc.id ? 'ev-tab on' : 'ev-tab'} onClick={() => onSelectDoc(d.id)}>
            {d.label}
          </button>
        ))}
      </div>
      <div className="ev-stage" ref={ref}>
        <div className="doc-page" style={{ transform: `translate(${frame.tx}px, ${frame.ty}px) scale(${frame.scale})` }}>
          <img src={doc.src} width={nat.w} height={nat.h} alt="" />
        </div>
        {hl && <div className="doc-hl" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />}
        <div className="doc-tools">
          <button onClick={fit} aria-label="Vừa khung">⤢</button>
          <button onClick={() => zoom(0.8)} aria-label="Thu nhỏ">−</button>
          <span>{Math.round(frame.scale * 100)}%</span>
          <button onClick={() => zoom(1.25)} aria-label="Phóng to">+</button>
          <button className={lockView ? 'on' : ''} onClick={onToggleLock} aria-label="Khoá khung nhìn">🔒</button>
        </div>
      </div>
    </section>
  )
}
