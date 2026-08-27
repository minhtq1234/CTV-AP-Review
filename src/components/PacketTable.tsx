import { useMemo, useState } from 'react'
import type { PacketMeta } from '../upload/api'
import {
  NO_FILTERS,
  filterRows,
  isFiltering,
  packetRows,
  visibleCounters,
  type PacketTableFilters,
} from '../logic/packetTable'
import { attentionReasons, packetStatusSummary } from '../logic/packetDashboard'

interface Props {
  packets: PacketMeta[]
  onOpenPacket: (index: number) => void
}

/**
 * The packet list as a table (ver 2 §2.2).
 *
 * Column widths: the NAME column is the flexible one and every status column is
 * fixed. That ordering is deliberate — the design mock did the opposite, giving
 * fixed widths to five status columns and leaving the name unspecified under
 * `table-layout: fixed`, so below ~500px of container the name collapsed to 0px
 * and the primary identifying column disappeared while the pills survived. A
 * name is what a reviewer scans; it should be the last thing to lose space, not
 * the first.
 *
 * Filters here cover only the axes the lifecycle chips above do not: the chips
 * already are the "Kết quả FA" filter, so repeating it would give two controls
 * for one axis.
 */
export default function PacketTable({ packets, onOpenPacket }: Props) {
  const [filters, setFilters] = useState<PacketTableFilters>(NO_FILTERS)
  const rows = useMemo(() => packetRows(packets), [packets])
  const counters = useMemo(() => visibleCounters(rows), [rows])
  const visible = useMemo(() => filterRows(rows, filters), [rows, filters])
  const set = (patch: Partial<PacketTableFilters>) =>
    setFilters(current => ({ ...current, ...patch }))
  // Whether any packet carries the field at all — a column of dashes is noise,
  // and an older ingest has none of these.
  const hasCommitmentData = rows.some(row => row.hasCommitment !== null)
  const hasDocumentData = rows.some(row => row.documents !== null)

  return (
    <>
      {counters.length > 0 && (
        <div className="packet-table-counters" aria-label="Kết quả đối chiếu theo trạng thái">
          {counters.map(counter => {
            const active = filters.ai === counter.status
            return (
              <button
                key={counter.status}
                type="button"
                className={`packet-table-counter ${counter.tone}${active ? ' active' : ''}`}
                aria-pressed={active}
                onClick={() => set({ ai: active ? '' : counter.status })}
              >
                <b>{counter.count}</b>
                <span>{counter.label}</span>
              </button>
            )
          })}
        </div>
      )}

      <div className="packet-table-filters">
        <input
          type="search"
          className="packet-table-search"
          placeholder="Tìm theo tên…"
          value={filters.q}
          aria-label="Tìm gói hồ sơ theo tên"
          onChange={event => set({ q: event.target.value })}
        />
        {hasDocumentData && (
          <select
            aria-label="Lọc theo chứng từ"
            value={filters.documents}
            onChange={event => set({ documents: event.target.value as PacketTableFilters['documents'] })}
          >
            <option value="">Chứng từ: tất cả</option>
            <option value="complete">Đầy đủ</option>
            <option value="missing">Thiếu chứng từ</option>
          </select>
        )}
        {hasCommitmentData && (
          <select
            aria-label="Lọc theo cam kết thuế"
            value={filters.commitment}
            onChange={event => set({ commitment: event.target.value as PacketTableFilters['commitment'] })}
          >
            <option value="">Cam kết thuế: tất cả</option>
            <option value="yes">Có cam kết</option>
            <option value="no">Không cam kết</option>
          </select>
        )}
        {isFiltering(filters) && (
          <button type="button" className="btn" onClick={() => setFilters(NO_FILTERS)}>
            Xoá lọc
          </button>
        )}
        <span className="packet-table-showing">
          {visible.length === rows.length
            ? `${rows.length} gói`
            : `${visible.length} / ${rows.length} gói`}
        </span>
      </div>

      {visible.length === 0 ? (
        <div className="packet-grid-empty">Không có gói hồ sơ nào khớp bộ lọc.</div>
      ) : (
        <div className="packet-table-wrap">
          <table className="packet-table">
            <thead>
              <tr>
                <th className="pt-stt">STT</th>
                <th className="pt-name">Họ và tên</th>
                {hasCommitmentData && <th className="pt-camket">Cam kết thuế</th>}
                {hasDocumentData && <th className="pt-docs">Chứng từ</th>}
                <th className="pt-ai">Kết quả AI</th>
                <th className="pt-fa">Kết quả FA</th>
                <th className="pt-pages">Phạm vi trang</th>
              </tr>
            </thead>
            <tbody>
              {visible.map(row => {
                const packet = packets.find(p => p.index === row.index)
                const attention = packet ? attentionReasons(packet) : []
                const detail = packet ? packetStatusSummary(packet, row.fa) : null
                return (
                  <tr
                    key={row.index}
                    className="packet-table-row"
                    tabIndex={0}
                    role="button"
                    aria-label={`Gói ${row.stt} · ${row.name}`}
                    onClick={() => onOpenPacket(row.index)}
                    onKeyDown={event => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onOpenPacket(row.index)
                      }
                    }}
                  >
                    <td className="pt-stt">{row.stt}</td>
                    <td className="pt-name">
                      <span className="pt-name-text">{row.name}</span>
                      {attention.length > 0 && (
                        <span className="pt-attention" title={attention.join(' · ')}>
                          {attention.length > 1
                            ? `${attention[0]} +${attention.length - 1}`
                            : attention[0]}
                        </span>
                      )}
                    </td>
                    {hasCommitmentData && (
                      <td className="pt-camket">
                        <span className="pt-pill muted">
                          {row.hasCommitment === null ? '—' : row.hasCommitment ? 'Có' : 'Không'}
                        </span>
                      </td>
                    )}
                    {hasDocumentData && (
                      <td className="pt-docs">
                        {row.documentsLabel ? (
                          <>
                            <span
                              className={`pt-pill ${row.documentsComplete ? 'good' : 'bad'}`}
                            >
                              {row.documentsLabel}
                            </span>
                            {row.documents && row.documents.missing.length > 0 && (
                              <span className="pt-missing">
                                Thiếu: {row.documents.missing.join(', ')}
                              </span>
                            )}
                          </>
                        ) : (
                          <span className="pt-pill muted">—</span>
                        )}
                      </td>
                    )}
                    <td className="pt-ai">
                      <span className={`pt-pill ${row.aiTone}`}>{row.aiLabel}</span>
                    </td>
                    <td className="pt-fa">
                      <span className={`pt-pill fa-${row.fa}`}>{row.faLabel}</span>
                      {detail && <span className="pt-sub">{detail}</span>}
                    </td>
                    <td className="pt-pages">
                      p{row.pages[0] + 1}–{row.pages[1] + 1}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
