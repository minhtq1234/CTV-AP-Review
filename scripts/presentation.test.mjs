import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'

const deckPath = new URL(
  '../docs/presentations/ctv-ap-review-overview.html',
  import.meta.url,
)

const readDeck = () => readFileSync(deckPath, 'utf8')

test('contains exactly five slides and the approved story', () => {
  const html = readDeck()
  assert.equal((html.match(/class="slide(?:\s[^"]*)?"/g) ?? []).length, 5)
  for (const requiredText of [
    'AP Lens — Soát hồ sơ CTV thông minh',
    'Tải lên một lần, hệ thống chuẩn bị phần còn lại',
    'Một dashboard cho toàn bộ đợt hồ sơ',
    'Xem tổng quan, rồi kiểm tra từng trường',
    'Tập trung vào ngoại lệ, xuất kết quả rõ ràng',
    'Chưa xem',
    'Đang xem',
    'Đã xong',
    'Flagged',
    'Cần chú ý trước',
    'Tổng quan',
    'Từ chối hồ sơ',
    'Xuất báo cáo',
  ]) {
    assert.match(html, new RegExp(requiredText))
  }
})

test('is offline, dependency-free, and PII-safe by construction', () => {
  const html = readDeck()
  assert.doesNotMatch(html, /(?:src|href)=["']https?:\/\//i)
  assert.doesNotMatch(html, /<script[^>]+src=/i)
  assert.doesNotMatch(html, /<link[^>]+rel=["']stylesheet/i)
  assert.doesNotMatch(html, /\b\d{12}\b/)
  // Any Vietnamese personal name: every syllable capitalised, two or more of
  // them. This used to list three real contractors by hand, which caught a leak
  // of exactly those three and put their names in a public repo to do it. The
  // deck is illustrative and carries no per-person data, so one match here means
  // real roster content reached the slides.
  assert.doesNotMatch(html, /\p{Lu}\p{Ll}+(?:\s+\p{Lu}\p{Ll}+)+/u)
})

test('includes accessible navigation, fullscreen, keyboard, and touch controls', () => {
  const html = readDeck()
  assert.match(html, /aria-label="Trang trước"/)
  assert.match(html, /aria-label="Trang tiếp theo"/)
  assert.match(html, /aria-label="Toàn màn hình"/)
  assert.match(html, /requestFullscreen/)
  assert.match(html, /ArrowLeft/)
  assert.match(html, /ArrowRight/)
  assert.match(html, /PageUp/)
  assert.match(html, /PageDown/)
  assert.match(html, /touchstart/)
  assert.match(html, /prefers-reduced-motion/)
})
