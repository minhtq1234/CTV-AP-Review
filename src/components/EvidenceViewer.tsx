import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type { CSSProperties } from 'react'
import type { Bbox } from '../types'
import type { EvidenceDoc } from '../ctv/types'
import { inflateBbox } from '../logic/loupe'
import {
  DOCUMENT_VIEW_MODES,
  autofocusZoomLevel,
  bboxPercentStyle,
  clampPageIndex,
  groupPageIndexes,
  isDocumentPanEnabled,
  type DocumentViewMode,
} from '../logic/documentView'
import { assetUrl } from '../assets'
import HotkeyHelp from './HotkeyHelp'

interface Props {
  docs: EvidenceDoc[]
  activeDocId: string
  activePage: number
  focusBbox: Bbox | null
  lockView: boolean
  onSelectDoc: (id: string) => void
  onToggleLock: () => void
  rosterLabel?: string
  rosterValue?: string | null
}

const inputHasFocus = (target: EventTarget | null) => {
  const element = target as HTMLElement | null
  return element?.tagName === 'INPUT' || element?.tagName === 'TEXTAREA'
}

export default function EvidenceViewer({
  docs,
  activeDocId,
  activePage,
  focusBbox,
  lockView,
  onSelectDoc,
  onToggleLock,
  rosterLabel,
  rosterValue,
}: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const pageRefs = useRef<Record<number, HTMLDivElement | null>>({})
  const focusAnchorRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<{
    x: number
    y: number
    scrollLeft: number
    scrollTop: number
  } | null>(null)
  const [viewMode, setViewMode] = useState<DocumentViewMode>('single')
  const [zoomLevel, setZoomLevel] = useState(1)
  const [showHighlight, setShowHighlight] = useState(true)
  const [showRoster, setShowRoster] = useState(true)
  const [panMode, setPanMode] = useState(false)
  const [showHelp, setShowHelp] = useState(false)
  const panEnabled = isDocumentPanEnabled(panMode, zoomLevel)

  const doc = docs.find(candidate => candidate.id === activeDocId) ?? docs[0]
  const pageCount = doc?.pages.length ?? 0
  const pageIndex = clampPageIndex(activePage, pageCount)
  const pageGroups = groupPageIndexes(pageCount, viewMode)

  const focusedBox = useMemo(() => {
    if (!focusBbox || !doc?.pages[pageIndex]) return null
    const page = doc.pages[pageIndex]
    return inflateBbox(focusBbox, 0.2, page.width, page.height)
  }, [focusBbox, doc, pageIndex])

  useEffect(() => {
    if (lockView) return
    const scroll = scrollRef.current
    const pageElement = pageRefs.current[pageIndex]
    const page = doc?.pages[pageIndex]
    if (!focusedBox || !scroll || !pageElement || !page) return

    setZoomLevel(current => autofocusZoomLevel(
      focusedBox,
      pageElement.getBoundingClientRect().width / current,
      page.width,
      scroll.clientHeight,
    ))
  }, [activeDocId, pageIndex, focusedBox, viewMode, lockView, doc])

  useEffect(() => {
    if (lockView) return
    const animationFrame = requestAnimationFrame(() => {
      const target = focusedBox ? focusAnchorRef.current : pageRefs.current[pageIndex]
      target?.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
        inline: focusedBox ? 'center' : 'nearest',
      })
    })
    return () => cancelAnimationFrame(animationFrame)
  }, [activeDocId, pageIndex, focusedBox, viewMode, zoomLevel, lockView])

  const zoom = useCallback((factor: number) => {
    setZoomLevel(current => Math.max(0.5, Math.min(4, current * factor)))
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (!event.altKey) return
      const key = event.key
      if (event.code === 'Equal' || key === '=' || key === '+' || key === '≠' || key === '±') {
        event.preventDefault()
        zoom(1.25)
      } else if (
        event.code === 'Minus'
        || key === '-'
        || key === '_'
        || key === '–'
        || key === '—'
      ) {
        event.preventDefault()
        zoom(0.8)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [zoom])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (inputHasFocus(event.target)) return
      if (event.altKey || event.ctrlKey || event.metaKey) return
      if (event.key === 'b' || event.key === 'B') {
        event.preventDefault()
        setShowHighlight(value => !value)
      } else if (event.key === 'v' || event.key === 'V') {
        event.preventDefault()
        setShowRoster(value => !value)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (inputHasFocus(event.target)) return
      if (event.key === '?' || (event.shiftKey && event.key === '/')) {
        event.preventDefault()
        setShowHelp(value => !value)
      } else if (event.key === 'Escape') {
        setShowHelp(false)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (inputHasFocus(event.target)) return
      if (event.altKey && (
        event.code === 'KeyP'
        || event.key === 'p'
        || event.key === 'P'
        || event.key === 'π'
      )) {
        event.preventDefault()
        setPanMode(value => !value)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  const onPanStart = (event: React.MouseEvent<HTMLDivElement>) => {
    if (!panEnabled || !scrollRef.current) return
    event.preventDefault()
    dragRef.current = {
      x: event.clientX,
      y: event.clientY,
      scrollLeft: scrollRef.current.scrollLeft,
      scrollTop: scrollRef.current.scrollTop,
    }
  }

  useEffect(() => {
    if (!panEnabled) return
    const onMove = (event: MouseEvent) => {
      const start = dragRef.current
      const scroll = scrollRef.current
      if (!start || !scroll) return
      scroll.scrollLeft = start.scrollLeft - (event.clientX - start.x)
      scroll.scrollTop = start.scrollTop - (event.clientY - start.y)
    }
    const onUp = () => { dragRef.current = null }
    window.addEventListener('mousemove', onMove)
    window.addEventListener('mouseup', onUp)
    return () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
      dragRef.current = null
    }
  }, [panEnabled])

  if (!doc) return null

  const documentStyle: CSSProperties = {
    width: `${92 * zoomLevel}%`,
  }

  return (
    <section className="ev">
      <div className="ev-tabs">
        {docs.map(candidate => (
          <button
            key={candidate.id}
            className={`ev-tab${candidate.id === doc.id ? ' on' : ''}`}
            onClick={() => onSelectDoc(candidate.id)}
          >
            {candidate.label}
          </button>
        ))}
      </div>

      <div className="ev-view">
        <div className="ev-modes" role="group" aria-label="Chế độ xem tài liệu">
          {DOCUMENT_VIEW_MODES.map(option => (
            <button
              key={option.mode}
              className={viewMode === option.mode ? 'on' : ''}
              onClick={() => setViewMode(option.mode)}
            >
              {option.label}
            </button>
          ))}
        </div>

        <div
          className={`ev-scroll${panEnabled ? ' panning' : ''}`}
          ref={scrollRef}
          onMouseDown={onPanStart}
        >
          <div className={`ev-document ${viewMode}`} style={documentStyle}>
            {pageGroups.map((indexes, rowIndex) => (
              <div className="document-page-row" key={rowIndex}>
                {indexes.map(index => {
                  const page = doc.pages[index]
                  const isFocusedPage = index === pageIndex
                  const focusStyle = isFocusedPage && focusedBox
                    ? bboxPercentStyle(focusedBox, page.width, page.height)
                    : null
                  return (
                    <div
                      className="document-page"
                      data-page-index={index}
                      data-active-page={isFocusedPage ? 'true' : undefined}
                      key={index}
                      ref={element => { pageRefs.current[index] = element }}
                    >
                      <img
                        src={assetUrl(page.src)}
                        width={page.width}
                        height={page.height}
                        alt=""
                        draggable={false}
                      />
                      {focusStyle && (
                        <div
                          className="document-focus-anchor"
                          ref={focusAnchorRef}
                          style={focusStyle}
                        >
                          {showHighlight && <div className="doc-hl-fill" />}
                          {showRoster && rosterValue && (
                            <div className="roster-callout attached">
                              <div className="roster-callout-lbl">Bảng kê — {rosterLabel}</div>
                              <div className="roster-callout-val">{rosterValue}</div>
                            </div>
                          )}
                        </div>
                      )}
                      {isFocusedPage && !focusStyle && showRoster && rosterValue && (
                        <div className="roster-callout corner">
                          <div className="roster-callout-lbl">Bảng kê — {rosterLabel}</div>
                          <div className="roster-callout-val">{rosterValue}</div>
                        </div>
                      )}
                    </div>
                  )
                })}
              </div>
            ))}
          </div>
        </div>

        <div className="doc-tools">
          <button onClick={() => setZoomLevel(1)} aria-label="Vừa khung" title="Vừa khung">⤢</button>
          <span className="tool-divider" aria-hidden="true" />
          <button onClick={() => zoom(0.8)} aria-label="Thu nhỏ" title="Thu nhỏ (⌥−)">−</button>
          <span className="zoom-value">{Math.round(zoomLevel * 100)}%</span>
          <button onClick={() => zoom(1.25)} aria-label="Phóng to" title="Phóng to (⌥+)">+</button>
          <span className="tool-divider" aria-hidden="true" />
          <button
            className={showHighlight ? 'on' : ''}
            onClick={() => setShowHighlight(value => !value)}
            aria-label="Ẩn/hiện khung tô sáng"
            title="Ẩn/hiện khung (B)"
          >
            ▢
          </button>
          <button
            className={showRoster ? 'on' : ''}
            onClick={() => setShowRoster(value => !value)}
            aria-label="Ẩn/hiện giá trị bảng kê"
            title="Giá trị bảng kê (V)"
          >
            🏷
          </button>
          <button
            className={panMode ? 'on' : ''}
            onClick={() => setPanMode(value => !value)}
            aria-label="Di chuyển (pan)"
            title="Di chuyển (⌥P)"
          >
            ✋
          </button>
          <button
            className={lockView ? 'on' : ''}
            onClick={onToggleLock}
            aria-label="Khoá khung nhìn"
            title="Khoá khung nhìn"
          >
            🔒
          </button>
          <button
            onClick={() => setShowHelp(value => !value)}
            aria-label="Danh sách phím tắt"
            title="Phím tắt (?)"
          >
            ?
          </button>
        </div>
      </div>
      <HotkeyHelp open={showHelp} onClose={() => setShowHelp(false)} />
    </section>
  )
}
