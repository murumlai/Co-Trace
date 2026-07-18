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
    <div className="min-h-screen bg-background px-4 py-6 sm:px-6 md:flex md:items-center md:justify-center">
      <div className="grid w-full max-w-6xl overflow-hidden border border-border bg-card md:min-h-[680px] md:grid-cols-[0.95fr_1.05fr]">
        <div className="animate-fade-up bg-foreground p-6 text-white dot-texture sm:p-8 md:p-10">
          <div className="h-full bg-foreground p-10 text-white dot-texture">
            <Badge tone="accent">Live QA Console</Badge>
            <h1 className="mt-6 max-w-xl text-3xl font-semibold leading-tight tracking-tight sm:text-4xl">
              Manufacturing logs, clarified with <span className="gradient-text">precision</span>
            </h1>
            <p className="mt-5 max-w-lg text-base leading-7 text-white/70 sm:text-lg sm:leading-8">
              Upload FTRunner batches, isolate failed units, and compare yield signals without leaving the browser.
            </p>
            <div className="relative mt-10 hidden h-72 max-w-md sm:block">
            <div className="absolute inset-6 rounded-full border border-dashed border-accent/30 animate-rotate-slow" />
            <Card className="absolute left-0 top-6 w-56 p-5 animate-float">
              <div className="font-mono text-xs uppercase tracking-[0.15em] text-muted">First-pass yield</div>
                <div className="mt-2 text-4xl font-semibold gradient-text">78.65%</div>
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
        </div>

        <div className="relative z-10 flex w-full items-center p-6 sm:p-8 md:p-10">
          <div className="w-full max-w-md md:mx-auto">
          <div className="flex items-start gap-4 border-b border-border pb-6">
            <IconWell className="h-12 w-12 shrink-0">
              <span className="text-sm font-bold">CT</span>
            </IconWell>
            <div>
              <h2 className="text-2xl font-semibold tracking-tight text-foreground">Co_Trace</h2>
              <p className="mt-1 text-sm text-muted">Sign in to the manufacturing intelligence workspace.</p>
            </div>
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
          </div>
        </div>
      </div>
    </div>
  )
}
