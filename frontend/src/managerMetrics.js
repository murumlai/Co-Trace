export function formatRate(percentage, denominator) {
  return Number(denominator) > 0 ? `${Number(percentage || 0)}%` : '—'
}

export function firstObservedPassMetric(summary) {
  const denominator = Number(summary?.fpy_total || 0)
  if (!denominator) {
    return {
      value: '—',
      hint: 'No PASS/FAIL first observations',
    }
  }
  return {
    value: formatRate(summary.fpy, denominator),
    hint: `${summary.fpy_pass}/${denominator} units passed on their first observed attempt`,
  }
}

export function latestOutcomeTotal(summary) {
  return Number(summary?.passed || 0) + Number(summary?.failed || 0) + Number(summary?.unknown || 0)
}