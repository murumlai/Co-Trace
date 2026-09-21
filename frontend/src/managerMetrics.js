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

export function latestObservedYieldMetric(summary) {
  const denominator = Number(summary?.latest_yield_total || 0)
  return {
    value: formatRate(summary?.latest_yield, denominator),
    hint: denominator
      ? `${summary.latest_yield_pass}/${denominator} latest PASS/FAIL unit outcomes`
      : 'No latest PASS/FAIL unit outcomes',
  }
}

export function additionalAttemptMetric(summary) {
  const denominator = Number(summary?.total_runs || 0)
  return {
    value: formatRate(summary?.additional_attempt_share, denominator),
    hint: denominator
      ? `${summary.retests}/${denominator} attempts beyond each unit's first observed attempt`
      : 'No observed attempts',
  }
}