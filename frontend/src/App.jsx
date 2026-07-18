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
        'w-full rounded-lg px-3 py-2.5 text-left text-sm font-semibold transition-all duration-200 focus-ring',
        tab === id
          ? 'bg-accent text-white shadow-accent'
          : 'text-slate-300 hover:bg-white/10 hover:text-white',
      ].join(' ')}
    >
      {label}
    </button>
  )

  return (
    <div className="min-h-screen bg-background text-foreground lg:flex">
      <aside className="hidden min-h-screen w-72 shrink-0 border-r border-slate-800 bg-foreground p-5 text-white lg:sticky lg:top-0 lg:flex lg:flex-col">
        <div className="flex items-center gap-3 border-b border-white/10 pb-5">
          <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-secondary text-white">
            <span className="text-sm font-bold">CT</span>
          </div>
          <div>
                <div className="text-base font-semibold">Co_Trace</div>
            <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-slate-400">Manufacturing intelligence</div>
          </div>
        </div>

        <nav className="mt-6 space-y-2">
          {TABS.map(([id, label]) => (
            <NavButton key={id} id={id} label={label} />
          ))}
        </nav>

        <div className="mt-auto rounded-card border border-white/10 bg-white/5 p-4">
          <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-slate-400">Signed in</div>
          <div className="mt-1 text-sm font-semibold text-white">{username || 'user'}</div>
          <button
            onClick={logout}
            className="mt-4 w-full rounded-lg border border-white/10 px-3 py-2 text-sm font-semibold text-slate-300 transition hover:bg-white/10 hover:text-white focus-ring"
          >
            Sign out
          </button>
        </div>
      </aside>

      <div className="min-w-0 flex-1">
        <header className="sticky top-0 z-20 border-b border-border/70 bg-background/90 backdrop-blur-xl lg:hidden">
          <div className="px-4 py-3 sm:px-6">
            <div className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-secondary text-white">
                <span className="text-sm font-bold">CT</span>
              </div>
              <div className="hidden sm:block">
                <div className="text-base font-semibold text-foreground">Co_Trace</div>
                <div className="font-mono text-[10px] uppercase tracking-[0.15em] text-muted">Manufacturing intelligence</div>
              </div>
            </div>

            <button
              className="flex h-11 w-11 items-center justify-center rounded-lg border border-border bg-card text-foreground shadow-soft focus-ring"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
            >
              {menuOpen ? '✕' : '☰'}
            </button>
          </div>

          {menuOpen && (
            <div className="mt-3 flex flex-col gap-3 rounded-card border border-border bg-foreground p-4 shadow-lift">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
              <button
                onClick={logout}
                className="rounded-lg border border-white/10 px-4 py-2.5 text-sm font-semibold text-slate-300 focus-ring"
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
