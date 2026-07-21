import type { Verdict } from '../types'
import type { EvidenceDoc } from '../ctv/types'
import type { FieldVerdict, RankedCtv } from '../ctv/checks'
import { counts } from '../ctv/checks'

interface Props {
  ranked: RankedCtv[]
  docs: EvidenceDoc[]
  selectedKey: string
  onSelect: (key: string) => void
  onFocusSource: (fieldKey: string, sourceIdx: number) => void
}

// Field-level chip: the 4 hint verdicts, plus the neutral "review" state (#004) -- a field
// with no readable source at all is "cần xem", never rendered as a red exception.
const FIELD_CHIP: Record<FieldVerdict, { cls: string; glyph: string }> = {
  mismatch: { cls: 'v-mismatch', glyph: '✗' },
  low_conf: { cls: 'v-low', glyph: '!' },
  fuzzy: { cls: 'v-fuzzy', glyph: '~' },
  match: { cls: 'v-match', glyph: '✓' },
  review: { cls: 'v-review', glyph: 'cần xem' },
}

// Source-level chip: only for READABLE sources -- an 'unread' source never looks this up
// (rendered separately below as a neutral "cần xem · <doc>" chip, no verdict glyph).
const SRC_CHIP: Record<Verdict, { cls: string; glyph: string }> = {
  mismatch: { cls: 'v-mismatch', glyph: '✗' },
  low_conf: { cls: 'v-low', glyph: '!' },
  fuzzy: { cls: 'v-fuzzy', glyph: '~' },
  match: { cls: 'v-match', glyph: '✓' },
}

export default function FolderFieldsPanel({ ranked, docs, selectedKey, onSelect, onFocusSource }: Props) {
  const c = counts(ranked)
  const label = (id: string) => docs.find(d => d.id === id)?.label ?? id
  return (
    <aside className="fields-pane">
      <div className="fields-summary">
        <span>{ranked.length} mục kiểm tra</span>
        {c.mismatch > 0 && <span className="s-mismatch">● {c.mismatch} lệch</span>}
        {c.review > 0 && <span className="s-review">● {c.review} cần xem</span>}
        {c.low_conf > 0 && <span className="s-low">● {c.low_conf} tin cậy thấp</span>}
      </div>
      {ranked.map(r => {
        const chip = FIELD_CHIP[r.verdict]
        const sel = r.field.key === selectedKey
        return (
          <div key={r.field.key} className={`cfield ${sel ? 'sel' : ''}`} onClick={() => onSelect(r.field.key)}>
            <div className="cfield-head">
              <span className={`chip ${chip.cls}`}>{chip.glyph}</span>
              <span className="flabel">{r.field.label}</span>
              <span className="ftag">{r.field.group}</span>
            </div>
            <div className="cfield-exp">Kê khai (Excel): <b>{r.field.expected}</b></div>
            {r.sources.length > 0 && (
              <div className="cfield-src">
                <span className="cfield-src-lbl">Đối chiếu:</span>
                {r.sources.map((sr, i) => {
                  // Located but unreadable (handwritten/illegible) -- still a navigable chip
                  // pointing at the region, but neutral: it never renders as an exception.
                  if (sr.verdict === 'unread') {
                    return (
                      <button key={i} className="srcchip unread" title="Chưa đọc được — cần kiểm tra bằng mắt"
                        onClick={e => { e.stopPropagation(); onFocusSource(r.field.key, i) }}>
                        cần xem · {label(sr.source.docId)}
                      </button>
                    )
                  }
                  const sc = SRC_CHIP[sr.verdict]
                  return (
                    <button key={i} className={`srcchip ${sc.cls}`} title={sr.source.value}
                      onClick={e => { e.stopPropagation(); onFocusSource(r.field.key, i) }}>
                      <span className="srcchip-g">{sc.glyph}</span> {label(sr.source.docId)}
                      {sr.verdict === 'mismatch' && <span className="srcbad">: {sr.source.value}</span>}
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        )
      })}
    </aside>
  )
}
