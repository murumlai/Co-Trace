// Thin API client. Token is kept in localStorage for the placeholder auth.

const TOKEN_KEY = 'cotrace_token'

export function getToken() {
  return localStorage.getItem(TOKEN_KEY)
}
export function setToken(t) {
  if (t) localStorage.setItem(TOKEN_KEY, t)
  else localStorage.removeItem(TOKEN_KEY)
}

async function request(path, { method = 'GET', body, headers = {} } = {}) {
  const token = getToken()
  const res = await fetch(path, {
    method,
    headers: {
      ...(body && !(body instanceof FormData) ? { 'Content-Type': 'application/json' } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...headers,
    },
    body: body instanceof FormData ? body : body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}))
    throw new Error(detail.detail || `Request failed (${res.status})`)
  }
  return res.json()
}

export const api = {
  login: (username, password) =>
    request('/api/login', { method: 'POST', body: { username, password } }),
  me: () => request('/api/me'),
  upload: (formData) => request('/api/upload', { method: 'POST', body: formData }),
  status: (jobId) => request(`/api/jobs/${jobId}/status`),
  units: (jobId) => request(`/api/jobs/${jobId}/units`),
  reanalyze: (jobId, unitId) =>
    request(`/api/jobs/${jobId}/units/${unitId}/reanalyze`, { method: 'POST' }),
  manager: (jobId) => request(`/api/jobs/${jobId}/manager`),
}
