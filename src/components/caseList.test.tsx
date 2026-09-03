// @vitest-environment jsdom

import { act } from 'react'
import { createRoot, type Root } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CaseSummary } from '../upload/api'
import CaseList from './CaseList'

let root: Root
let container: HTMLDivElement

beforeEach(() => {
  vi.stubGlobal('IS_REACT_ACT_ENVIRONMENT', true)
  container = document.createElement('div')
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.unstubAllGlobals()
})

function summary(overrides: Partial<CaseSummary> = {}): CaseSummary {
  return {
    id: 'case-1',
    name: 'demo.pdf',
    createdAt: '2026-01-01T00:00:00+00:00',
    status: 'ready',
    pdfName: 'demo.pdf',
    progress: { done: 0, total: 3, flagged: 0, candidates: 0 },
    ...overrides,
  } as CaseSummary
}

function render(cases: CaseSummary[]) {
  const opened: string[] = []
  const deleted: string[] = []
  act(() => {
    root.render(
      <CaseList
        cases={cases}
        live={{}}
        onOpen={id => opened.push(id)}
        onNew={() => undefined}
        onDelete={id => deleted.push(id)}
      />,
    )
  })
  return { opened, deleted }
}

const row = () => container.querySelector<HTMLElement>('.case-row')!

describe('a case row is a real control', () => {
  it('announces itself as a button naming the case and its status', () => {
    render([summary()])

    expect(row().getAttribute('role')).toBe('button')
    expect(row().getAttribute('aria-label')).toContain('demo.pdf')
  })

  it('can be reached by keyboard and opened with Enter', () => {
    // It was a plain div with onClick: mouse-only, and invisible to a screen
    // reader as something you could act on.
    const { opened } = render([summary()])

    expect(row().tabIndex).toBe(0)
    act(() => {
      row().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    })

    expect(opened).toEqual(['case-1'])
  })

  it('opens with Space as well, and does not scroll the page doing it', () => {
    const { opened } = render([summary()])
    const event = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true })

    act(() => { row().dispatchEvent(event) })

    expect(opened).toEqual(['case-1'])
    expect(event.defaultPrevented).toBe(true)
  })

  it('deleting with the keyboard does not also open the case', () => {
    // The delete button sits inside the row, so its keypress bubbles to the
    // row's handler. Without a guard, Enter on delete would do both.
    const { opened } = render([summary()])
    const remove = container.querySelector<HTMLButtonElement>('.case-row-delete')!

    act(() => {
      remove.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    })

    expect(opened).toEqual([])
  })

  it('a still-processing case is out of the tab order and announced disabled', () => {
    // There is nothing to review yet, so it must not be focusable-and-inert.
    const { opened } = render([summary({ status: 'processing' })])

    expect(row().tabIndex).toBe(-1)
    expect(row().getAttribute('aria-disabled')).toBe('true')
    act(() => {
      row().dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true }))
    })
    expect(opened).toEqual([])
  })
})
