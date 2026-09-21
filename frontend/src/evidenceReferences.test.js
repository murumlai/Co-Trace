import assert from 'node:assert/strict'
import test from 'node:test'
import { validateEvidenceReferences } from './evidenceReferences.js'

test('validates excerpt-local line bounds against redacted text', () => {
  const [reference] = validateEvidenceReferences([{
    kind: 'log_excerpt',
    line_start: 1,
    line_end: 3,
  }], 'one\ntwo\nthree')

  assert.equal(reference.available, true)
  assert.equal(reference.unavailableReason, null)
})

test('marks stale or invalid excerpt bounds unavailable', () => {
  const references = validateEvidenceReferences([
    { kind: 'log_excerpt', line_start: 0, line_end: 1 },
    { kind: 'log_excerpt', line_start: 1, line_end: 4 },
  ], 'one\ntwo\nthree')

  assert.equal(references.every((reference) => !reference.available), true)
  assert.equal(references[0].unavailableReason, 'Excerpt line range is unavailable')
})

test('knowledge references remain pending authorized lookup validation', () => {
  const [reference] = validateEvidenceReferences([{
    kind: 'knowledge_section',
    section_id: 'section-1',
  }], '')

  assert.equal(reference.available, true)
})
