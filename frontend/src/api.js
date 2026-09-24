import { debugLog, log } from './logger'

async function request(path, { method = 'GET', body, headers = {}, signal, authOptional = false, responseType = 'json' } = {}) {
  const started = performance.now()
  let res
  try {
    res = await fetch(path, {
      method,
      credentials: 'include',
      headers: {
        ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...headers,
      },
      body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
      signal,
    })
  } catch (error) {
    if (error.name !== 'AbortError') {
      log('error', 'API network error', { path, method, error: error.message })
    }
    throw error
  }
  const durationMs = Math.round(performance.now() - started)
  debugLog('API response', { path, method, status: res.status, durationMs })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    if (!authOptional && (res.status === 401 || (res.status === 403 && detail.detail === 'Admin access required'))) {
      window.dispatchEvent(new CustomEvent('cotrace:unauthorized', { detail: { startedAt: started } }))
    }
    log('warning', 'API request failed', { path, method, status: res.status, durationMs, detail: detail.detail })
    const error = new Error(detail.detail || `Request failed (${res.status})`)
    error.status = res.status
    error.payload = detail.detail
    if (detail.detail && typeof detail.detail === 'object' && detail.detail.message) {
      error.message = detail.detail.message
    }
    throw error
  }
  if (method !== 'GET') {
    log('info', 'API request completed', { path, method, status: res.status, durationMs })
  }
  if (responseType === 'text') return res.text()
  return res.json()
}

export const api = {
  me: (options = {}) => request('/api/me', options),
  adminLogin: (payload) =>
    request('/api/auth/admin/login', { method: 'POST', body: payload, authOptional: true }),
  logout: () => request('/api/logout', { method: 'POST', authOptional: true }),
  upload: (formData, options = {}) => request('/api/upload', { method: 'POST', body: formData, ...options }),
  jobs: ({ limit = 20, cursor } = {}) => {
    const params = new URLSearchParams({ limit: String(limit) })
    if (cursor) params.set('cursor', cursor)
    return request(`/api/jobs?${params}`)
  },
  status: (jobId) => request(`/api/jobs/${jobId}/status`),
  stop: (jobId) => request(`/api/jobs/${jobId}/stop`, { method: 'POST' }),
  units: (jobId) => request(`/api/jobs/${jobId}/units`),
  clusters: (jobId) => request(`/api/jobs/${jobId}/clusters`),
  debugPacket: (jobId, { unitId, signature }) => {
    const params = new URLSearchParams()
    if (unitId) params.set('unit_id', unitId)
    if (signature) params.set('signature', signature)
    return request(`/api/jobs/${jobId}/debug-packet?${params}`, { responseType: 'text' })
  },
  feedback: (jobId) => request(`/api/jobs/${jobId}/feedback`),
  createFeedback: (jobId, payload) =>
    request(`/api/jobs/${jobId}/feedback`, { method: 'POST', body: payload }),
  actions: (jobId) => request(`/api/jobs/${jobId}/actions`),
  createAction: (jobId, payload) =>
    request(`/api/jobs/${jobId}/actions`, { method: 'POST', body: payload }),
  updateAction: (jobId, actionId, payload) =>
    request(`/api/jobs/${jobId}/actions/${actionId}`, { method: 'PATCH', body: payload }),
  reanalyze: (jobId, unitId) =>
    request(`/api/jobs/${jobId}/units/${unitId}/reanalyze`, { method: 'POST' }),
  manager: (jobId, scope = {}) => {
    const params = new URLSearchParams()
    ;(scope.products || []).forEach((value) => params.append('product', value))
    ;(scope.lots || []).forEach((value) => params.append('lot', value))
    ;(scope.stations || []).forEach((value) => params.append('station', value))
    if (scope.startTime) params.set('start_time', scope.startTime)
    if (scope.endTime) params.set('end_time', scope.endTime)
    const query = params.toString()
    return request(`/api/jobs/${jobId}/manager${query ? `?${query}` : ''}`)
  },
  comparison: (jobId, scope = {}) => {
    const params = new URLSearchParams()
    ;(scope.products || []).forEach((value) => params.append('product', value))
    ;(scope.lots || []).forEach((value) => params.append('lot', value))
    ;(scope.stations || []).forEach((value) => params.append('station', value))
    if (scope.targetPercent !== '' && scope.targetPercent != null) {
      params.set('target_metric', scope.targetMetric || 'first_observed_pass_rate')
      params.set('target_percent', String(scope.targetPercent))
    }
    const query = params.toString()
    return request(`/api/jobs/${jobId}/comparison${query ? `?${query}` : ''}`)
  },
  analysisCache: () => request('/api/cache/analysis'),
  clearAnalysisCache: (cacheKey) =>
    request(`/api/cache/analysis/${cacheKey}`, { method: 'DELETE' }),
  clearJobCache: (jobId) => request(`/api/jobs/${jobId}/cache`, { method: 'DELETE' }),
  // Product-aware diagnosis: knowledge pack management.
  knowledge: () => request('/api/knowledge'),
  knowledgeScan: () => request('/api/knowledge/scan'),
  knowledgeSections: (product) =>
    request(`/api/knowledge/sections${product ? `?product=${encodeURIComponent(product)}` : ''}`),
  playbooks: (product, status) => {
    const params = new URLSearchParams()
    if (product) params.set('product', product)
    if (status) params.set('status', status)
    const query = params.toString()
    return request(`/api/knowledge/playbooks${query ? `?${query}` : ''}`)
  },
  createPlaybook: (payload) => request('/api/knowledge/playbooks', { method: 'POST', body: payload }),
  updatePlaybook: (playbookId, payload) =>
    request(`/api/knowledge/playbooks/${playbookId}`, { method: 'PATCH', body: payload }),
  retirePlaybook: (playbookId) =>
    request(`/api/knowledge/playbooks/${playbookId}`, { method: 'DELETE' }),
  knowledgeUploadCheck: (filename) =>
    request(`/api/knowledge/upload/check?filename=${encodeURIComponent(filename)}`),
  knowledgeJob: (jobId) => request(`/api/knowledge/jobs/${jobId}`),
  knowledgeRebuild: () => request('/api/knowledge/rebuild', { method: 'POST' }),
  knowledgeUpload: (formData, options = {}) =>
    request('/api/knowledge/upload', { method: 'POST', body: formData, ...options }),
  knowledgeDeleteDocument: (docId) =>
    request(`/api/knowledge/documents/${docId}`, { method: 'DELETE' }),
  knowledgeDeletePack: () => request('/api/knowledge', { method: 'DELETE' }),
  // Authoritative acronym glossary: review + maintenance.
  acronyms: (product, status) => {
    const params = new URLSearchParams()
    if (product) params.set('product', product)
    if (status) params.set('status', status)
    const qs = params.toString()
    return request(`/api/knowledge/acronyms${qs ? `?${qs}` : ''}`)
  },
  upsertAcronym: (payload) =>
    request('/api/knowledge/acronyms', { method: 'POST', body: payload }),
  deleteAcronym: (acronym, product) => {
    const params = new URLSearchParams({ acronym })
    if (product) params.set('product', product)
    return request(`/api/knowledge/acronyms?${params.toString()}`, { method: 'DELETE' })
  },
}
