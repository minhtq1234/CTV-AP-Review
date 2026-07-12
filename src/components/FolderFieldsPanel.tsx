import type { Verdict } from '../types'
import type { RankedCtv } from '../ctv/checks'
import { counts } from '../ctv/checks'

interface Props { ranked: RankedCtv[]; selectedKey: string; onSelect: (key: string) => void }

const CHIP: Record<Verdict, { cls: string; glyph: string }> = {
  mismatch: { cls: 'v-mismatch', glyph: '✗' },
  low_conf: { cls: 'v-low', glyph: '!' },
  fuzzy: { cls: 'v-fuzzy', glyph: '~' },
  match: { cls: 'v-match', glyph: '✓' },
}

export default function FolderFieldsPanel({ ranked, selectedKey, onSelect }: Props) {
  const c = counts(ranked)
  return (
    <aside className="fields-pane">
      <div className="fields-summary">
        <span>{ranked.length} mục kiểm tra</span>
        {c.mismatch > 0 && <span className="s-mismatch">● {c.mismatch} lệch</span>}
        {c.low_conf > 0 && <span className="s-low">● {c.low_conf} tin cậy thấp</span>}
      </div>
      {ranked.map(r => {
        const chip = CHIP[r.verdict]
        const conf = r.field.extract ? Math.round(r.field.extract.confidence * 100) : null
        return (
          <div key={r.field.key} className={`frow ${r.field.key === selectedKey ? 'sel' : ''}`}
            onClick={() => onSelect(r.field.key)}>
            <span className={`chip ${chip.cls}`}>{chip.glyph}</span>
            <span className="fbody">
              <span className="flabel">{r.field.label} <span className="ftag">{r.field.group}</span></span>
              <span className="fvals">
                {r.field.expected} → <span className={r.verdict === 'mismatch' ? 'act bad' : 'act'}>{r.actual}</span>
              </span>
            </span>
            {conf !== null && <span className={`conf ${r.verdict === 'low_conf' ? 'low' : ''}`}>{conf}%</span>}
          </div>
        )
      })}
    </aside>
  )
}
