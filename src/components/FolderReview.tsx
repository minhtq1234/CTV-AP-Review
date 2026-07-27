import { useEffect, useMemo, useState } from 'react'
import type { Bbox } from '../types'
import type { CtvFolder } from '../ctv/types'
import { rankFolder } from '../ctv/checks'
import type { PacketReview, FieldFlag } from '../upload/api'
import { allSeen } from '../logic/review'
import {
  fieldSelection,
  moveVerticalSelection,
  overviewSelection,
  selectedFieldKey,
  type ReviewSelection,
} from '../logic/reviewSelection'
import { formatRosterValue } from '../logic/reviewValue'
import {
  rejectedReview,
  undoRejectedReview,
} from '../logic/packetRejection'
import FolderFieldsPanel from './FolderFieldsPanel'
import EvidenceViewer from './EvidenceViewer'
import ActionBar from './ActionBar'
import PacketRejectionDialog from './PacketRejectionDialog'

interface Props {
  folder: CtvFolder
  review: PacketReview
  onReview: (review: PacketReview) => void
  onCommitReview: (review: PacketReview) => Promise<void>
}

const SAVE_ERROR = 'Không lưu được. Vui lòng thử lại.'

export default function FolderReview({
  folder,
  review,
  onReview,
  onCommitReview,
}: Props) {
  const ranked = useMemo(() => rankFolder(folder), [folder])
  const [selection, setSelection] = useState<ReviewSelection>(
    overviewSelection,
  )
  const [activeDocId, setActiveDocId] = useState(folder.docs[0]?.id ?? '')
  const [activePage, setActivePage] = useState(0)
  const [focusBbox, setFocusBbox] = useState<Bbox | null>(null)
  const [lockView, setLockView] = useState(false)
  const [rejectionDialogOpen, setRejectionDialogOpen] = useState(false)
  const [rejectionSaving, setRejectionSaving] = useState(false)
  const [rejectionError, setRejectionError] = useState<string | null>(null)

  // Mark a field as seen the first time it is explicitly focused — a no-op (no onReview call)
  // if it's already seen, so re-focusing it never loops.
  const markSeen = (key: string) => {
    if (review.fields[key]?.seen) return
    onReview({
      ...review,
      fields: { ...review.fields, [key]: { seen: true, flag: review.fields[key]?.flag ?? null } },
    })
  }

  const toggleFlag = (key: string, flag: FieldFlag | null) => {
    onReview({ ...review, fields: { ...review.fields, [key]: { seen: true, flag } } })
  }

  const selectOverview = () => {
    setSelection(overviewSelection())
    setActiveDocId(folder.docs[0]?.id ?? '')
    setActivePage(0)
    setFocusBbox(null)
  }

  // Focus the sourceIndex-th source (document) of a field, or clear the highlight if it has none.
  const focusAt = (key: string, sourceIndex: number) => {
    setSelection(fieldSelection(key, sourceIndex))
    markSeen(key)
    const s = folder.fields.find(f => f.key === key)?.sources[sourceIndex]
    if (s) { setActiveDocId(s.docId); setActivePage(s.page); setFocusBbox(s.bbox) }
    else setFocusBbox(null)
  }

  // Switching document by tab (#006): if the currently selected field has a source on the
  // newly-active document, jump straight to it (same as clicking that source's chip) so
  // walking a field across its documents is one click per doc, eye always guided. Only clear
  // the highlight when the field genuinely has no source there.
  const onSelectDoc = (id: string) => {
    if (selection.kind === 'overview') {
      setActiveDocId(id)
      setActivePage(0)
      setFocusBbox(null)
      return
    }

    const sourceIndex = folder.fields
      .find(field => field.key === selection.key)
      ?.sources.findIndex(source => source.docId === id) ?? -1

    if (sourceIndex >= 0) focusAt(selection.key, sourceIndex)
    else { setActiveDocId(id); setActivePage(0); setFocusBbox(null) }
  }

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (
        ['INPUT', 'TEXTAREA', 'BUTTON', 'SELECT'].includes(el.tagName)
        || el.closest('.packet-rejection-dialog')
      )) return
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        const nextSelection = moveVerticalSelection(
          selection,
          ranked.map(row => row.field.key),
          e.key === 'ArrowDown' ? 'down' : 'up',
        )
        if (nextSelection.kind === 'overview') selectOverview()
        else focusAt(nextSelection.key, nextSelection.sourceIndex)
      } else if (e.key === 'ArrowRight' || e.key === 'ArrowLeft') {
        if (selection.kind === 'overview') return
        const n = folder.fields.find(f => f.key === selection.key)?.sources.length ?? 0
        if (n < 2) return // nothing to step through
        e.preventDefault()
        const next = e.key === 'ArrowRight'
          ? Math.min(selection.sourceIndex + 1, n - 1)
          : Math.max(selection.sourceIndex - 1, 0)
        focusAt(selection.key, next) // same field → next document
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [ranked, selection, folder])

  // `F` toggles a flag on the currently selected field — separate from the arrow-nav effect
  // above, same input-focus guard, plus skipping modified keystrokes so browser/OS shortcuts
  // (e.g. ⌘F find) pass through untouched.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      if (el && (
        ['INPUT', 'TEXTAREA', 'BUTTON', 'SELECT'].includes(el.tagName)
        || el.closest('.packet-rejection-dialog')
      )) return
      if (e.altKey || e.ctrlKey || e.metaKey) return
      if (e.key === 'f' || e.key === 'F') {
        if (selection.kind === 'overview') return
        e.preventDefault()
        const cur = review.fields[selection.key]?.flag
        toggleFlag(selection.key, cur ? null : { reason: '', note: '' })
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [review, selection])

  const selectedKey = selectedFieldKey(selection)
  const selField = selectedKey
    ? folder.fields.find(field => field.key === selectedKey)
    : undefined
  const fieldKeys = folder.fields.map(f => f.key)
  const seenCount = fieldKeys.filter(k => review.fields[k]?.seen).length

  const commitPacketReview = async (candidate: PacketReview) => {
    setRejectionSaving(true)
    setRejectionError(null)
    try {
      await onCommitReview(candidate)
      setRejectionDialogOpen(false)
    } catch {
      setRejectionError(SAVE_ERROR)
    } finally {
      setRejectionSaving(false)
    }
  }

  return (
    <div className="screen">
      <div className="panes">
        <FolderFieldsPanel
          ranked={ranked}
          selection={selection}
          onSelectOverview={selectOverview}
          onSelectField={key => focusAt(key, 0)}
          review={review}
          onToggleFlag={toggleFlag}
          onOpenPacketRejection={() => {
            setRejectionError(null)
            setRejectionDialogOpen(true)
          }}
        />
        <EvidenceViewer
          docs={folder.docs}
          activeDocId={activeDocId}
          activePage={activePage}
          focusBbox={focusBbox}
          lockView={lockView}
          overviewMode={selection.kind === 'overview'}
          onSelectDoc={onSelectDoc}
          onToggleLock={() => setLockView(v => !v)}
          rosterLabel={selField?.label}
          rosterValue={selField ? formatRosterValue(selField) : null}
        />
      </div>
      <ActionBar
        done={review.done}
        seenCount={seenCount}
        total={fieldKeys.length}
        hint="↑↓ chuyển trường · ←→ đổi chứng từ · F đánh dấu · B khung · V giá trị bảng kê · ⌥P di chuyển · ? phím tắt"
        onFinish={() => { if (allSeen(review, fieldKeys)) onReview({ ...review, done: true }) }}
      />
      {rejectionDialogOpen && (
        <PacketRejectionDialog
          rejection={review.rejection}
          saving={rejectionSaving}
          error={rejectionError}
          onCancel={() => {
            setRejectionError(null)
            setRejectionDialogOpen(false)
          }}
          onSubmit={rejection => {
            void commitPacketReview(rejectedReview(review, rejection))
          }}
          onUndo={review.rejection
            ? () => { void commitPacketReview(undoRejectedReview(review, fieldKeys)) }
            : undefined}
        />
      )}
    </div>
  )
}
