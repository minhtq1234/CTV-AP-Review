import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Bbox, Frame } from '../types'
import type { EvidenceDoc } from '../ctv/types'
import { boxToViewport, inflateBbox, loupeFrame } from '../logic/loupe'
import { assetUrl } from '../assets'

interface Props {
  docs: EvidenceDoc[]
  activeDocId: string
  activePage: number
  focusBbox: Bbox | null
  lockView: boolean
  onSelectDoc: (id: string) => void
  onSelectPage: (page: number) => void
  onToggleLock: () => void
}

export default function EvidenceViewer({
  docs, activeDocId, activePage, focusBbox, lockView, onSelectDoc, onSelectPage, onToggleLock,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [vp, setVp] = useState({ w: 0, h: 0 })
  const [frame, setFrame] = useState<Frame>({ scale: 1, tx: 0, ty: 0 })
  const doc = docs.find(d => d.id === activeDocId) ?? docs[0]
  const page = doc.pages[activePage] ?? doc.pages[0]
  const nat = { w: page.width, h: page.height }
  // U1: highlight (and the loupe frame it drives) is drawn ~20% larger on each side than the
  // raw field bbox, so the boxed area includes a bit of surrounding context. Memoized so it
  // keeps a stable reference across re-renders that don't actually change the source bbox
  // (e.g. a zoom/pan update) -- otherwise the effect below would re-fit the frame on every render.
  const inflated = useMemo(
    () => focusBbox ? inflateBbox(focusBbox, 0.2, nat.w, nat.h) : null,
    [focusBbox, nat.w, nat.h],
  )

  useLayoutEffect(() => {
    const el = ref.current!
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  useLayoutEffect(() => {
    if (lockView || vp.w === 0) return
    setFrame(loupeFrame(inflated, nat, vp))
  }, [inflated, vp.w, vp.h, activeDocId, activePage, lockView])

  const zoom = useCallback((factor: number) => setFrame(f => {
    const s = Math.max(0.1, Math.min(6, f.scale * factor))
    const cx = (vp.w / 2 - f.tx) / f.scale, cy = (vp.h / 2 - f.ty) / f.scale
    return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
  }), [vp.w, vp.h])

  // Alt +/- to zoom — uses physical key codes so ⌥ on macOS works (⌥- would type an en-dash).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey) return
      const k = e.key
      if (e.code === 'Equal' || k === '=' || k === '+' || k === '≠' || k === '±') { e.preventDefault(); zoom(1.25) }
      else if (e.code === 'Minus' || k === '-' || k === '_' || k === '–' || k === '—') { e.preventDefault(); zoom(0.8) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [zoom])
  const fit = () => setFrame(loupeFrame(null, nat, vp))
  const hl = inflated ? boxToViewport(inflated, frame) : null
  const pageCount = doc.pages.length

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
          <img src={assetUrl(page.src)} width={nat.w} height={nat.h} alt="" />
        </div>
        {hl && <div className="doc-hl" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />}

        {pageCount > 1 && (
          <div className="doc-pager">
            <button disabled={activePage === 0} onClick={() => onSelectPage(activePage - 1)} aria-label="Trang trước">‹</button>
            <span>{activePage + 1} / {pageCount}</span>
            <button disabled={activePage === pageCount - 1} onClick={() => onSelectPage(activePage + 1)} aria-label="Trang sau">›</button>
          </div>
        )}

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
