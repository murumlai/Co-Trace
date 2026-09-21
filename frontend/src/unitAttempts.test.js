import assert from 'node:assert/strict'
import test from 'node:test'
import { groupAttempts } from './unitAttempts.js'

test('counts three matching failures across two units without duplicating final attempts', () => {
  const first = {
    unit_id: 'unit-a-attempt-1',
    signature: 'link-timeout',
    station_id: 'station-1',
    host: 'tester-1',
    lot_id: 'lot-1',
  }
  const final = { ...first, unit_id: 'unit-a-attempt-2' }
  const other = { ...first, unit_id: 'unit-b-attempt-1' }
  const units = [
    { final: { ...final }, failures: [first, final] },
    { final: { ...other }, failures: [other] },
  ]
  const predicates = [
    (attempt) => attempt.signature === 'link-timeout',
    (attempt) => attempt.station_id === 'station-1' && attempt.host === 'tester-1',
    (attempt) => attempt.lot_id === 'lot-1',
  ]

  for (const matchesAttempt of predicates) {
    const matchingUnits = units.filter((unit) => groupAttempts(unit).some(matchesAttempt))
    const attemptCount = matchingUnits.reduce(
      (total, unit) => total + groupAttempts(unit).filter(matchesAttempt).length,
      0,
    )
    assert.equal(matchingUnits.length, 2)
    assert.equal(attemptCount, 3)
  }
})

test('preserves distinct failed retries and the final passing attempt', () => {
  const first = { unit_id: 'attempt-1', result: 'FAIL', signature: 'same-failure' }
  const second = { ...first, unit_id: 'attempt-2' }
  const final = { unit_id: 'attempt-3', result: 'PASS' }

  assert.deepEqual(groupAttempts({ final, failures: [first, second] }), [final, first, second])
})

test('keeps first-pass and unknown final attempts without failures', () => {
  for (const result of ['PASS', 'UNKNOWN']) {
    const final = { unit_id: 'attempt-1', result }
    assert.deepEqual(groupAttempts({ final }), [final])
    assert.deepEqual(groupAttempts({ final, failures: [] }), [final])
  }
})

test('handles missing final attempts and empty groups', () => {
  const failure = { unit_id: 'attempt-1', result: 'FAIL' }

  assert.deepEqual(groupAttempts({ failures: [failure] }), [failure])
  assert.deepEqual(groupAttempts({ final: null, failures: [] }), [])
  assert.deepEqual(groupAttempts({}), [])
})

test('retains refreshed failure metadata without mutating the group', () => {
  const final = Object.freeze({ unit_id: 'attempt-1', root_cause: 'Original diagnosis' })
  const updated = Object.freeze({ ...final, root_cause: 'Updated diagnosis' })
  const failures = Object.freeze([updated])
  const group = Object.freeze({ final, failures })

  assert.deepEqual(groupAttempts(group), [updated])
  assert.equal(group.final.root_cause, 'Original diagnosis')
  assert.equal(group.failures, failures)
})