import { useEffect, useMemo, useState } from 'react'
import type { Bbox } from '../types'
import type { CtvFolder, EvidenceKind } from '../ctv/types'
import { rankFolder } from '../ctv/checks'
import {
  assignCccdCard,
  listCccdCards,
  type PacketReview,
  type FieldFlag,
} from '../upload/api'
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
import CccdCardPicker from './CccdCardPicker'
import PacketGrid from './PacketGrid'
import PacketEvidenceDrawer from './PacketEvidenceDrawer'
import CriteriaMatrix from './CriteriaMatrix'
import PacketDocsDialog from './PacketDocsDialog'

interface Props {
  folder: CtvFolder
  review: PacketReview
  onReview: (review: PacketReview) => void
  onCommitReview: (review: PacketReview) => Promise<void>
  // Present only in the live (server-backed) flow; the offline demo has no
  // case to assign cards against, so the picker stays hidden there.
  caseId?: string | null
  packetIndex?: number | null
  onCardAssigned?: () => void
  /** Leave this packet for the case-level Tổng hợp tab, where the roster-level
   *  criterion is actually checked. Absent in the offline demo. */
  onShowSummary?: () => void
}

const SAVE_ERROR = 'Không lưu được. Vui lòng thử lại.'

// Three ways to look at one packet: the field grid the reviewer already knows,
// Acc's 25 criteria, and the scans themselves. The criteria view needs a live
// case, so it is offered only when there is one.
type ViewMode = 'grid' | 'criteria' | 'documents'

