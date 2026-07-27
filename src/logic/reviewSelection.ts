export type ReviewSelection =
  | { kind: 'overview' }
  | { kind: 'field'; key: string; sourceIndex: number }

export function overviewSelection(): ReviewSelection {
  return { kind: 'overview' }
}

export function fieldSelection(
  key: string,
  sourceIndex = 0,
): ReviewSelection {
  return { kind: 'field', key, sourceIndex }
}

export function selectedFieldKey(
  selection: ReviewSelection,
): string | null {
  return selection.kind === 'field' ? selection.key : null
}

export function moveVerticalSelection(
  selection: ReviewSelection,
  fieldKeys: string[],
  direction: 'up' | 'down',
): ReviewSelection {
  if (fieldKeys.length === 0) return overviewSelection()

  if (selection.kind === 'overview') {
    return direction === 'down'
      ? fieldSelection(fieldKeys[0])
      : overviewSelection()
  }

  const currentIndex = fieldKeys.indexOf(selection.key)
  if (currentIndex <= 0 && direction === 'up') return overviewSelection()
  if (currentIndex < 0) return overviewSelection()

  const nextIndex = direction === 'down'
    ? Math.min(currentIndex + 1, fieldKeys.length - 1)
    : Math.max(currentIndex - 1, 0)

  return fieldSelection(fieldKeys[nextIndex])
}
