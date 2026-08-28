// src/components/CriteriaMatrix.interaction.test.tsx
// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CriterionCell, CriterionRow } from '../upload/api'
import type { EvidenceKind } from '../ctv/types'
import { MatrixRow } from './CriteriaMatrix'

function cell(overrides: Partial<CriterionCell> = {}): CriterionCell {
  return {
    document: 'Hợp đồng', status: 'no', computedStatus: 'no',
    value: '8.000.000', note: 'Thiếu chữ ký CTV.', evidence: [],
    ...overrides,
  }
}

function row(overrides: Partial<CriterionRow> = {}): CriterionRow {
  return {
    stt: 21,
    code: '21',
    label: 'Hợp đồng có chữ ký CTV',
    group: '05',
    groupLabel: 'Chứng từ và ký dấu',
    kind: 'presence',
    render: 'matrix',
    how: 'Kiểm tra có chữ ký của đúng CTV.',
    status: 'no',
    note: '',
    cells: [cell()],
    ...overrides,
  }
}

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  host = document.createElement('div')
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
  vi.unstubAllGlobals()
})

interface Opened { docKind: EvidenceKind; label: string; note?: string; value?: string }

function mount(r: CriterionRow, columns: string[]) {
  const opened: Opened[] = []
  const summaries: number[] = []
  act(() => {
    root.render(
      <table><tbody>
        <MatrixRow
          row={r}
          columns={columns}
          open={false}
          onToggle={() => undefined}
          onDecide={() => undefined}
          onOpenDocument={(docKind, context) => opened.push({ docKind, ...context })}
          onShowSummary={() => summaries.push(1)}
        />
      </tbody></table>,
    )
  })
  return { opened, summaries }
}

function clickMark(column: string) {
  const marks = [...host.querySelectorAll('button.criteria-mark')]
  const found = marks.find(m => (m.getAttribute('aria-label') ?? '').includes(column))
  if (!found) throw new Error(`no cell mark for ${column}: ${host.innerHTML}`)
  act(() => { (found as HTMLButtonElement).click() })
}

describe('clicking a matrix cell', () => {
  it('asks to open the document for the column the cell sits in', () => {
    const { opened } = mount(row(), ['Hợp đồng'])
    clickMark('Hợp đồng')
    expect(opened).toHaveLength(1)
    expect(opened[0].docKind).toBe('contract')
    // The note and value travel with it: the detail row used to be where the
    // reviewer read these before deciding.
    expect(opened[0].label).toContain('Hợp đồng')
    expect(opened[0].note).toBe('Thiếu chữ ký CTV.')
    expect(opened[0].value).toBe('8.000.000')
  })

  it('maps the MST lookup column to the pit document, not an mst one', () => {
    const r = row({ cells: [cell({ document: 'Website tra cứu MST' })] })
    const { opened } = mount(r, ['Website tra cứu MST'])
    clickMark('Website tra cứu MST')
    expect(opened[0].docKind).toBe('pit')
  })

  it('does nothing when the Excel cell is clicked', () => {
    const r = row({ cells: [cell({ document: 'Excel' })] })
    const { opened, summaries } = mount(r, ['Excel'])
    clickMark('Excel')
    expect(opened).toHaveLength(0)
    expect(summaries).toHaveLength(0)
  })

  it('asks for the summary tab when the roster-level cell is clicked', () => {
    const r = row({ cells: [cell({ document: 'Bảng Kê Thu Mua' })] })
    const { opened, summaries } = mount(r, ['Bảng Kê Thu Mua'])
    clickMark('Bảng Kê Thu Mua')
    expect(summaries).toHaveLength(1)
    expect(opened).toHaveLength(0)
  })

  it('opens nothing for a cell the criterion does not apply to', () => {
    const r = row({ cells: [cell({ document: 'Hợp đồng', status: 'na' })] })
    const { opened } = mount(r, ['Hợp đồng'])
    clickMark('Hợp đồng')
    expect(opened).toHaveLength(0)
  })
})
