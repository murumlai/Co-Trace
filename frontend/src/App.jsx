import { useRef, useState } from 'react'
import { api } from './api'
import { AuthProvider, useAuth } from './auth'
import Login from './pages/Login'
import Home from './pages/Home'
import Engineer from './pages/Engineer'
import Manager from './pages/Manager'
import { debugLog, log } from './logger'

const TABS = [
  ['home', 'Home'],
  ['engineer', 'Engineer'],
  ['manager', 'Manager'],
]

function relPath(file) {
  return file.webkitRelativePath || file.name
}

function Shell() {
  const { isAuthed, username, logout } = useAuth()
  const [tab, setTab] = useState('home')
  const [jobId, setJobId] = useState(null)
  const [activeJobId, setActiveJobId] = useState(null)
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchProgress, setBatchProgress] = useState(null)
  const [batchError, setBatchError] = useState('')
  const [menuOpen, setMenuOpen] = useState(false)
  const [warnings, setWarnings] = useState([])
  const runToken = useRef(0)
  const uploadAbort = useRef(null)

  if (!isAuthed) return <Login />

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

  const NavButton = ({ id, label }) => (
    <button
      onClick={() => {
        debugLog('Tab changed', { tab: id })
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
              {batchRunning && (
                <button
                  onClick={stopBatch}
                  className="rounded-2xl bg-base px-4 py-2 text-sm text-danger shadow-extruded-sm hover:-translate-y-px transition-all duration-300 focus-ring"
                >
                  Stop batch
                </button>
              )}
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
              {batchRunning && (
                <button
                  onClick={stopBatch}
                  className="rounded-2xl bg-base px-4 py-2.5 text-sm text-danger shadow-inset-sm focus-ring"
                >
                  Stop batch
                </button>
              )}
              <button
                onClick={logout}
                className="rounded-2xl bg-base px-4 py-2.5 text-sm text-muted shadow-inset-sm focus-ring"
              >
                Sign out ({username || 'user'})
              </button>
            </div>
          )}
        </div>

        {warnings.length > 0 && (
          <div className="mx-auto max-w-7xl px-6 pt-4">
            <div className="rounded-card bg-base shadow-inset-sm px-5 py-3 flex items-start justify-between gap-4">
              <div className="text-sm text-amber-700">
                <span className="font-semibold">{warnings.length} folder{warnings.length === 1 ? '' : 's'} skipped:</span>{' '}
                no ftrunnerlog01.txt or debuglog.txt found. These runs were excluded from the results.
                <ul className="mt-1 list-disc list-inside text-xs text-amber-600 max-h-24 overflow-auto">
                  {warnings.map((w) => (
                    <li key={w}>{w}</li>
                  ))}
                </ul>
              </div>
              <button
                className="text-xs text-muted hover:text-ink focus-ring rounded-lg px-2 py-1 shrink-0"
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
          />
        )}
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
