import { useState } from 'react'
import { useAuth } from '../auth'
import { Button, Card, IconWell, Input } from '../components/ui'

export default function Login() {
  const { login } = useAuth()
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
    <div className="min-h-screen flex items-center justify-center px-6 py-16">
      {/* Ambient decorative wells */}
      <div className="pointer-events-none absolute -z-0 opacity-60">
        <div className="h-72 w-72 rounded-full bg-base shadow-extruded animate-float" />
      </div>

      <Card className="relative z-10 w-full max-w-md p-10 md:p-12">
        <div className="flex flex-col items-center text-center">
          <IconWell className="h-16 w-16 mb-6">
            <span className="font-display text-2xl font-extrabold text-accent">CT</span>
          </IconWell>
          <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">
            Co_Trace
          </h1>
          <p className="mt-2 text-muted">Manufacturing Log Dashboard</p>
        </div>

        <form onSubmit={submit} className="mt-10 space-y-5">
          <div>
            <label className="block text-sm font-medium text-muted mb-2" htmlFor="u">
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
            <label className="block text-sm font-medium text-muted mb-2" htmlFor="p">
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
            <div className="rounded-2xl bg-base shadow-inset-sm px-4 py-3 text-sm text-danger">
              {error}
            </div>
          )}

          <Button variant="primary" type="submit" disabled={busy} className="w-full">
            {busy ? 'Signing in…' : 'Sign in'}
          </Button>
        </form>

        <p className="mt-6 text-center text-xs text-muted">
          Placeholder auth — default <span className="font-semibold">admin / admin</span>
        </p>
      </Card>
    </div>
  )
}
