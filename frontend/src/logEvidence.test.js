import assert from 'node:assert/strict'
import test from 'node:test'
import { buildEvidenceView, moveMatch, visibleEvidenceText } from './logEvidence.js'

const TRACE = [
  'line 1 start',
  'line 2 context',
  'line 3 ERROR timeout',
  'line 4 context',
  'line 5 middle',
  'line 6 context',
  'line 7 error retry',
  'line 8 context',
  'line 9 end',
].join('\n')

test('search is case-insensitive and keeps bounded surrounding context', () => {
  const view = buildEvidenceView(TRACE, 'ERROR', 1)

  assert.deepEqual(view.matchIndexes, [2, 6])
  assert.deepEqual(view.lines.map((line) => line.n), [2, 3, 4, 6, 7, 8])
  assert.deepEqual(view.lines.filter((line) => line.isMatch).map((line) => line.n), [3, 7])
})

test('overlapping context windows do not duplicate excerpt lines', () => {
  const view = buildEvidenceView('ERROR one\ncontext\nERROR two', 'error', 2)

  assert.deepEqual(view.lines.map((line) => line.n), [1, 2, 3])
})

test('blank query preserves every original excerpt line number', () => {
  const view = buildEvidenceView('first\n\nthird', '')

  assert.equal(view.allLineCount, 3)
  assert.deepEqual(view.lines.map((line) => [line.n, line.line]), [[1, 'first'], [2, ''], [3, 'third']])
})

test('match navigation wraps in both directions', () => {
  assert.equal(moveMatch(0, 1, 3), 1)
  assert.equal(moveMatch(2, 1, 3), 0)
  assert.equal(moveMatch(0, -1, 3), 2)
  assert.equal(moveMatch(0, 1, 0), 0)
})

test('visible copy text contains only displayed redacted evidence', () => {
  const view = buildEvidenceView(TRACE, 'retry', 1)

  assert.equal(visibleEvidenceText(view.lines), 'line 6 context\nline 7 error retry\nline 8 context')
})