export default function FolderReview({
  folder,
  review,
  onReview,
  onCommitReview,
  caseId = null,
  packetIndex = null,
  onCardAssigned,
  onShowSummary,
}: Props) {
  const ranked = useMemo(() => rankFolder(folder), [folder])
  const [selection, setSelection] = useState<ReviewSelection>(
    overviewSelection,
  )
  const [overviewResetVersion, setOverviewResetVersion] = useState(0)
  const [activeDocId, setActiveDocId] = useState(folder.docs[0]?.id ?? '')
  const [activePage, setActivePage] = useState(0)
  const [focusBbox, setFocusBbox] = useState<Bbox | null>(null)
  const [lockView, setLockView] = useState(false)
  const [rejectionDialogOpen, setRejectionDialogOpen] = useState(false)
  const [rejectionSaving, setRejectionSaving] = useState(false)
  const [rejectionError, setRejectionError] = useState<string | null>(null)
  // '25 tiêu chí' is the default -- it is the checklist the reviewer is
  // actually accountable for, and a cell opens the scan behind it. Falls back
  // to the grid in the offline demo, which has no caseId and so never renders
  // the criteria tab at all. FolderReview is keyed per packet in UploadFlow,
  // so this applies on every packet rather than remembering the last view.
  const [viewMode, setViewMode] = useState<ViewMode>(
    caseId != null && packetIndex != null ? 'criteria' : 'grid',
  )
  const [evidenceDrawerOpen, setEvidenceDrawerOpen] = useState(false)
  const [cardPickerOpen, setCardPickerOpen] = useState(false)
  const [cardBusy, setCardBusy] = useState(false)
  const [cardError, setCardError] = useState<string | null>(null)
  // Which document a cell asked to open. The criteria matrix names a kind and
  // carries the cell's note and value; the Dạng bảng grid names the document
  // outright, since its columns already are the packet's documents.
  const [docPopup, setDocPopup] = useState<{
    docKind?: EvidenceKind
    docId?: string
    context?: { label: string; note?: string; value?: string }
  } | null>(null)

  // The CCCD card the ingest could not place. OCR fails on roughly half of
  // them (the images Excel stores are too small to read digits off), so the
  // reviewer needs a way to say which card is whose.
  const hasCard = folder.docs.some(doc => doc.kind === 'id_front')
  const canAssignCard = caseId !== null && packetIndex !== null

  // The card's id lives server-side, so it is looked up on demand rather than
  // fetched for every packet the reviewer opens.
  const detachCard = async () => {
    if (caseId === null || packetIndex === null) return
    setCardBusy(true)
    setCardError(null)
    try {
      const cards = await listCccdCards(caseId)
      const attached = cards.find(c => c.attachedPacketIndex === packetIndex)
      if (!attached) throw new Error('card-not-found')
      await assignCccdCard(caseId, attached.cardId, null)
      onCardAssigned?.()
    } catch {
      setCardError('Không gỡ được ảnh. Vui lòng thử lại.')
    } finally {
      setCardBusy(false)
    }
  }

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
    setOverviewResetVersion(version => version + 1)
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

  // These hotkeys act on a field selection, which the grid and the document panes
  // both show. The criteria view does not: it has no field list, so ArrowDown
  // there marked an invisible field as seen and `F` flagged one. `viewMode` was
  // in the dependency array but never read in the body, so the listeners stayed
  // live in a view that has nothing for them to act on.
  useEffect(() => {
    if (viewMode === 'criteria') return
    const onKey = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement | null
      const fromOverviewControl = !!el?.closest('.overview-selection-control')
      if (el && (
        (
          ['INPUT', 'TEXTAREA', 'BUTTON', 'SELECT'].includes(el.tagName)
          && !fromOverviewControl
        )
        || el.closest('.packet-rejection-dialog')
      )) return
      if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
        e.preventDefault()
        if (selection.kind === 'overview' && e.key === 'ArrowUp') return
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
  }, [ranked, selection, folder, viewMode])

  // `F` toggles a flag on the currently selected field — separate from the arrow-nav effect
  // above, same input-focus guard, plus skipping modified keystrokes so browser/OS shortcuts
  // (e.g. ⌘F find) pass through untouched.
  useEffect(() => {
    if (viewMode === 'criteria') return
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
  }, [review, selection, viewMode])

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
      <div className="package-view-toggle" role="group" aria-label="Chế độ xem hồ sơ">
        {caseId != null && packetIndex != null && (
          <button
            type="button"
            aria-pressed={viewMode === 'criteria'}
            className={viewMode === 'criteria' ? 'on' : ''}
            onClick={() => { setEvidenceDrawerOpen(false); setViewMode('criteria') }}
          >
            25 tiêu chí
          </button>
        )}
        <button
          type="button"
          aria-pressed={viewMode === 'grid'}
          className={viewMode === 'grid' ? 'on' : ''}
          onClick={() => { setEvidenceDrawerOpen(false); setViewMode('grid') }}
        >
          Dạng bảng
        </button>
        <button
          type="button"
          aria-pressed={viewMode === 'documents'}
          className={viewMode === 'documents' ? 'on' : ''}
          onClick={() => { setEvidenceDrawerOpen(false); setViewMode('documents') }}
        >
          Xem chứng từ
        </button>
      </div>
      {viewMode === 'criteria' && caseId != null && packetIndex != null ? (
        <CriteriaMatrix
          caseId={caseId}
          packetIndex={packetIndex}
          onOpenDocument={(docKind, context) => setDocPopup({ docKind, context })}
          onShowSummary={onShowSummary}
        />
      ) : viewMode === 'grid' ? (
        <PacketGrid
          folder={folder}
          selectedEvidence={evidenceDrawerOpen && selection.kind === 'field'
            ? { fieldKey: selection.key, sourceIndex: selection.sourceIndex }
            : null}
          onOpenDocument={docId => {
            if (caseId != null && packetIndex != null) { setDocPopup({ docId }); return }
            // The offline demo has no case, so there is no manifest endpoint
            // for the dialog to fetch. Show the document in the panes instead
            // of leaving the cell an inert button -- same intent, no autofocus.
            setActiveDocId(docId)
            setActivePage(0)
            setFocusBbox(null)
            setViewMode('documents')
          }}
        />
      ) : (
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
          overviewResetVersion={overviewResetVersion}
          onSelectDoc={onSelectDoc}
          onToggleLock={() => setLockView(v => !v)}
          rosterLabel={selField?.label}
          rosterValue={selField ? formatRosterValue(selField) : null}
        />
      </div>
      )}
      {viewMode === 'grid' && evidenceDrawerOpen && selField && (
        <PacketEvidenceDrawer
          docs={folder.docs}
          activeDocId={activeDocId}
          activePage={activePage}
          focusBbox={focusBbox}
          lockView={lockView}
          overviewResetVersion={overviewResetVersion}
          onSelectDoc={onSelectDoc}
          onToggleLock={() => setLockView(value => !value)}
          onClose={() => setEvidenceDrawerOpen(false)}
          onOpenFull={() => {
            setEvidenceDrawerOpen(false)
            setViewMode('documents')
          }}
          rosterLabel={selField.label}
          rosterValue={formatRosterValue(selField)}
        />
      )}
      {canAssignCard && (
        <div className={`cccd-card-note${hasCard ? ' attached' : ''}`}>
          <span>
            {hasCard
              ? 'Ảnh CCCD lấy từ file Excel'
              : 'Gói này chưa có ảnh CCCD'}
          </span>
          {cardError && (
            <span className="cccd-card-note-error" role="alert">
              {cardError}
            </span>
          )}
          <button
            type="button"
            disabled={cardBusy}
            onClick={() => {
              if (hasCard) void detachCard()
              else setCardPickerOpen(true)
            }}
          >
            {hasCard
              ? (cardBusy ? 'Đang gỡ…' : 'Gỡ ảnh CCCD')
              : 'Gán ảnh CCCD…'}
          </button>
        </div>
      )}
      <ActionBar
        done={review.done}
        seenCount={seenCount}
        total={fieldKeys.length}
        hint="↑↓ chuyển trường · ←→ đổi chứng từ · F đánh dấu · B khung · V giá trị bảng kê · ⌥P di chuyển · ? phím tắt"
        onFinish={() => { if (allSeen(review, fieldKeys)) onReview({ ...review, done: true }) }}
      />
      {cardPickerOpen && canAssignCard && (
        <CccdCardPicker
          caseId={caseId!}
          packetIndex={packetIndex!}
          packetLabel={folder.name}
          onCancel={() => setCardPickerOpen(false)}
          onAssigned={() => {
            setCardPickerOpen(false)
            onCardAssigned?.()
          }}
        />
      )}
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
      {docPopup && caseId != null && packetIndex != null && (
        /* No `onOpenPacket`: the reviewer is already inside this packet, so a
           button offering to open it would go nowhere. */
        <PacketDocsDialog
          caseId={caseId}
          packetIndex={packetIndex}
          packetName={folder.name}
          initialDocId={docPopup.docId}
          initialDocKind={docPopup.docKind}
          context={docPopup.context}
          onClose={() => setDocPopup(null)}
        />
      )}
    </div>
  )
}
