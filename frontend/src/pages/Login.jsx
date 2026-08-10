import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth'
import { Button, Card } from '../components/ui'

const AUTH_ERROR_COPY = {
  state_mismatch: 'The sign-in request expired. Please try again.',
  missing_code: 'GitHub did not return a sign-in code. Please try again.',
  oauth_failed: 'GitHub sign-in failed. Please try again.',
}

export default function Login() {
  const { login, adminLogin, sessionExpired, clearSessionNotice } = useAuth()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [showAdmin, setShowAdmin] = useState(false)
  const [adminUser, setAdminUser] = useState('')
  const [adminPass, setAdminPass] = useState('')

  const oauthError = useMemo(() => {
    const params = new URLSearchParams(window.location.search)
    return params.get('auth_error')
  }, [])

  useEffect(() => {
    if (!oauthError) return
    setError(AUTH_ERROR_COPY[oauthError] || 'GitHub sign-in failed. Please try again.')
    const url = new URL(window.location.href)
    url.searchParams.delete('auth_error')
    window.history.replaceState(null, '', url.toString())
  }, [oauthError])

  const submit = () => {
    setError('')
    clearSessionNotice()
    setBusy(true)
    login()
  }

  const submitAdmin = async (event) => {
    event.preventDefault()
    setError('')
    clearSessionNotice()
    setBusy(true)
    try {
      await adminLogin(adminUser, adminPass)
    } catch (err) {
      setError(err.message || 'Admin sign-in failed. Please try again.')
      setBusy(false)
    }
  }

  return (
    <div className="relative min-h-screen flex items-center justify-center px-6 py-16">
      {/* Subtle ambient accent glow */}
      <div
        aria-hidden="true"
        className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
      >
        <div className="absolute left-1/2 top-1/3 h-72 w-72 -translate-x-1/2 rounded-full bg-accent/10 blur-3xl" />
      </div>

      <Card className="relative z-10 w-full max-w-md p-10 md:p-12">
        <div className="flex flex-col items-center text-center">
          <div className="flex h-16 w-16 items-center justify-center rounded-xl bg-accent mb-6">
            <span className="font-display text-2xl font-extrabold text-white">CT</span>
          </div>
          <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">
            Co-Trace
          </h1>
          <p className="mt-2 text-muted">Manufacturing Log Dashboard</p>
        </div>

        <div className="mt-10 space-y-5">
          {error && (
            <div className="rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}

          {!error && sessionExpired && (
            <div className="rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
              Your session expired. Please sign in again.
            </div>
          )}

          <Button variant="primary" type="button" onClick={submit} disabled={busy} className="w-full">
            {busy ? 'Opening GitHub…' : 'Sign in with GitHub'}
          </Button>

          <div className="flex items-center gap-3 text-xs text-muted">
            <span className="h-px flex-1 bg-border" />
            <span>maintenance</span>
            <span className="h-px flex-1 bg-border" />
          </div>

          {!showAdmin ? (
            <Button
              variant="secondary"
              type="button"
              onClick={() => {
                setError('')
                setShowAdmin(true)
              }}
              disabled={busy}
              className="w-full"
            >
              Sign in as Admin
            </Button>
          ) : (
            <form onSubmit={submitAdmin} className="space-y-3">
              <input
                type="text"
                value={adminUser}
                onChange={(e) => setAdminUser(e.target.value)}
                placeholder="Admin username"
                autoComplete="username"
                className="w-full rounded-lg border border-border bg-surface px-4 py-2 text-sm text-ink focus-ring"
              />
              <input
                type="password"
                value={adminPass}
                onChange={(e) => setAdminPass(e.target.value)}
                placeholder="Admin password"
                autoComplete="current-password"
                className="w-full rounded-lg border border-border bg-surface px-4 py-2 text-sm text-ink focus-ring"
              />
              <Button variant="primary" type="submit" disabled={busy} className="w-full">
                {busy ? 'Signing in…' : 'Sign in'}
              </Button>
              <button
                type="button"
                onClick={() => setShowAdmin(false)}
                disabled={busy}
                className="w-full text-xs text-muted hover:underline focus-ring rounded"
              >
                Back to GitHub sign-in
              </button>
            </form>
          )}
        </div>
      </Card>
    </div>
  )
}
