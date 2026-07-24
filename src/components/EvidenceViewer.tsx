import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import type { Bbox, Frame } from '../types'
import type { EvidenceDoc } from '../ctv/types'
import { boxToViewport, inflateBbox, loupeFrame } from '../logic/loupe'
import { calloutAnchor } from '../logic/review'
import { clampPage } from '../logic/pageNav'
import { ViewMode, VIEW_MODES, clampZoom } from '../logic/viewMode'
import { assetUrl } from '../assets'
import HotkeyHelp from './HotkeyHelp'

interface Props {
  docs: EvidenceDoc[]
  activeDocId: string
  activePage: number
  focusBbox: Bbox | null
  focusCaption?: string | null   // #7 signature-band caption (soft band instead of the red box)
  lockView: boolean
  viewMode: ViewMode
  onSetViewMode: (m: ViewMode) => void
  onSelectDoc: (id: string) => void
  onSelectPage: (page: number) => void
  onToggleLock: () => void
  rosterLabel?: string        // focused field label, e.g. "Số CCCD"
  rosterValue?: string | null // focused field's expected (bảng kê) value
}

export default function EvidenceViewer({
  docs, activeDocId, activePage, focusBbox, focusCaption, lockView, viewMode, onSetViewMode,
  onSelectDoc, onSelectPage, onToggleLock, rosterLabel, rosterValue,
}: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const scrollRef = useRef<HTMLDivElement>(null)
  const [vp, setVp] = useState({ w: 0, h: 0 })
  const [frame, setFrame] = useState<Frame>({ scale: 1, tx: 0, ty: 0 })
  const [contZoom, setContZoom] = useState(1) // continuous-mode width multiplier (native scroll)
  const [showHighlight, setShowHighlight] = useState(true) // U2: toggle the red bbox overlay
  const [showRoster, setShowRoster] = useState(true) // pin roster value callout, toggled by V
  const [panMode, setPanMode] = useState(false) // U4: drag-to-pan toggle
  const [showHelp, setShowHelp] = useState(false) // U5: hotkey reference overlay
  const dragRef = useRef<{ x: number; y: number; tx: number; ty: number } | null>(null)
  const doc = docs.find(d => d.id === activeDocId) ?? docs[0]
  const pageCount = doc.pages.length
  const pageIdx = clampPage(activePage, pageCount)   // never out of range
  const page = doc.pages[pageIdx] ?? doc.pages[0]
  const nat = { w: page.width, h: page.height }
  // U1: highlight (and the loupe frame it drives) is drawn ~20% larger on each side than the
  // raw field bbox, so the boxed area includes a bit of surrounding context. Memoized so it
  // keeps a stable reference across re-renders that don't actually change the source bbox
  // (e.g. a zoom/pan update) -- otherwise the effect below would re-fit the frame on every render.
  const inflated = useMemo(
    () => focusBbox ? inflateBbox(focusBbox, 0.2, nat.w, nat.h) : null,
    [focusBbox, nat.w, nat.h],
  )

  // View-mode geometry. `1`/`cont` show a single page; `2` shows an even-aligned pair laid out
  // in a row (natCombined = summed widths + gaps, tallest height) so the fit math frames both.
  const isCont = viewMode === 'cont'
  const gap = 16
  const pairStart = viewMode === '2' ? pageIdx - (pageIdx % 2) : pageIdx
  const step = viewMode === '2' ? 2 : 1
  const pagesInView = viewMode === '2' ? doc.pages.slice(pairStart, pairStart + 2) : [page]
  const natCombined = viewMode === '2'
    ? { w: pagesInView.reduce((s, p) => s + p.width, 0) + gap * (pagesInView.length - 1),
        h: Math.max(...pagesInView.map(p => p.height)) }
    : nat

  useLayoutEffect(() => {
    const el = ref.current!
    const ro = new ResizeObserver(() => setVp({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    return () => ro.disconnect()
  }, [])

  // Auto-fit/zoom to the focused bbox — ONLY in single-page mode. The other modes never
  // auto-focus (2 trang fits the pair below; Cuộn liên tục uses native scroll).
  useLayoutEffect(() => {
    if (viewMode !== '1' || lockView || vp.w === 0) return
    setFrame(loupeFrame(inflated, nat, vp))
  }, [inflated, vp.w, vp.h, activeDocId, pageIdx, lockView, viewMode])

  // 2 trang: fit the current page pair (no bbox zoom) whenever the pair or viewport changes.
  useLayoutEffect(() => {
    if (viewMode !== '2' || lockView || vp.w === 0) return
    setFrame(loupeFrame(null, natCombined, vp))
  }, [viewMode, pairStart, activeDocId, vp.w, vp.h, lockView])

  // Cuộn liên tục: reset the native scroll to the top when entering the mode or changing doc.
  useLayoutEffect(() => { if (isCont && scrollRef.current) scrollRef.current.scrollTop = 0 }, [isCont, activeDocId])

  // Mode-aware zoom: in continuous mode nudge the width multiplier (native scroll handles the
  // rest); in the transform modes re-scale the frame about the viewport centre.
  const zoom = useCallback((factor: number) => {
    if (isCont) { setContZoom(z => clampZoom(z * factor)); return }
    setFrame(f => {
      const s = Math.max(0.1, Math.min(6, f.scale * factor))
      const cx = (vp.w / 2 - f.tx) / f.scale, cy = (vp.h / 2 - f.ty) / f.scale
      return { scale: s, tx: vp.w / 2 - cx * s, ty: vp.h / 2 - cy * s }
    })
  }, [vp.w, vp.h, isCont])

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
  // even if the cursor leaves the stage bounds mid-drag). No-op in continuous mode (native
  // scroll instead — the stage isn't rendered, so mousedown never fires there).
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

  // ⤢ resets the transform to fit the page (single) / pair (2 trang), or the width multiplier
  // in continuous mode.
  const fit = () => {
    if (isCont) { setContZoom(1); return }
    setFrame(loupeFrame(null, natCombined, vp))
  }
  const hl = showHighlight && inflated ? boxToViewport(inflated, frame) : null
  // Roster callout anchors off the field box regardless of the `B` highlight toggle — `V` is
  // an independent on/off switch, so it must not depend on `hl` (which goes null when B is off).
  const rosterBox = inflated ? boxToViewport(inflated, frame) : null
  const zoomPct = Math.round((isCont ? contZoom : frame.scale) * 100)

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
      <div className="ev-view" ref={ref}>
        <div className="ev-modes">
          {VIEW_MODES.map(m => (
            <button key={m.mode} className={m.mode === viewMode ? 'on' : ''}
              onClick={() => onSetViewMode(m.mode)}>{m.label}</button>
          ))}
        </div>

        {isCont ? (
          <div className="ev-scroll" ref={scrollRef}>
            {doc.pages.map((p, i) => (
              <img key={i} className="cont-page" src={assetUrl(p.src)}
                style={{ width: (vp.w * 0.92) * contZoom, height: 'auto' }} alt="" draggable={false} />
            ))}
          </div>
        ) : (
          <div className={panMode ? 'ev-stage panning' : 'ev-stage'} onMouseDown={onStageMouseDown}>
            <div className="doc-page" style={{ transform: `translate(${frame.tx}px, ${frame.ty}px) scale(${frame.scale})` }}>
              {pagesInView.map((p, i) => (
                <img key={i} src={assetUrl(p.src)} width={p.width} height={p.height}
                  style={{ marginLeft: i > 0 ? gap : 0 }} alt="" draggable={false} />
              ))}
            </div>
            {viewMode === '1' && !focusCaption && hl && <div className="doc-hl" style={{ left: hl.left, top: hl.top, width: hl.width, height: hl.height }} />}

            {/* #7 signature landing: a soft dashed band + caption instead of the red value box.
                Positioned off the highlight-independent box so it shows even when B is toggled off. */}
            {viewMode === '1' && focusCaption && rosterBox && (
              <>
                <div className="doc-hl soft" style={{ left: rosterBox.left, top: rosterBox.top, width: rosterBox.width, height: rosterBox.height }} />
                <div className="doc-caption" style={{ left: rosterBox.left, top: rosterBox.top - 26 }}>{focusCaption}</div>
              </>
            )}

            {viewMode === '1' && showRoster && rosterValue && (
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
          </div>
        )}

        {!isCont && pageCount > 1 && (
          <div className="doc-pager">
            <button disabled={pairStart === 0} onClick={() => onSelectPage(Math.max(0, pageIdx - step))} aria-label="Trang trước">‹</button>
            <span>{viewMode === '2' ? `${pairStart + 1}–${Math.min(pairStart + 2, pageCount)} / ${pageCount}` : `${pageIdx + 1} / ${pageCount}`}</span>
            <button disabled={pairStart + step >= pageCount} onClick={() => onSelectPage(Math.min(pageCount - 1, pageIdx + step))} aria-label="Trang sau">›</button>
          </div>
        )}

        <div className="doc-tools">
          <button onClick={fit} aria-label="Vừa khung">⤢</button>
          <button onClick={() => zoom(0.8)} aria-label="Thu nhỏ">−</button>
          <span>{zoomPct}%</span>
          <button onClick={() => zoom(1.25)} aria-label="Phóng to">+</button>
          <button className={showHighlight ? 'on' : ''} onClick={() => setShowHighlight(v => !v)}
            aria-label="Ẩn/hiện khung tô sáng" title="Ẩn/hiện khung (B)">▢</button>
          <button className={showRoster ? 'on' : ''} onClick={() => setShowRoster(v => !v)}
            aria-label="Ẩn/hiện giá trị bảng kê" title="Giá trị bảng kê (V)">🏷</button>
          <button className={panMode ? 'on' : ''} onClick={() => setPanMode(v => !v)}
            aria-label="Di chuyển (pan)" title="Di chuyển (⌥P)">✋</button>
          <button className={lockView ? 'on' : ''} onClick={onToggleLock} aria-label="Khoá khung nhìn">🔒</button>
          <button onClick={() => setShowHelp(v => !v)} aria-label="Danh sách phím tắt" title="Phím tắt (?)">?</button>
        </div>
      </div>
      <HotkeyHelp open={showHelp} onClose={() => setShowHelp(false)} />
    </section>
  )
}
