import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Bbox, Frame } from '../types'
import type { DocRecap, EvidenceDoc } from '../ctv/types'
import { boxToViewport, inflateBbox, loupeFrame } from '../logic/loupe'
import { calloutAnchor } from '../logic/review'
import { isContentBearing } from '../logic/recap'
import { assetUrl } from '../assets'
import HotkeyHelp from './HotkeyHelp'
import RecapPopover from './RecapPopover'

interface Props {
  docs: EvidenceDoc[]
  activeDocId: string
  activePage: number
  focusBbox: Bbox | null
  lockView: boolean
  onSelectDoc: (id: string) => void
  onSelectPage: (page: number) => void
  onToggleLock: () => void
  rosterLabel?: string        // focused field label, e.g. "Số CCCD"
  rosterValue?: string | null // focused field's expected (bảng kê) value
  getRecap?: (doc: EvidenceDoc) => Promise<DocRecap>  // seam: canned (offline) or server (live)
}

export default function EvidenceViewer({
  docs, activeDocId, activePage, focusBbox, lockView, onSelectDoc, onSelectPage, onToggleLock,
  rosterLabel, rosterValue, getRecap,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [vp, setVp] = useState({ w: 0, h: 0 })
  const [frame, setFrame] = useState<Frame>({ scale: 1, tx: 0, ty: 0 })
  const [showHighlight, setShowHighlight] = useState(true) // U2: toggle the red bbox overlay
  const [showRoster, setShowRoster] = useState(true) // pin roster value callout, toggled by V
  const [panMode, setPanMode] = useState(false) // U4: drag-to-pan toggle
  const [showHelp, setShowHelp] = useState(false) // U5: hotkey reference overlay
  const [recapOpen, setRecapOpen] = useState(false)
  const [recapLoading, setRecapLoading] = useState(false)
  const [recapError, setRecapError] = useState<string | null>(null)
  const [recapCache, setRecapCache] = useState<Record<string, DocRecap>>({})
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)
  const doc = docs.find(d => d.id === activeDocId) ?? docs[0]
  const page = doc.pages[activePage] ?? doc.pages[0]
  const openRecap = useCallback(async () => {
    setRecapOpen(true); setRecapError(null)
    if (recapCache[doc.id] || !getRecap) return  // cached → instant; no resolver → nothing to fetch
    setRecapLoading(true)
    try {
      const r = await getRecap(doc)
      setRecapCache(m => ({ ...m, [doc.id]: r }))
    } catch (e) {
      setRecapError(e instanceof Error ? e.message : 'Không tạo được bản tóm tắt.')
    } finally {
      setRecapLoading(false)
    }
  }, [doc, getRecap, recapCache])
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

  // U2: `B` toggles the highlight overlay — ignored while typing in a text field (same
  // input-focus guard used by FolderReview's field/document nav).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
      if (e.key === 'b' || e.key === 'B') { e.preventDefault(); setShowHighlight(v => !v) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // `V` toggles the roster (bảng kê) value callout — independent of the `B` box toggle above,
  // same input-focus guard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
      if (e.key === 'v' || e.key === 'V') { e.preventDefault(); setShowRoster(v => !v) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // U5: `?` opens/closes the hotkey reference; Escape closes it if open. Same input-focus guard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.key === '?' || (e.shiftKey && e.key === '/')) { e.preventDefault(); setShowHelp(v => !v) }
      else if (e.key === 'Escape') setShowHelp(false)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // U4: Option/Alt + P toggles pan mode — same physical-key-code guard as Alt +/- above (⌥P
  // types 'π' on a macOS US layout), plus the input-focus guard.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (el.tagName === 'INPUT' || el.tagName === 'TEXTAREA')) return
      if (e.altKey && (e.code === 'KeyP' || e.key === 'p' || e.key === 'P' || e.key === 'π')) {
        e.preventDefault()
        setPanMode(v => !v)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  // U4: drag-to-pan while panMode is on — mousedown on the stage captures the frame's current
  // offset, then window-level mousemove/mouseup drag it (window-level so the drag keeps tracking
  // even if the cursor leaves the stage bounds mid-drag).
  const onStageMouseDown = (e: React.MouseEvent) => {
    if (!panMode) return
    e.preventDefault()
    dragRef.current = { x: e.clientX, y: e.clientY, tx: frame.tx, ty: frame.ty }
  }

  useEffect(() => {
    if (!panMode) return
    const onMove = (e: MouseEvent) => {
      const d = dragRef.current
      if (!d) return
      const tx = d.tx + (e.clientX - d.x)
      const ty = d.ty + (e.clientY - d.y)
      setFrame(f => ({ ...f, tx, ty }))
    }
    const onUp = () => { dragRef.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      dragRef.current = null
    }
  }, [panMode])

  // Close the recap when the active document changes — a recap is per-doc.
  useEffect(() => { setRecapOpen(false); setRecapError(null); setRecapLoading(false) }, [activeDocId])

  // Escape closes the recap while it's open.
  useEffect(() => {
    if (!recapOpen) return
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setRecapOpen(false) }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [recapOpen])

  const fit = () => setFrame(loupeFrame(null, nat, vp))
  const hl = showHighlight && inflated ? boxToViewport(inflated, frame) : null
  // Roster callout anchors off the field box regardless of the `B` highlight toggle — `V` is
  // an independent on/off switch, so it must not depend on `hl` (which goes null when B is off).
  const rosterBox = inflated ? boxToViewport(inflated, frame) : null
  const pageCount = doc.pages.length

  return (
    <section className="ev">
      <div className="ev-tabs">
        {docs.map(d => (
          // U3: the active document tab stands out (solid accent); the others stay neutral —
          // clearer than tinting every tab its own colour (see `.ev-tab.on` in styles.css).
          <button key={d.id} className={`ev-tab${d.id === doc.id ? ' on' : ''}`}
            onClick={() => onSelectDoc(d.id)}>
            {d.label}
          </button>
        ))}
      </div>
      <div className={panMode ? 'ev-stage panning' : 'ev-stage'} ref={ref} onMouseDown={onStageMouseDown}>
        <div className="doc-page" style={{ transform: `translate(${frame.tx}px, ${frame.ty}px) scale(${frame.scale})` }}>
          <img src={assetUrl(page.src)} width={nat.w} height={nat.h} alt="" draggable={false} />
        </div>
        {hl && <div className="doc-hl" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />}

        {showRoster && rosterValue && (
          rosterBox
            ? (() => {
                const CALLOUT_H = 52
                const a = calloutAnchor(rosterBox, CALLOUT_H, vp.h)
                return (
                  <div className={`roster-callout ${a.placement}`} style={{ left: a.left, top: a.top }}>
                    <div className="roster-callout-lbl">Bảng kê — {rosterLabel}</div>
                    <div className="roster-callout-val">{rosterValue}</div>
                  </div>
                )
              })()
            : (
                <div className="roster-callout corner">
                  <div className="roster-callout-lbl">Bảng kê — {rosterLabel}</div>
                  <div className="roster-callout-val">{rosterValue}</div>
                </div>
              )
        )}

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
          <button className={showHighlight ? 'on' : ''} onClick={() => setShowHighlight(v => !v)}
            aria-label="Ẩn/hiện khung tô sáng" title="Ẩn/hiện khung (B)">▢</button>
          <button className={showRoster ? 'on' : ''} onClick={() => setShowRoster(v => !v)}
            aria-label="Ẩn/hiện giá trị bảng kê" title="Giá trị bảng kê (V)">🏷</button>
          <button className={panMode ? 'on' : ''} onClick={() => setPanMode(v => !v)}
            aria-label="Di chuyển (pan)" title="Di chuyển (⌥P)">✋</button>
          <button className={lockView ? 'on' : ''} onClick={onToggleLock} aria-label="Khoá khung nhìn">🔒</button>
          <button onClick={() => setShowHelp(v => !v)} aria-label="Danh sách phím tắt" title="Phím tắt (?)">?</button>
          {getRecap && isContentBearing(doc.kind) && (
            <button className={recapOpen ? 'on' : ''} onClick={openRecap}
              aria-label="AI tóm tắt tài liệu" title="AI tóm tắt tài liệu">✨</button>
          )}
        </div>

        {recapOpen && (
          <RecapPopover loading={recapLoading} error={recapError}
            recap={recapCache[doc.id] ?? null} docLabel={doc.label}
            onClose={() => setRecapOpen(false)} />
        )}
      </div>
      <HotkeyHelp open={showHelp} onClose={() => setShowHelp(false)} />
    </section>
  )
}
