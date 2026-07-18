import { useState } from 'react'
import { useAuth } from '../auth'
import { Badge, Button, Card, IconWell, Input } from '../components/ui'

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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden px-6 py-16">
      <div className="pointer-events-none absolute right-[-8rem] top-[-8rem] h-80 w-80 rounded-full bg-accent/10 blur-3xl" />
      <div className="pointer-events-none absolute bottom-[-10rem] left-[-8rem] h-96 w-96 rounded-full bg-accent-secondary/10 blur-3xl" />

      <div className="grid w-full max-w-5xl items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]">
        <div className="hidden animate-fade-up lg:block">
          <Badge tone="accent">Live QA Console</Badge>
          <h1 className="mt-6 max-w-xl font-display text-5xl leading-tight text-foreground">
            Manufacturing logs, clarified with <span className="gradient-text">precision</span>
          </h1>
          <p className="mt-5 max-w-lg text-lg leading-8 text-muted">
            Upload FTRunner batches, isolate failed units, and compare yield signals without leaving the browser.
          </p>
          <div className="relative mt-10 h-72 max-w-md">
            <div className="absolute inset-6 rounded-full border border-dashed border-accent/30 animate-rotate-slow" />
            <Card className="absolute left-0 top-6 w-56 p-5 animate-float">
              <div className="font-mono text-xs uppercase tracking-[0.15em] text-muted">First-pass yield</div>
              <div className="mt-2 font-display text-4xl gradient-text">78.65%</div>
            </Card>
            <Card className="absolute bottom-4 right-0 w-60 p-5 animate-float [animation-delay:600ms]">
              <div className="font-mono text-xs uppercase tracking-[0.15em] text-muted">Failure signatures</div>
              <div className="mt-3 flex items-end gap-2">
                <span className="h-10 w-5 rounded-t bg-accent/30" />
                <span className="h-16 w-5 rounded-t bg-accent/50" />
                <span className="h-24 w-5 rounded-t bg-gradient-to-t from-accent to-accent-secondary" />
                <span className="h-12 w-5 rounded-t bg-accent/40" />
              </div>
            </Card>
          </div>
        </div>

        <Card className="relative z-10 w-full p-8 shadow-lift-lg md:p-10">
          <div className="flex flex-col items-center text-center">
            <IconWell className="mb-6 h-16 w-16">
              <span className="font-display text-2xl">CT</span>
            </IconWell>
            <h2 className="font-display text-3xl text-foreground">Co_Trace</h2>
            <p className="mt-2 text-muted">Sign in to the manufacturing intelligence workspace.</p>
          </div>

          <form onSubmit={submit} className="mt-10 space-y-5">
            <div>
              <label className="mb-2 block text-sm font-semibold text-foreground" htmlFor="u">
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
              <label className="mb-2 block text-sm font-semibold text-foreground" htmlFor="p">
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
              <div className="rounded-xl border border-danger/20 bg-danger/10 px-4 py-3 text-sm text-danger">
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
    </div>
  )
}
