import { useState } from 'react'
import { useAuth } from '../auth'
import { Button, Card, Input } from '../components/ui'

export default function Login() {
  const { login, sessionExpired } = useAuth()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setError('')
    setBusy(true)
    try {
      await login(username, password)
    } catch (err) {
      setError(err.message)
    } finally {
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

        <form onSubmit={submit} className="mt-10 space-y-5">
          <div>
            <label className="block text-sm font-medium text-ink-2 mb-2" htmlFor="u">
              Username
            </label>
            <Input
              id="u"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              placeholder="admin"
              autoComplete="username"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-ink-2 mb-2" htmlFor="p">
              Password
            </label>
            <Input
              id="p"
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              placeholder="••••••"
              autoComplete="current-password"
            />
          </div>

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

          <Button variant="primary" type="submit" disabled={busy} className="w-full">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-muted">
          Placeholder auth — default <span className="font-semibold text-ink-2">admin / admin</span>
        </p>
      </Card>
    </div>
  )
}
