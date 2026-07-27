import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, test, vi } from 'vitest'
import PacketRejectionDialog from './PacketRejectionDialog'

const renderDialog = (
  rejection: {
    reasons: ('missing_documents' | 'wrong_template' | 'missing_signature')[]
    note: string
  } | null,
  saving = false,
  error: string | null = null,
) => renderToStaticMarkup(
  <PacketRejectionDialog
    rejection={rejection}
    saving={saving}
    error={error}
    onCancel={vi.fn()}
    onSubmit={vi.fn()}
    onUndo={rejection ? vi.fn() : undefined}
  />,
)

describe('PacketRejectionDialog contract', () => {
  test('create mode renders all reasons and approved actions', () => {
    const html = renderDialog(null)
    expect(html).toContain('Từ chối gói hồ sơ')
    expect(html).toContain('Thiếu chứng từ')
    expect(html).toContain('Chứng từ không đúng mẫu')
    expect(html).toContain('Thiếu chữ ký')
    expect(html).toContain('Ghi chú')
    expect(html).toContain('Hủy')
    expect(html).toContain('Xác nhận từ chối')
    expect(html).not.toContain('Hoàn tác từ chối')
  })

  test('edit mode seeds reasons/note and exposes edit plus undo actions', () => {
    const html = renderDialog({
      reasons: ['missing_documents', 'missing_signature'],
      note: 'Bổ sung',
    })
    expect(html).toContain('Sửa lý do từ chối')
    expect(html).toContain('Lưu thay đổi')
    expect(html).toContain('Hoàn tác từ chối')
    expect(html).toContain('>Bổ sung</textarea>')
    expect((html.match(/checked=""/g) ?? [])).toHaveLength(2)
  })

  test('saving disables dismiss and mutation actions', () => {
    const html = renderDialog(null, true)
    expect(html).toContain('Đang lưu…')
    expect((html.match(/disabled=""/g) ?? []).length).toBeGreaterThanOrEqual(4)
  })

  test('shows a retryable inline save error', () => {
    const html = renderDialog(
      { reasons: ['wrong_template'], note: '' },
      false,
      'Không lưu được. Vui lòng thử lại.',
    )
    expect(html).toContain('Không lưu được. Vui lòng thử lại.')
    expect(html).toContain('role="alert"')
  })
})
