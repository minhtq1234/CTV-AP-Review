import { createElement } from 'react'
import { renderToStaticMarkup } from 'react-dom/server'
import { expect, test } from 'vitest'
import UploadScreen from './UploadScreen'

test('renders the optional xlsx CCCD chooser and high-resolution guidance', () => {
  const html = renderToStaticMarkup(createElement(UploadScreen, {
    busy: false,
    onStart: () => undefined,
  }))

  expect(html).toContain('Chọn file ảnh CCCD Excel (tuỳ chọn)')
  expect(html).toContain('Nên dùng ảnh gốc hoặc ảnh độ phân giải cao')
  expect((html.match(/accept="\.xlsx"/g) ?? []).length).toBe(2)
})
