const LOG_ENDPOINT = '/api/logs/frontend'
const SECRET_KEY_RE = /(token|password|passwd|authorization|secret|apikey|api_key)/i
const DEBUG_ENABLED =
  import.meta.env.VITE_COTRACE_DEBUG === '1' ||
  localStorage.getItem('cotrace_debug') === '1' ||
  new URLSearchParams(window.location.search).get('debug') === '1'

let initialized = false

export function isDebugLogging() {
  return DEBUG_ENABLED
}

export function initFrontendLogging() {
  if (initialized) return
  initialized = true
  log('info', 'Frontend started', {
    debug: DEBUG_ENABLED,
    mode: import.meta.env.MODE,
    path: window.location.pathname,
  })
  window.addEventListener('error', (event) => {
    log('error', 'Browser error', {
      message: event.message,
      filename: event.filename,
      lineno: event.lineno,
      colno: event.colno,
    })
  })
  window.addEventListener('unhandledrejection', (event) => {
    log('error', 'Unhandled browser promise rejection', {
      reason: String(event.reason?.message || event.reason || 'unknown'),
    })
  })
}

export function debugLog(message, context = {}) {
  log('debug', message, context)
}

export function log(level, message, context = {}) {
  const normalized = normalizeLevel(level)
  if (normalized === 'debug' && !DEBUG_ENABLED) return
  const payload = JSON.stringify({
    level: normalized,
    message,
    context: sanitizeContext({
      ...context,
      path: context.path || window.location.pathname,
      debug: DEBUG_ENABLED,
    }),
  })
  try {
    if (navigator.sendBeacon) {
      const queued = navigator.sendBeacon(LOG_ENDPOINT, new Blob([payload], { type: 'application/json' }))
      if (queued) return
    }
    fetch(LOG_ENDPOINT, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      keepalive: true,
    }).catch(() => {})
  } catch {
    // Logging must never affect the app flow.
  }
}

function normalizeLevel(level) {
  const lowered = String(level || 'info').toLowerCase()
  return ['debug', 'info', 'warning', 'error'].includes(lowered) ? lowered : 'info'
}

function sanitizeContext(value, depth = 0) {
  if (depth > 4) return '[MAX_DEPTH]'
  if (value == null) return value
  if (Array.isArray(value)) return value.slice(0, 50).map((item) => sanitizeContext(item, depth + 1))
  if (typeof value === 'object') {
    return Object.fromEntries(
      Object.entries(value).map(([key, item]) => [
        key,
        SECRET_KEY_RE.test(key) ? '[REDACTED]' : sanitizeContext(item, depth + 1),
      ]),
    )
  }
  const text = String(value)
  return text.length > 500 ? `${text.slice(0, 500)}...[truncated]` : value
}