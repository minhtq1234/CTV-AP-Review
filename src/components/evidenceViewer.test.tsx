import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import type { EvidenceDoc } from '../ctv/types'
import EvidenceViewer from './EvidenceViewer'

const docs: EvidenceDoc[] = [{
  id: 'doc',
  kind: 'contract',
  label: 'Synthetic document',
  pages: [
    { src: '/synthetic-1.svg', width: 1000, height: 1400 },
    { src: '/synthetic-2.svg', width: 1000, height: 1400 },
    { src: '/synthetic-3.svg', width: 1000, height: 1400 },
  ],
}]

describe('complete-document evidence viewer', () => {
  it('renders both approved modes and every active-document page', () => {
    const html = renderToStaticMarkup(
      <EvidenceViewer
        docs={docs}
        activeDocId="doc"
        activePage={1}
        focusBbox={{ x: 100, y: 200, width: 300, height: 40 }}
        lockView={false}
        onSelectDoc={() => undefined}
        onToggleLock={() => undefined}
        rosterLabel="Synthetic field"
        rosterValue="Synthetic value"
      />,
    )
    expect(html).toContain('1 trang')
    expect(html).toContain('2 trang')
    expect(html.match(/data-page-index=/g)).toHaveLength(3)
    expect(html).toContain('100%')
  })

  it('reserves natural page geometry before backend images finish loading', () => {
    const html = renderToStaticMarkup(
      <EvidenceViewer
        docs={docs}
        activeDocId="doc"
        activePage={2}
        focusBbox={{ x: 100, y: 200, width: 300, height: 40 }}
        lockView={false}
        onSelectDoc={() => undefined}
        onToggleLock={() => undefined}
      />,
    )
    expect(html.match(/width="1000" height="1400"/g)).toHaveLength(3)
  })

  it('keeps every existing v1 tool visible', () => {
    const html = renderToStaticMarkup(
      <EvidenceViewer
        docs={docs}
        activeDocId="doc"
        activePage={0}
        focusBbox={null}
        lockView={false}
        onSelectDoc={() => undefined}
        onToggleLock={() => undefined}
      />,
    )
    for (const label of [
      'Vừa khung',
      'Thu nhỏ',
      'Phóng to',
      'Ẩn/hiện khung tô sáng',
      'Ẩn/hiện giá trị bảng kê',
      'Di chuyển (pan)',
      'Khoá khung nhìn',
      'Danh sách phím tắt',
    ]) {
      expect(html).toContain(`aria-label="${label}"`)
    }
  })
})
