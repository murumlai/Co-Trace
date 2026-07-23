// Thin API client. Token is kept in localStorage for the placeholder auth.
import { debugLog, log } from './logger'

const TOKEN_KEY = 'cotrace_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request(path, { method = 'GET', body, headers = {}, signal } = {}) {
  const token = getToken()
  const started = performance.now()
  let res
  try {
    res = await fetch(path, {
      method,
      headers: {
        ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
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
  if (res.status === 401 && path !== '/api/login') {
    // Stale/expired bearer token (e.g. backend restarted, or the session
    // TTL lapsed). Clear it and let the app fall back to the login screen
    // instead of surfacing a raw 401 error mid-action.
    setToken(null)
    window.dispatchEvent(new Event('cotrace:unauthorized'))
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    log('warning', 'API request failed', { path, method, status: res.status, durationMs, detail: detail.detail })
    throw new Error(detail.detail || `Request failed (${res.status})`)
  }
  if (method !== 'GET') {
    log('info', 'API request completed', { path, method, status: res.status, durationMs })
  }
  return res.json()
}

export const api = {
  login: (username, password) =>
    request('/api/login', { method: 'POST', body: { username, password } }),
  me: () => request('/api/me'),
  upload: (formData, options = {}) => request('/api/upload', { method: 'POST', body: formData, ...options }),
  status: (jobId) => request(`/api/jobs/${jobId}/status`),
  stop: (jobId) => request(`/api/jobs/${jobId}/stop`, { method: 'POST' }),
  units: (jobId) => request(`/api/jobs/${jobId}/units`),
  reanalyze: (jobId, unitId) =>
    request(`/api/jobs/${jobId}/units/${unitId}/reanalyze`, { method: 'POST' }),
  manager: (jobId) => request(`/api/jobs/${jobId}/manager`),
  analysisCache: () => request('/api/cache/analysis'),
  clearAnalysisCache: (cacheKey) =>
    request(`/api/cache/analysis/${cacheKey}`, { method: 'DELETE' }),
  clearJobCache: (jobId) => request(`/api/jobs/${jobId}/cache`, { method: 'DELETE' }),
}
