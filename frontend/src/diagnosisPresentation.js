export const ANALYSIS_SOURCE_LABEL = {
  llm: 'Copilot hypothesis',
  stub: 'Offline placeholder',
  cached: 'Reused in batch',
  'local-cache': 'Saved hypothesis',
  playbook: 'Reviewed playbook',
}

export const CONTEXT_SOURCE_LABEL = {
  debug_excerpt: 'DebugLog excerpt',
  ftrunner_snippet: 'FTRunner snippet',
  error_message: 'Error message only',
}

export function assessEvidence(attempt = {}) {
  const reasons = []
  const contextSource = attempt.analysis_context_source
  if (attempt.evidence_consumed === false) {
    reasons.push('Current source references were not consumed by this reused diagnosis')
  }
  if (!contextSource) reasons.push('Analysis context metadata is unavailable')
  if (contextSource === 'error_message') reasons.push('Only the error message was available')
  if (attempt.analysis_source === 'stub') reasons.push('Offline placeholder, not a live diagnosis')
  if (attempt.knowledge_match_status && attempt.knowledge_match_status !== 'matched') {
    reasons.push('No matching product knowledge')
  }
  if (
    attempt.debuglog_status &&
    !['excerpt', 'not_applicable'].includes(attempt.debuglog_status)
  ) {
    reasons.push(attempt.debuglog_message || 'DebugLog evidence was unavailable')
  }
  const hasLogContext = ['debug_excerpt', 'ftrunner_snippet'].includes(contextSource) && attempt.evidence_consumed !== false
  return {
    grounded: hasLogContext && reasons.length === 0,
    reasons,
    sourceLabel: ANALYSIS_SOURCE_LABEL[attempt.analysis_source] || attempt.analysis_source || 'Pending analysis',
    contextLabel: CONTEXT_SOURCE_LABEL[contextSource] || 'Context source unavailable',
  }
}

export function modelConfidenceLabel(confidence) {
  return confidence == null ? null : `${Math.round(Number(confidence) * 100)}% model-reported confidence`
}
