import type { Bbox, Verdict } from '../types'
import type { EvidenceDoc } from '../ctv/types'
import type { RankedCtv } from '../ctv/checks'
import { counts } from '../ctv/checks'

interface Props {
  ranked: RankedCtv[]
  docs: EvidenceDoc[]
  selectedKey: string
  onSelect: (key: string) => void
  onFocusSource: (docId: string, page: number, bbox: Bbox) => void
}

const CHIP: Record<Verdict, { cls: string; glyph: string }> = {
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
        {c.low_conf > 0 && <span className="s-low">● {c.low_conf} tin cậy thấp</span>}
      </div>
      {ranked.map(r => {
        const chip = CHIP[r.verdict]
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
                  const sc = CHIP[sr.verdict]
                  return (
                    <button key={i} className={`srcchip ${sc.cls}`} title={sr.source.value}
                      onClick={e => { e.stopPropagation(); onFocusSource(sr.source.docId, sr.source.page, sr.source.bbox) }}>
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
