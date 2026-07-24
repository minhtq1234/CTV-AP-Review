// Pure page/document navigation helpers for the scan pane. Kept out of the
// React components so the index math (clamping, rolling into adjacent docs)
// is unit-tested (the components themselves carry no tests).

import type { EvidenceDoc } from '../ctv/types'

/** Clamp a page index into a doc's real range; 0 when the doc has no pages. */
export function clampPage(page: number, pageCount: number): number {
  if (pageCount <= 0) return 0
  return Math.max(0, Math.min(page, pageCount - 1))
}

/**
 * Step one page in `dir` (+1 / -1) within `docs`, rolling into the adjacent
 * document at the first/last page. Clamped at the very ends (first page of the
 * first doc / last page of the last doc). Returns the resulting {docId, page}.
 */
export function stepPage(
  docs: EvidenceDoc[], activeDocId: string, activePage: number, dir: 1 | -1,
): { docId: string; page: number } {
  const di = Math.max(0, docs.findIndex(d => d.id === activeDocId))
  const doc = docs[di]
  const last = doc.pages.length - 1
  const p = clampPage(activePage, doc.pages.length)
  if (dir === 1) {
    if (p < last) return { docId: doc.id, page: p + 1 }
    if (di < docs.length - 1) return { docId: docs[di + 1].id, page: 0 }
    return { docId: doc.id, page: Math.max(0, last) }   // at the very end
  } else {
    if (p > 0) return { docId: doc.id, page: p - 1 }
    if (di > 0) {
      const prev = docs[di - 1]
      return { docId: prev.id, page: Math.max(0, prev.pages.length - 1) }
    }
    return { docId: doc.id, page: 0 }                   // at the very start
  }
}

/** Step to the adjacent document id (clamped at the ends). */
export function stepDoc(docs: EvidenceDoc[], activeDocId: string, dir: 1 | -1): string {
  const i = Math.max(0, docs.findIndex(d => d.id === activeDocId))
  return docs[Math.max(0, Math.min(i + dir, docs.length - 1))].id
}
