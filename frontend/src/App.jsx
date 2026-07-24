import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { AuthProvider, useAuth } from './auth'
import Login from './pages/Login'
import Home from './pages/Home'
import Engineer from './pages/Engineer'
import Manager from './pages/Manager'
import About from './pages/About'
import { debugLog, log } from './logger'

const TABS = [
  ['home', 'Home'],
  ['engineer', 'Engineer'],
  ['manager', 'Manager'],
  ['about', 'About'],
]

function relPath(file) {
  return file.webkitRelativePath || file.name
}

function Shell() {
  const { isAuthed, username, logout } = useAuth()
  const [theme, setTheme] = useState(() => localStorage.getItem('cotrace-theme') || 'light')
  const [tab, setTab] = useState('home')
  const [jobId, setJobId] = useState(null)
  const [activeJobId, setActiveJobId] = useState(null)
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchProgress, setBatchProgress] = useState(null)
  const [batchError, setBatchError] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [warnings, setWarnings] = useState([])
  const [llmMetrics, setLlmMetrics] = useState(null)
  const [selectedFiles, setSelectedFiles] = useState([])
  const runToken = useRef(0)
  const uploadAbort = useRef(null)

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.style.colorScheme = theme
    localStorage.setItem('cotrace-theme', theme)
  }, [theme])

  if (!isAuthed) return <Login />

  const toggleTheme = () => setTheme((current) => (current === 'dark' ? 'light' : 'dark'))

  const onJobReady = (id, jobWarnings = []) => {
    setJobId(id)
    setWarnings(jobWarnings)
    setTab('engineer')
    log('info', 'Job ready', { jobId: id, warningCount: jobWarnings.length })
  }

  const startBatch = async (files) => {
    const token = runToken.current + 1
    runToken.current = token
    setBatchRunning(true)
    setBatchError('')
    setWarnings([])
    setLlmMetrics(null)
    setActiveJobId(null)
    setBatchProgress({ status: 'uploading', processed: 0, total: files.length, message: 'Uploading files' })
    const controller = new AbortController()
    uploadAbort.current = controller
    try {
      const formData = new FormData()
      for (const file of files) {
        formData.append('files', file)
        formData.append('paths', relPath(file))
      }
      const { job_id } = await api.upload(formData, { signal: controller.signal })
      if (runToken.current !== token) return
      uploadAbort.current = null
      setActiveJobId(job_id)
      await pollBatch(job_id, token)
    } catch (err) {
      if (runToken.current !== token) return
      const stopped = err.name === 'AbortError'
      setBatchError(stopped ? '' : err.message)
      setBatchProgress((current) => ({
        ...(current || {}),
        status: stopped ? 'cancelled' : 'error',
        message: stopped ? 'Batch stopped by user' : err.message,
      }))
      setBatchRunning(false)
      uploadAbort.current = null
    }
  }

  const pollBatch = async (id, token) => {
    while (runToken.current === token) {
      const status = await api.status(id)
      if (runToken.current !== token) return
      setBatchProgress({
        status: status.status,
        processed: status.progress.processed,
        total: status.progress.total,
        message: status.message,
      })
      setLlmMetrics(status.llm_metrics || null)
      if (status.status === 'done') {
        setBatchRunning(false)
        onJobReady(id, status.warnings || [])
        return
      }
      if (status.status === 'error' || status.status === 'cancelled') {
        setBatchRunning(false)
        setBatchError(status.status === 'cancelled' ? '' : status.message)
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 700))
    }
  }

  const stopBatch = async () => {
    const id = activeJobId
    setBatchProgress((current) => ({
      ...(current || {}),
      message: id ? 'Stopping batch after the current step' : 'Stopping upload',
    }))
    if (!id) {
      runToken.current += 1
      uploadAbort.current?.abort()
      uploadAbort.current = null
      setBatchRunning(false)
      setBatchProgress({ status: 'cancelled', processed: 0, total: 1, message: 'Batch stopped by user' })
      return
    }
    try {
      await api.stop(id)
    } catch (err) {
      setBatchError(err.message)
    }
  }

  const NavButton = ({ id, label }) => {
    const selected = tab === id
    return (
      <button
        onClick={() => {
          debugLog('Tab changed', { tab: id })
          setTab(id)
          setMenuOpen(false)
        }}
        aria-current={selected ? 'page' : undefined}
        className={[
          'rounded-lg px-4 py-2 text-sm font-medium transition-colors duration-150 focus-ring',
          selected ? 'bg-accent/10 text-accent' : 'text-muted hover:text-ink hover:bg-surface-2',
        ].join(' ')}
      >
        {label}
      </button>
    )
  }

  const ThemeSwitch = ({ className = '' }) => {
    const dark = theme === 'dark'
    return (
      <button
        type="button"
        role="switch"
        aria-checked={dark}
        aria-label={`Switch to ${dark ? 'light' : 'dark'} mode`}
        onClick={toggleTheme}
        className={[
          'flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-ink focus-ring',
          className,
        ].join(' ')}
      >
        <span className="relative h-5 w-9 shrink-0 rounded-full bg-surface-2 border border-border">
          <span
            className={[
              'absolute left-0.5 top-0.5 h-3.5 w-3.5 rounded-full bg-accent transition-transform duration-200',
              dark ? 'translate-x-4' : 'translate-x-0',
            ].join(' ')}
          />
        </span>
        <span>{dark ? 'Dark' : 'Light'}</span>
      </button>
    )
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-20 border-b border-border bg-surface/80 backdrop-blur">
        <div className="mx-auto max-w-7xl px-6">
          <div className="flex h-16 items-center justify-between gap-4">
            <div className="flex items-center gap-3">
              <div className="flex h-9 w-9 items-center justify-center rounded-lg bg-accent">
                <span className="font-display text-sm font-extrabold text-white">CT</span>
              </div>
              <span className="font-display font-bold text-ink hidden sm:block">Co-Trace</span>
            </div>

            <nav className="hidden md:flex items-center gap-1">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
            </nav>

            <div className="hidden md:flex items-center gap-3">
              <ThemeSwitch />
              {batchRunning && (
                <button
                  onClick={stopBatch}
                  className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-danger transition-colors duration-150 hover:border-danger hover:bg-danger/5 focus-ring"
                >
                  Stop batch
                </button>
              )}
              <span className="text-sm text-muted">{username || 'user'}</span>
              <button
                onClick={logout}
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-ink focus-ring"
              >
                Sign out
              </button>
            </div>

            <button
              className="md:hidden flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-surface text-ink focus-ring"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
            >
              {menuOpen ? '✕' : '☰'}
            </button>
          </div>

          {menuOpen && (
            <div className="md:hidden mb-3 rounded-panel border border-border bg-surface shadow-md p-4 flex flex-col gap-2">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
              {batchRunning && (
                <button
                  onClick={stopBatch}
                  className="rounded-lg border border-border bg-surface px-4 py-2.5 text-sm text-danger focus-ring"
                >
                  Stop batch
                </button>
              )}
              <ThemeSwitch className="justify-center" />
              <button
                onClick={logout}
                className="rounded-lg border border-border bg-surface px-4 py-2.5 text-sm text-muted focus-ring"
              >
                Sign out ({username || 'user'})
              </button>
            </div>
          )}
        </div>

        {warnings.length > 0 && (
          <div className="mx-auto max-w-7xl px-6 py-3">
            <div className="rounded-panel border border-warning/30 bg-warning/10 px-4 py-3 flex items-start justify-between gap-4">
              <div className="text-sm text-warning">
                <span className="font-semibold">{warnings.length} folder{warnings.length === 1 ? '' : 's'} skipped:</span>{' '}
                no ftrunnerlog01.txt or debuglog.txt found. These runs were excluded from the results.
                <ul className="mt-1 list-disc list-inside text-xs text-warning/80 max-h-24 overflow-auto">
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
              <button
                className="text-xs text-muted hover:text-ink focus-ring rounded-md px-2 py-1 shrink-0"
                onClick={() => setWarnings([])}
              >
                Dismiss
              </button>
            </div>
          </div>
        )}
      </header>

      <main>
        {tab === 'home' && (
          <Home
            onStartBatch={startBatch}
            onStopBatch={stopBatch}
            processing={batchRunning}
            progress={batchProgress}
            batchError={batchError}
            llmMetrics={llmMetrics}
            files={selectedFiles}
            setFiles={setSelectedFiles}
          />
        )}
        {tab === 'engineer' && <Engineer jobId={jobId} />}
        {tab === 'manager' && <Manager jobId={jobId} />}
        {tab === 'about' && <About />}
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
