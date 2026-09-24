export function formatRate(percentage, numerator, denominator) {
  const observed = Number(denominator || 0)
  const successes = Number(numerator || 0)
  return observed > 0
    ? `${Number(percentage || 0)}% (${successes}/${observed})`
    : '— (0/0)'
}

export function firstObservedPassMetric(summary) {
  const denominator = Number(summary?.fpy_total || 0)
  if (!denominator) {
    return {
      value: formatRate(0, 0, 0),
      hint: 'No PASS/FAIL first observations',
    }
  }
  return {
    value: formatRate(summary.fpy, summary.fpy_pass, denominator),
    hint: 'Units passed on their first observed attempt',
  }
}

export function latestOutcomeTotal(summary) {
  return Number(summary?.passed || 0) + Number(summary?.failed || 0) + Number(summary?.unknown || 0)
}

export function latestObservedYieldMetric(summary) {
  const denominator = Number(summary?.latest_yield_total || 0)
  return {
    value: formatRate(summary?.latest_yield, summary?.latest_yield_pass, denominator),
    hint: denominator
      ? 'Latest PASS/FAIL unit outcomes'
      : 'No latest PASS/FAIL unit outcomes',
  }
}

export function additionalAttemptMetric(summary) {
  const denominator = Number(summary?.total_runs || 0)
  return {
    value: formatRate(summary?.additional_attempt_share, summary?.retests, denominator),
    hint: denominator
      ? "Attempts beyond each unit's first observed attempt"
      : 'No observed attempts',
  }
}