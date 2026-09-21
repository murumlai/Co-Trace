export function buildEvidenceView(text, query, contextLines = 2) {
  const allLines = text ? String(text).split(/\r?\n/) : []
  const normalized = String(query || '').toLocaleLowerCase()
  const matchIndexes = normalized
    ? allLines.flatMap((line, index) => line.toLocaleLowerCase().includes(normalized) ? [index] : [])
    : []

  if (!normalized) {
    return {
      allLineCount: allLines.length,
      matchIndexes,
      lines: allLines.map((line, index) => ({ line, n: index + 1, isMatch: false })),
    }
  }

  const visible = new Set()
  matchIndexes.forEach((index) => {
    const first = Math.max(0, index - contextLines)
    const last = Math.min(allLines.length - 1, index + contextLines)
    for (let cursor = first; cursor <= last; cursor += 1) visible.add(cursor)
  })
  return {
    allLineCount: allLines.length,
    matchIndexes,
    lines: [...visible].sort((left, right) => left - right).map((index) => ({
      line: allLines[index],
      n: index + 1,
      isMatch: matchIndexes.includes(index),
    })),
  }
}

export function moveMatch(current, direction, count) {
  if (count <= 0) return 0
  return (current + direction + count) % count
}

export function visibleEvidenceText(lines) {
  return lines.map(({ line }) => line).join('\n')
}
