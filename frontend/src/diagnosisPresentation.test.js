import assert from 'node:assert/strict'
import test from 'node:test'
import { assessEvidence, modelConfidenceLabel } from './diagnosisPresentation.js'

test('missing metadata never produces a grounded evidence label', () => {
  const assessment = assessEvidence({})

  assert.equal(assessment.grounded, false)
  assert.match(assessment.reasons.join(' '), /metadata is unavailable/)
  assert.equal(assessment.contextLabel, 'Context source unavailable')
})

test('redacted log context with no known limitations is grounded', () => {
  const assessment = assessEvidence({
    analysis_source: 'llm',
    analysis_context_source: 'debug_excerpt',
    knowledge_match_status: 'matched',
    debuglog_status: 'excerpt',
  })

  assert.equal(assessment.grounded, true)
  assert.deepEqual(assessment.reasons, [])
  assert.equal(assessment.sourceLabel, 'Copilot hypothesis')
})

test('error-only, offline, missing-log, and unmatched-knowledge limitations are explicit', () => {
  const assessment = assessEvidence({
    analysis_source: 'stub',
    analysis_context_source: 'error_message',
    knowledge_match_status: 'no_match',
    debuglog_status: 'not_found',
    debuglog_message: 'DebugLog not found',
  })

  assert.equal(assessment.grounded, false)
  assert.deepEqual(assessment.reasons, [
    'Only the error message was available',
    'Offline placeholder, not a live diagnosis',
    'No matching product knowledge',
    'DebugLog not found',
  ])
  assert.equal(assessment.sourceLabel, 'Offline placeholder')
})

test('confidence is explicitly model-reported', () => {
  assert.equal(modelConfidenceLabel(0.824), '82% model-reported confidence')
  assert.equal(modelConfidenceLabel(null), null)
})
