import { useState } from 'react'
import { AuthProvider, useAuth } from './auth'
import Login from './pages/Login'
import Home from './pages/Home'
import Engineer from './pages/Engineer'
import Manager from './pages/Manager'

const TABS = [
  ['home', 'Home'],
  ['engineer', 'Engineer'],
  ['manager', 'Manager'],
]

function Shell() {
  const { isAuthed, username, logout } = useAuth()
  const [tab, setTab] = useState('home')
  const [jobId, setJobId] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)

  if (!isAuthed) return <Login />

  const onJobReady = (id) => {
    setJobId(id)
    setTab('engineer')
  }

  const NavButton = ({ id, label }) => (
    <button
      onClick={() => {
        setTab(id)
        setMenuOpen(false)
      }}
      className={[
        'rounded-xl px-4 py-2.5 text-sm font-semibold transition-all duration-200 focus-ring',
        tab === id
          ? 'bg-accent text-white shadow-accent'
          : 'text-muted hover:bg-surface hover:text-foreground',
      ].join(' ')}
    >
      {label}
    </button>
  )

  return (
    <div className="min-h-screen overflow-hidden bg-background text-foreground">
      <header className="sticky top-0 z-20 border-b border-border/70 bg-background/85 backdrop-blur-xl">
        <div className="mx-auto max-w-7xl px-4 py-3 sm:px-6">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary text-white shadow-accent">
                <span className="font-display text-sm">CT</span>
              </div>
              <div className="hidden sm:block">
                <div className="font-display text-xl text-foreground">Co_Trace</div>
                <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted">Manufacturing intelligence</div>
              </div>
            </div>

            <nav className="hidden items-center gap-2 rounded-2xl border border-border bg-card p-1 shadow-soft md:flex">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
            </nav>

            <div className="hidden md:flex items-center gap-4">
              <span className="font-mono text-xs uppercase tracking-[0.15em] text-muted">{username || 'user'}</span>
              <button
                onClick={logout}
                className="rounded-xl border border-border bg-card px-4 py-2 text-sm font-semibold text-muted shadow-soft transition-all duration-200 hover:-translate-y-0.5 hover:text-foreground focus-ring"
              >
                Sign out
              </button>
            </div>

            <button
              className="flex h-11 w-11 items-center justify-center rounded-xl border border-border bg-card text-foreground shadow-soft focus-ring md:hidden"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
            >
              {menuOpen ? '✕' : '☰'}
            </button>
          </div>

          {menuOpen && (
            <div className="mt-3 flex flex-col gap-3 rounded-card border border-border bg-card p-4 shadow-lift md:hidden">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
              <button
                onClick={logout}
                className="rounded-xl border border-border px-4 py-2.5 text-sm font-semibold text-muted focus-ring"
              >
                Sign out ({username || 'user'})
              </button>
            </div>
          )}
        </div>
      </header>

      <main>
        {tab === 'home' && <Home onJobReady={onJobReady} />}
        {tab === 'engineer' && <Engineer jobId={jobId} />}
        {tab === 'manager' && <Manager jobId={jobId} />}
      </main>
    </div>
  )
}

export default function App() {
  return (
    <AuthProvider>
      <Shell />
    </AuthProvider>
  )
}
