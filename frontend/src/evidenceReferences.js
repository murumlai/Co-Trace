export function validateEvidenceReferences(references, snippet) {
  const lineCount = snippet ? String(snippet).split(/\r?\n/).length : 0
  return (references || []).map((reference) => {
    if (reference.kind !== 'log_excerpt') return { ...reference, available: true, unavailableReason: null }
    const start = Number(reference.line_start)
    const end = Number(reference.line_end)
    const valid = Number.isInteger(start) && Number.isInteger(end) && start >= 1 && end >= start && end <= lineCount
    return {
      ...reference,
      available: valid,
      unavailableReason: valid ? null : 'Excerpt line range is unavailable',
    }
  })
}
