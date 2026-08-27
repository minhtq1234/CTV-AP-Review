import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { CriterionRow } from '../upload/api'
import { MatrixRow } from './CriteriaMatrix'

function row(overrides: Partial<CriterionRow> = {}): CriterionRow {
  return {
    stt: 21,
    code: '21',
    label: 'Hợp đồng có chữ ký CTV',
    group: '05',
    groupLabel: 'Chứng từ và ký dấu',
    kind: 'presence',
    render: 'matrix',
    how: 'Kiểm tra có chữ ký của đúng CTV tại vị trí dành cho bên cung cấp dịch vụ.',
    status: 'rv',
    note: '',
    cells: [{
      document: 'Hợp đồng', status: 'rv', computedStatus: 'rv',
      value: '', note: 'Cần người kiểm tra chữ ký.', evidence: [],
    }],
    ...overrides,
  }
}

const render = (r: CriterionRow, open = false) => renderToStaticMarkup(
  <table><tbody>
    <MatrixRow row={r} columns={['Hợp đồng']} open={open}
               onToggle={() => undefined} onDecide={() => undefined} />
  </tbody></table>,
)

describe('a criteria cell is a control', () => {
  it('the mark is a button a reviewer can press', () => {
    const html = render(row())
    expect(html).toContain('criteria-mark')
    expect(html).toContain('type="button"')
  })

  it('the button says what it opens', () => {
    const html = render(row())
    expect(html).toContain('aria-expanded="false"')
  })

  it('a cell outside the criterion is not a control', () => {
    const html = renderToStaticMarkup(
      <table><tbody>
        <MatrixRow row={row()} columns={['Hợp đồng', 'BBNT']} open={false}
                   onToggle={() => undefined} onDecide={() => undefined} />
      </tbody></table>,
    )
    expect(html).toContain('out-of-scope')
  })
})

describe('the decision picker', () => {
  it('is hidden until the row is opened', () => {
    expect(render(row(), false)).not.toContain('criteria-decide')
  })

  it('offers every status except the one the cell already has', () => {
    const html = render(row(), true)
    for (const label of ['Đạt', 'Không khớp', 'Thiếu chứng từ',
                         'Chưa kiểm tra được']) {
      expect(html).toContain(label)
    }
  })

  it('does not offer a second confirmation step', () => {
    // Acc: one click. No dialog, no reason field.
    const html = render(row(), true)
    expect(html).not.toContain('textarea')
    expect(html.toLowerCase()).not.toContain('xác nhận lại')
  })

  it('shows no picker for a cell marked na', () => {
    const na = row({
      cells: [{ document: 'Hợp đồng', status: 'na', computedStatus: 'na',
                value: '', note: 'Không áp dụng.', evidence: [] }],
    })
    expect(render(na, true)).not.toContain('criteria-decide')
  })
})

describe('a decided cell says so', () => {
  const decided = row({
    status: 'ok',
    cells: [{
      document: 'Hợp đồng', status: 'ok', computedStatus: 'rv', value: '',
      note: 'Cần người kiểm tra chữ ký. Người kiểm tra đổi thành "Đạt".',
      evidence: [{ documentId: 'override', page: 0, bbox: null, value: '',
                   confidence: null, provenance: 'override' }],
    }],
  })

  it('marks the cell as carrying a decision', () => {
    expect(render(decided)).toContain('decided')
  })

  it('names what the engine computed, so the change is visible', () => {
    const html = render(decided, true)
    expect(html).toContain('Cần người kiểm tra')
  })

  it('an untouched cell is not marked', () => {
    expect(render(row())).not.toContain('criteria-mark decided')
  })
})
