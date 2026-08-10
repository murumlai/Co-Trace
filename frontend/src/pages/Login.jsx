import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../auth'
import { Button, Card } from '../components/ui'

const AUTH_ERROR_COPY = {
  state_mismatch: 'The sign-in request expired. Please try again.',
  missing_code: 'GitHub did not return a sign-in code. Please try again.',
  oauth_failed: 'GitHub sign-in failed. Please try again.',
}

export default function Login() {
  const { login, sessionExpired, clearSessionNotice } = useAuth()
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

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
        </div>
      </Card>
    </div>
  )
}
