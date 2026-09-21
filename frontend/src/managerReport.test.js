import assert from 'node:assert/strict'
import test from 'node:test'
import { buildManagerCsv, csvCell, managerReportFilename } from './managerReport.js'

test('escapes CSV delimiters, quotes, line breaks, and spreadsheet formulas', () => {
  assert.equal(csvCell('a,b"c\nd'), '"a,b""c\nd"')
  assert.equal(csvCell('=HYPERLINK("bad")'), '"\'=HYPERLINK(""bad"")"')
  assert.equal(csvCell('+SUM(1,2)'), '"\'+SUM(1,2)"')
  assert.equal(csvCell('-1+2'), '"\'-1+2"')
  assert.equal(csvCell('@cmd'), '"\'@cmd"')
})

test('exports active scope, completeness, KPIs, and aggregate tables', () => {
  const csv = buildManagerCsv({
    batch: {
      display_name: 'Line 7', product_codes: ['P1'], included_run_count: 2,
      discovered_run_count: 3, parse_excluded_count: 1, incomplete_folder_count: 0,
      unknown_result_count: 0, missing_debuglog_count: 1,
    },
    scope: { filters: { products: ['P1'], lots: ['L1'], stations: ['S1'] } },
    summary: {
      fpy: 50, fpy_pass: 1, fpy_total: 2, latest_yield: 100,
      latest_yield_pass: 2, latest_yield_total: 2, failed: 0, unique_units: 2,
      additional_attempt_share: 33.33, retests: 1, total_runs: 3,
      recovered_after_retry: 1, unknown: 0,
    },
    pareto: [{ reason: '=unsafe', count: 1, pct: 100, cum_pct: 100, unit_ids: ['SN1'] }],
    stations: [{ station: 'H / ST1', total: 2, pass: 1, fail: 1 }],
    lots: [{ lot: 'L1', total: 2, pass: 1, fail: 1, yield: 50 }],
    trend: [{ date: '2026-09-21', pass: 1, fail: 1, yield: 50 }],
  }, {
    available: true,
    baseline: { display_name: 'Prior batch' },
    scope: { current_attempts: 3, baseline_attempts: 4 },
    metrics: {
      first_observed_pass_rate: { delta_pp: 5 },
      latest_observed_unit_yield: { delta_pp: 10 },
    },
    target: { percent: 95, metric: 'latest_observed_unit_yield', gap_pp: 5, provenance: 'user_entered' },
  }, '2026-09-21T12:00:00Z', [{
    error_code: 'E1', next_action: 'Inspect fixture', assignee: 'Test team',
    status: 'in_progress', updated_at: '2026-09-21T11:00:00Z', version: 2,
  }])

  assert.match(csv, /Active product filters","P1/)
  assert.match(csv, /2\/3 parsed runs included/)
  assert.match(csv, /Latest observed unit yield/)
  assert.match(csv, /"'=unsafe"/)
  assert.match(csv, /Attempt pass-rate trend/)
  assert.match(csv, /Prior batch/)
  assert.match(csv, /provenance=user_entered/)
  assert.match(csv, /Verified investigation actions/)
  assert.match(csv, /Inspect fixture/)
  assert.match(csv, /Not included in aggregate export/)
})

test('creates a bounded filesystem-safe report filename', () => {
  assert.equal(managerReportFilename('Line 7 / Product A'), 'co-trace-Line-7-Product-A-shift-review.csv')
  assert.match(managerReportFilename('='.repeat(200)), /^co-trace-batch-/)
})
