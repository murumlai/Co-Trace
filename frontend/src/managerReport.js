import { formatRate } from './managerMetrics.js'

const FORMULA_PREFIX = /^[=+\-@]/

export function csvCell(value) {
  let text = value == null ? '' : String(value)
  if (FORMULA_PREFIX.test(text)) text = `'${text}`
  return `"${text.replaceAll('"', '""')}"`
}

const row = (...values) => values.map(csvCell).join(',')

const clone = (value) => JSON.parse(JSON.stringify(value))

export function filterActionsForScope(data, actions = []) {
  const attemptIds = data?.scope?.attempt_ids
  if (!Array.isArray(attemptIds)) return [...actions]
  const attempts = new Set(attemptIds)
  const signatures = new Set((data.pareto || []).map((item) => item.signature).filter(Boolean))
  return actions.filter((entry) => (
    entry.unit_id ? attempts.has(entry.unit_id) : entry.signature ? signatures.has(entry.signature) : false
  ))
}

export function createManagerReportSnapshot({
  jobId,
  scopeKey,
  data,
  comparison = null,
  actions = [],
  resourceStates = {},
  generatedAt = new Date().toISOString(),
}) {
  const snapshotData = clone(data)
  return Object.freeze({
    jobId,
    scopeKey,
    generatedAt,
    data: snapshotData,
    comparison: comparison ? clone(comparison) : null,
    actions: clone(filterActionsForScope(snapshotData, actions)),
    resourceStates: { ...resourceStates },
  })
}

export function buildManagerCsv(data, comparison = null, generatedAt = new Date().toISOString(), actions = [], resourceStates = {}) {
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
    row('Actor attribution', 'Assignees show responsibility. Recorded shared-workspace/Admin labels do not identify an individual editor.'),
    row('Completeness', `${batch.included_run_count ?? 'unavailable'}/${batch.discovered_run_count ?? 'unavailable'} parsed runs included`),
    row('Quality flags', `parse excluded=${batch.parse_excluded_count ?? 'unavailable'}; incomplete=${batch.incomplete_folder_count ?? 'unavailable'}; unknown=${batch.unknown_result_count ?? 'unavailable'}; missing DebugLog=${batch.missing_debuglog_count ?? 'unavailable'}`),
    row('Comparison availability', comparison?.available ? 'available' : (comparison?.reason || 'unavailable')),
    row('Comparison resource', resourceStates.comparison || (comparison ? 'available' : 'unavailable')),
    row('Investigation-action resource', resourceStates.actions || 'available'),
    row('Comparison baseline', comparison?.baseline?.display_name || ''),
    row('Comparison sample sizes', comparison?.scope ? `${comparison.scope.current_attempts} current attempts; ${comparison.scope.baseline_attempts} baseline attempts` : ''),
    row('First observed pass-rate delta (percentage points)', comparison?.metrics?.first_observed_pass_rate?.delta_pp ?? ''),
    row('Latest unit-yield delta (percentage points)', comparison?.metrics?.latest_observed_unit_yield?.delta_pp ?? ''),
    row('Target', comparison?.target && comparison.target.available !== false ? `${comparison.target.percent}% ${comparison.target.metric}; gap ${comparison.target.gap_pp} percentage points; provenance=${comparison.target.provenance}` : (comparison?.target?.reason || '')),
    '',
    row('KPI', 'Value', 'Denominator / definition'),
    row('First observed pass rate', formatRate(summary.fpy, summary.fpy_pass, summary.fpy_total), 'Units passed on their first observed attempt'),
    row('Latest observed unit yield', formatRate(summary.latest_yield, summary.latest_yield_pass, summary.latest_yield_total), 'Latest PASS/FAIL units'),
    row('Still-failing units', summary.failed, `${summary.failed}/${summary.unique_units} observed units`),
    row('Additional-attempt share', formatRate(summary.additional_attempt_share, summary.retests, summary.total_runs), "Attempts beyond each unit's first observed attempt"),
    row('Recovered after retry', summary.recovered_after_retry, 'Latest PASS after observed first FAIL'),
    row('Unknown latest outcomes', summary.unknown, `${summary.unknown}/${summary.unique_units} observed units`),
    '',
    row('Failure Pareto'),
    row('Rank', 'Failure family', 'Failed attempts', 'Share %', 'Cumulative %', 'Affected units'),
    ...(data.pareto || []).map((item, index) => row(
      index + 1,
      item.reason,
      item.count,
      formatRate(item.pct, item.count, item.total || summary.failed_attempts),
      formatRate(item.cum_pct, item.cum_count, item.total || summary.failed_attempts),
      (item.unit_ids || []).join('; '),
    )),
    '',
    row('Station / tester attempts'),
    row('Station / tester', 'Volume', 'PASS', 'FAIL', 'Failure rate %'),
    ...(data.stations || []).map((item) => row(item.station, item.total, item.pass, item.fail, formatRate(item.total ? (item.fail / item.total) * 100 : 0, item.fail, item.total))),
    '',
    row('Lot attempt comparison'),
    row('Lot', 'Volume', 'PASS', 'FAIL', 'Pass rate %'),
    ...(data.lots || []).map((item) => row(item.lot, item.total, item.pass, item.fail, formatRate(item.yield, item.pass, item.total))),
    '',
    row('Attempt pass-rate trend'),
    row('Date', 'PASS', 'FAIL', 'Pass rate %'),
    ...(data.trend || []).map((item) => row(item.date, item.pass, item.fail, formatRate(item.yield, item.pass, item.pass + item.fail))),
    '',
    row('Recommended actions', 'Not included in aggregate export; use scoped Engineer drill-down and redacted debug packets.'),
    '',
    row('Investigation actions'),
    row('Failure', 'Next action', 'Assignee', 'Status', 'Updated', 'Version', 'Recorded actor'),
    ...actions.map((item) => row(
      item.error_code || item.signature || item.unit_id,
      item.next_action,
      item.assignee || 'Unassigned',
      item.status,
      item.updated_at,
      item.version,
      item.history?.at(-1)?.actor_login || 'unavailable',
    )),
  ]
  return `${lines.join('\r\n')}\r\n`
}

export function managerReportFilename(jobId, scopeKey = 'all', generatedAt = new Date().toISOString()) {
  const safe = (value, fallback, limit) => String(value || fallback)
    .replace(/[^A-Za-z0-9.-]+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, limit) || fallback
  const job = safe(jobId, 'batch', 48)
  const scope = safe(scopeKey, 'all', 48)
  const timestamp = safe(generatedAt.replace(/\.\d{3}Z$/, 'Z'), 'time', 32)
  return `co-trace_${job}_${scope}_${timestamp}.csv`
}
