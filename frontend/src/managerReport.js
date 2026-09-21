const FORMULA_PREFIX = /^[=+\-@]/

export function csvCell(value) {
  let text = value == null ? '' : String(value)
  if (FORMULA_PREFIX.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

const row = (...values) => values.map(csvCell).join(',')

export function buildManagerCsv(data, comparison = null, generatedAt = new Date().toISOString(), actions = []) {
  const summary = data.summary || {}
  const scope = data.scope || {}
  const batch = data.batch || {}
  const filters = scope.filters || {}
  const lines = [
    row('Co-Trace scoped shift review'),
    row('Generated at', generatedAt),
    row('Batch', batch.display_name || 'Unavailable'),
    row('Products', (batch.product_codes || []).join('; ')),
    row('Observed period', batch.observed_start_time || '', batch.observed_end_time || ''),
    row('Timezone', batch.timestamp_timezone || 'unavailable'),
    row('Active product filters', (filters.products || []).join('; ')),
    row('Active lot filters', (filters.lots || []).join('; ')),
    row('Active station filters', (filters.stations || []).join('; ')),
    row('Active time filter', filters.start_time || '', filters.end_time || ''),
    row('Definition', 'All measures describe attempts selected within this uploaded batch. First/latest are calculated within the selection.'),
    row('Completeness', `${batch.included_run_count ?? 'unavailable'}/${batch.discovered_run_count ?? 'unavailable'} parsed runs included`),
    row('Quality flags', `parse excluded=${batch.parse_excluded_count ?? 'unavailable'}; incomplete=${batch.incomplete_folder_count ?? 'unavailable'}; unknown=${batch.unknown_result_count ?? 'unavailable'}; missing DebugLog=${batch.missing_debuglog_count ?? 'unavailable'}`),
    row('Comparison availability', comparison?.available ? 'available' : (comparison?.reason || 'unavailable')),
    row('Comparison baseline', comparison?.baseline?.display_name || ''),
    row('Comparison sample sizes', comparison?.scope ? `${comparison.scope.current_attempts} current attempts; ${comparison.scope.baseline_attempts} baseline attempts` : ''),
    row('First observed pass-rate delta (percentage points)', comparison?.metrics?.first_observed_pass_rate?.delta_pp ?? ''),
    row('Latest unit-yield delta (percentage points)', comparison?.metrics?.latest_observed_unit_yield?.delta_pp ?? ''),
    row('Target', comparison?.target ? `${comparison.target.percent}% ${comparison.target.metric}; gap ${comparison.target.gap_pp} percentage points; provenance=${comparison.target.provenance}` : ''),
    '',
    row('KPI', 'Value', 'Denominator / definition'),
    row('First observed pass rate', summary.fpy, `${summary.fpy_pass}/${summary.fpy_total} units`),
    row('Latest observed unit yield', summary.latest_yield, `${summary.latest_yield_pass}/${summary.latest_yield_total} latest PASS/FAIL units`),
    row('Still-failing units', summary.failed, `${summary.failed}/${summary.unique_units} observed units`),
    row('Additional-attempt share', summary.additional_attempt_share, `${summary.retests}/${summary.total_runs} attempts`),
    row('Recovered after retry', summary.recovered_after_retry, 'Latest PASS after observed first FAIL'),
    row('Unknown latest outcomes', summary.unknown, `${summary.unknown}/${summary.unique_units} observed units`),
    '',
    row('Failure Pareto'),
    row('Rank', 'Failure family', 'Failed attempts', 'Share %', 'Cumulative %', 'Affected units'),
    ...(data.pareto || []).map((item, index) => row(index + 1, item.reason, item.count, item.pct, item.cum_pct, (item.unit_ids || []).join('; '))),
    '',
    row('Station / tester attempts'),
    row('Station / tester', 'Volume', 'PASS', 'FAIL', 'Failure rate %'),
    ...(data.stations || []).map((item) => row(item.station, item.total, item.pass, item.fail, item.total ? ((item.fail / item.total) * 100).toFixed(2) : '')),
    '',
    row('Lot attempt comparison'),
    row('Lot', 'Volume', 'PASS', 'FAIL', 'Pass rate %'),
    ...(data.lots || []).map((item) => row(item.lot, item.total, item.pass, item.fail, item.yield)),
    '',
    row('Attempt pass-rate trend'),
    row('Date', 'PASS', 'FAIL', 'Pass rate %'),
    ...(data.trend || []).map((item) => row(item.date, item.pass, item.fail, item.yield)),
    '',
    row('Recommended actions', 'Not included in aggregate export; use scoped Engineer drill-down and redacted debug packets.'),
    '',
    row('Verified investigation actions'),
    row('Failure', 'Next action', 'Owner', 'Status', 'Updated', 'Version'),
    ...actions.map((item) => row(item.error_code || item.signature || item.unit_id, item.next_action, item.assignee || 'Unassigned', item.status, item.updated_at, item.version)),
  ]
  return `${lines.join('\r\n')}\r\n`
}

export function managerReportFilename(displayName) {
  const safe = String(displayName || 'batch').replace(/[^A-Za-z0-9._-]+/g, '-').replace(/^-|-$/g, '').slice(0, 80) || 'batch'
  return `co-trace-${safe}-shift-review.csv`
}
