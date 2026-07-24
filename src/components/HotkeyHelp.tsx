interface HotkeyHelpProps { open: boolean; onClose: () => void }

// U5: the full hotkey reference — `?` opens/closes this from EvidenceViewer. Kept as a plain
// list (not a table) so it reads fine at the panel's compact width.
const ROWS: { keys: string; desc: string }[] = [
  { keys: '↑ / ↓', desc: 'Chuyển mục kiểm tra' },
  { keys: '← / →', desc: 'Chuyển trang (sang tài liệu kế khi hết trang)' },
  { keys: 'Alt + / Alt −', desc: 'Phóng to / thu nhỏ' },
  { keys: 'B', desc: 'Ẩn / hiện khung tô sáng' },
  { keys: 'F', desc: 'Đánh dấu mục cần gửi lại' },
  { keys: 'V', desc: 'Ẩn/hiện giá trị bảng kê trên chứng từ' },
  { keys: 'Option/Alt + P', desc: 'Bật/tắt di chuyển (pan) — kéo để di chuyển tài liệu' },
  { keys: '🔒', desc: 'Khoá khung nhìn (giữ nguyên khi đổi mục/chứng từ)' },
  { keys: '?', desc: 'Hiện / ẩn danh sách phím tắt này' },
  { keys: 'Thanh chế độ xem', desc: '1 trang · Cuộn liên tục · 2 trang (trên thanh công cụ)' },
]

export default function HotkeyHelp({ open, onClose }: HotkeyHelpProps) {
  if (!open) return null
  return (
    <div className="help-backdrop" onClick={onClose}>
      <div className="help-panel" onClick={e => e.stopPropagation()}>
        <div className="help-head">
          <strong>Phím tắt</strong>
          <button className="help-close" onClick={onClose} aria-label="Đóng">✕</button>
        </div>
        <div className="help-list">
          {ROWS.map(r => (
            <div key={r.keys} className="help-row">
              <span className="help-keys">{r.keys}</span>
              <span className="help-desc">{r.desc}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
