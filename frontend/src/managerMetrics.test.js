import assert from 'node:assert/strict'
import test from 'node:test'
import { firstObservedPassMetric, formatRate, latestOutcomeTotal } from './managerMetrics.js'

test('formats a first-observed pass rate with its unit denominator', () => {
  assert.deepEqual(firstObservedPassMetric({ fpy: 75, fpy_pass: 3, fpy_total: 4 }), {
    value: '75%',
    hint: '3/4 units passed on their first observed attempt',
  })
})

test('does not present zero percent when no PASS or FAIL observation exists', () => {
  assert.deepEqual(firstObservedPassMetric({ fpy: 0, fpy_pass: 0, fpy_total: 0 }), {
    value: '—',
    hint: 'No PASS/FAIL first observations',
  })
  assert.equal(formatRate(0, 0), '—')
})

test('latest outcomes reconcile passed, failed, and unknown units', () => {
  assert.equal(latestOutcomeTotal({ passed: 5, failed: 2, unknown: 1 }), 8)
  assert.equal(latestOutcomeTotal({ passed: 0, failed: 0, unknown: 4 }), 4)
})