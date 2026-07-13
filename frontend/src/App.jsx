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
        'rounded-2xl px-5 py-2.5 text-sm font-medium transition-all duration-300 focus-ring',
        tab === id
          ? 'bg-base text-accent shadow-inset'
          : 'bg-base text-muted shadow-extruded-sm hover:-translate-y-px',
      ].join(' ')}
    >
      {label}
    </button>
  )

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 backdrop-blur-sm">
        <div className="mx-auto max-w-7xl px-6 py-4">
          <div className="flex items-center justify-between rounded-card bg-base shadow-extruded px-5 py-3">
            <div className="flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-2xl bg-base shadow-inset-deep">
                <span className="font-display text-sm font-extrabold text-accent">CT</span>
              </div>
              <span className="font-display font-bold text-ink hidden sm:block">Co_Trace</span>
            </div>

            <nav className="hidden md:flex items-center gap-3">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
            </nav>

            <div className="hidden md:flex items-center gap-4">
              <span className="text-sm text-muted">{username || 'user'}</span>
              <button
                onClick={logout}
                className="rounded-2xl bg-base px-4 py-2 text-sm text-muted shadow-extruded-sm hover:-translate-y-px hover:text-ink transition-all duration-300 focus-ring"
              >
                Sign out
              </button>
            </div>

            <button
              className="md:hidden flex h-11 w-11 items-center justify-center rounded-2xl bg-base shadow-extruded-sm focus-ring"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
            >
              {menuOpen ? '✕' : '☰'}
            </button>
          </div>

          {menuOpen && (
            <div className="md:hidden mt-3 rounded-card bg-base shadow-extruded p-4 flex flex-col gap-3">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
              <button
                onClick={logout}
                className="rounded-2xl bg-base px-4 py-2.5 text-sm text-muted shadow-inset-sm focus-ring"
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
