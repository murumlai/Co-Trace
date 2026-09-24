import { useEffect, useRef, useState } from 'react'
import { api } from './api'
import { AuthProvider, useAuth } from './auth'
import AdminDialog from './components/AdminDialog'
import Home from './pages/Home'
import Engineer from './pages/Engineer'
import Manager from './pages/Manager'
import Knowledge from './pages/Knowledge'
import About from './pages/About'
import RecentBatches from './components/RecentBatches'
import { debugLog, log } from './logger'
import { monitorJob } from './jobMonitoring'
import {
  DEFAULT_ENGINEER_VIEW_STATE,
  DEFAULT_MANAGER_SCOPE,
  loadWorkspaceState,
  resolveDrillDownSelection,
  saveWorkspaceState,
  workspaceSearch,
} from './workspaceState'

const TABS = [
  ['home', 'Home'],
  ['engineer', 'Engineer'],
  ['manager', 'Manager'],
  ['knowledge', 'Knowledge'],
  ['about', 'About'],
]

function relPath(file) {
  return file.webkitRelativePath || file.name
}

const preferredViewKey = (username) => `cotrace-results-view:${String(username || '').toLocaleLowerCase()}`

function Shell() {
  const { checking, isAuthed, workspaceId: username, isAdmin, logout, notice, clearNotice } = useAuth()
  const [theme, setTheme] = useState(() => localStorage.getItem('cotrace-theme') || 'light')
  const [tab, setTab] = useState('home')
  const [jobId, setJobId] = useState(null)
  const [restoreCandidateId, setRestoreCandidateId] = useState(null)
  const [workspaceReady, setWorkspaceReady] = useState(false)
  const [restoringWorkspace, setRestoringWorkspace] = useState(false)
  const [workspaceError, setWorkspaceError] = useState('')
  const [activeJobId, setActiveJobId] = useState(null)
  const [batchRunning, setBatchRunning] = useState(false)
  const [batchProgress, setBatchProgress] = useState(null)
  const [batchError, setBatchError] = useState('')
  const [engineerDrillDown, setEngineerDrillDown] = useState(null)
  const [engineerViewState, setEngineerViewState] = useState({ ...DEFAULT_ENGINEER_VIEW_STATE })
  const [engineerFeedbackDrafts, setEngineerFeedbackDrafts] = useState({})
  const [engineerActionDrafts, setEngineerActionDrafts] = useState({})
  const [managerScope, setManagerScope] = useState({ ...DEFAULT_MANAGER_SCOPE })
  const [knowledgeReview, setKnowledgeReview] = useState(null)
  const [menuOpen, setMenuOpen] = useState(false)
  const [adminOpen, setAdminOpen] = useState(false)
  const [adminError, setAdminError] = useState('')
  const [leavingAdmin, setLeavingAdmin] = useState(false)
  const [warnings, setWarnings] = useState([])
  const [llmMetrics, setLlmMetrics] = useState(null)
  const [selectedFiles, setSelectedFiles] = useState([])
  const [recentJobs, setRecentJobs] = useState([])
  const [recentJobsCursor, setRecentJobsCursor] = useState(null)
  const [recentJobsLoading, setRecentJobsLoading] = useState(false)
  const [recentJobsError, setRecentJobsError] = useState('')
  const [preferredResultsView, setPreferredResultsView] = useState('engineer')
  const runToken = useRef(0)
  const uploadAbort = useRef(null)
  const workspaceOwner = useRef(null)
  const recentJobsRequest = useRef(0)

  useEffect(() => {
    const root = document.documentElement
    root.dataset.theme = theme
    root.style.colorScheme = theme
    localStorage.setItem('cotrace-theme', theme)
  }, [theme])

  useEffect(() => {
    const hasDrafts = Object.values(engineerFeedbackDrafts).some((value) => value.trim()) || Object.keys(engineerActionDrafts).length > 0
    if (!hasDrafts) return undefined
    const warnBeforeUnload = (event) => {
      event.preventDefault()
      event.returnValue = ''
    }
    window.addEventListener('beforeunload', warnBeforeUnload)
    return () => window.removeEventListener('beforeunload', warnBeforeUnload)
  }, [engineerActionDrafts, engineerFeedbackDrafts])

  useEffect(() => {
    if (!menuOpen || adminOpen) return undefined
    const closeOnEscape = (event) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [menuOpen, adminOpen])

  useEffect(() => {
    if (checking) return
    if (!isAuthed || !username) {
      workspaceOwner.current = null
      setWorkspaceReady(true)
      return
    }
    if (workspaceOwner.current === username) return
    workspaceOwner.current = username
    const savedView = localStorage.getItem(preferredViewKey(username))
    setPreferredResultsView(savedView === 'manager' ? 'manager' : 'engineer')
    const restored = loadWorkspaceState(sessionStorage, username, window.location.search)
    if (!window.location.search) {
      restored.tab = 'home'
      restored.jobId = null
      restored.drillDown = null
      restored.engineer = { ...DEFAULT_ENGINEER_VIEW_STATE }
      restored.managerScope = { ...DEFAULT_MANAGER_SCOPE }
    }
    setTab(restored.tab)
    setEngineerViewState(restored.engineer)
    setManagerScope(restored.managerScope)
    setEngineerDrillDown(restored.drillDown)
    setRestoreCandidateId(restored.jobId)
    setWorkspaceReady(true)
    if (restored.jobId) restoreWorkspaceJob(restored.jobId)
    loadRecentJobs({ replace: true })
  }, [checking, isAuthed, username])

  useEffect(() => {
    if (!workspaceReady || !isAuthed || !username || restoringWorkspace) return
    const workspace = {
      tab,
      jobId: jobId || activeJobId || restoreCandidateId,
      engineer: engineerViewState,
      managerScope,
      drillDown: engineerDrillDown,
    }
    saveWorkspaceState(sessionStorage, username, workspace)
    const search = workspaceSearch(workspace, window.location.search)
    window.history.replaceState(null, '', `${window.location.pathname}${search}${window.location.hash}`)
  }, [activeJobId, engineerDrillDown, engineerViewState, isAuthed, jobId, managerScope, restoreCandidateId, restoringWorkspace, tab, username, workspaceReady])

  const drillDownDescriptorKey = JSON.stringify({
    attempt_id: engineerDrillDown?.attempt_id,
    signature: engineerDrillDown?.signature,
    station_id: engineerDrillDown?.station_id,
    host: engineerDrillDown?.host,
    lot_id: engineerDrillDown?.lot_id,
    exact: engineerDrillDown?.exact,
  })
  const managerScopeKey = JSON.stringify(managerScope)

  useEffect(() => {
    if (!jobId || !engineerDrillDown || engineerDrillDown.exact) return undefined
    if (engineerDrillDown.attempt_ids?.length || engineerDrillDown.unit_ids?.length) return undefined
    let active = true
    const descriptor = engineerDrillDown

    if (descriptor.attempt_id) {
      setEngineerDrillDown(resolveDrillDownSelection(null, descriptor))
      return undefined
    }

    api.manager(jobId, managerScope).then(
      (data) => {
        if (active) setEngineerDrillDown(resolveDrillDownSelection(data, descriptor))
      },
      (error) => {
        if (!active) return
        setEngineerDrillDown({
          ...resolveDrillDownSelection(null, descriptor),
          selection_error: error.message,
        })
      },
    )
    return () => {
      active = false
    }
  }, [drillDownDescriptorKey, jobId, managerScopeKey])

  useEffect(() => {
    if (!workspaceReady || !isAuthed || !username) return undefined
    const onPopState = () => {
      const restored = loadWorkspaceState(sessionStorage, username, window.location.search, { navigation: true })
      setTab(restored.tab)
      setEngineerViewState((current) => ({ ...current, ...restored.engineer }))
      setManagerScope(restored.managerScope)
      setEngineerDrillDown(restored.drillDown)
      const currentJobId = jobId || restoreCandidateId
      if (restored.jobId && restored.jobId !== currentJobId) {
        setRestoreCandidateId(restored.jobId)
        restoreWorkspaceJob(restored.jobId)
      } else if (!restored.jobId && currentJobId) {
        runToken.current += 1
        setJobId(null)
        setActiveJobId(null)
        setRestoreCandidateId(null)
        setBatchRunning(false)
        setBatchProgress(null)
        setWorkspaceError('')
        setWarnings([])
        setEngineerFeedbackDrafts({})
      }
    }
    window.addEventListener('popstate', onPopState)
    return () => window.removeEventListener('popstate', onPopState)
  }, [isAuthed, jobId, restoreCandidateId, username, workspaceReady])

  const toggleTheme = () => setTheme((current) => (current === 'dark' ? 'light' : 'dark'))

  const onJobReady = (id, jobWarnings = []) => {
    setJobId(id)
    setActiveJobId(null)
    setRestoreCandidateId(null)
    setWorkspaceError('')
    setEngineerDrillDown(null)
    setEngineerViewState({ ...DEFAULT_ENGINEER_VIEW_STATE })
    setEngineerFeedbackDrafts({})
    setEngineerActionDrafts({})
    setManagerScope({ ...DEFAULT_MANAGER_SCOPE })
    setWarnings(jobWarnings)
    setTab(preferredResultsView)
    loadRecentJobs({ replace: true })
    log('info', 'Job ready', { jobId: id, warningCount: jobWarnings.length })
  }

  const startBatch = async (files, options = {}) => {
    if (
      (Object.values(engineerFeedbackDrafts).some((value) => value.trim()) || Object.keys(engineerActionDrafts).length > 0) &&
      !window.confirm('Start a new batch and discard unsaved feedback or action edits?')
    ) return
    const token = runToken.current + 1
    runToken.current = token
    setBatchRunning(true)
    setBatchError('')
    setWorkspaceError('')
    setRestoreCandidateId(null)
    setWarnings([])
    setLlmMetrics(null)
    setActiveJobId(null)
    setBatchProgress({ status: 'uploading', stage: 'uploading', processed: 0, total: files.length, message: 'Uploading files' })
    const controller = new AbortController()
    uploadAbort.current = controller
    try {
      const formData = new FormData()
      files.forEach((file, i) => {
        formData.append('files', file)
        // webkitRelativePath is set by the folder picker and already encodes
        // the subfolder hierarchy. Individual file picks leave it empty, so
        // every .txt would get the same flat path and the backend would overwrite
        // them — assign a synthetic unique folder per file.
        // .zip files must stay flat (no subfolder) so the backend's _is_root_zip
        // check recognises them as batch containers to extract.
        const isZip = file.name.toLowerCase().endsWith('.zip')
        const path = file.webkitRelativePath || (isZip ? file.name : `run_${i}/${file.name}`)
        formData.append('paths', path)
      })
      formData.append('force_refresh', options.forceRefresh ? 'true' : 'false')
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
        stage: stopped ? 'cancelled' : 'error',
        message: stopped ? 'Batch stopped by user' : err.message,
      }))
      setBatchRunning(false)
      uploadAbort.current = null
    }
  }

  async function pollBatch(id, token, openResults = true) {
    const result = await monitorJob({
      jobId: id,
      getStatus: api.status,
      isCurrent: () => runToken.current === token,
      onStatus: (status) => {
      setBatchProgress({
        status: status.status,
        stage: status.progress.stage,
        processed: status.progress.processed,
        total: status.progress.total,
        message: status.message,
        elapsed_s: status.elapsed_s || 0,
      })
      setLlmMetrics(status.llm_metrics || null)
      },
      onReconnect: ({ attempt, maxAttempts }) => {
        setBatchProgress((current) => ({
          ...(current || {}),
          message: `Connection interrupted. Reconnecting (${attempt}/${maxAttempts - 1})`,
        }))
      },
    })

    if (result.kind === 'stale') return
    setBatchRunning(false)
    if (result.kind === 'done') {
      if (openResults) {
        onJobReady(id, result.status.warnings || [])
      } else {
        setJobId(id)
        setActiveJobId(null)
        setRestoreCandidateId(null)
        setWarnings(result.status.warnings || [])
      }
      return
    }
    if (result.kind === 'error' || result.kind === 'cancelled') {
      setBatchError(result.kind === 'cancelled' ? '' : result.status.message)
      return
    }
    if (result.kind === 'paused') {
      setBatchError(`Status monitoring paused: ${result.error.message}. The server job may still be running.`)
      setBatchProgress((current) => ({
        ...(current || {}),
        status: 'monitoring_error',
        stage: 'monitoring_error',
        message: 'Status monitoring paused',
      }))
    }
  }

  async function restoreWorkspaceJob(id) {
    const token = runToken.current + 1
    runToken.current = token
    setRestoringWorkspace(true)
    setWorkspaceError('')
    try {
      const status = await api.status(id)
      if (runToken.current !== token) return
      setBatchProgress({
        status: status.status,
        stage: status.progress.stage,
        processed: status.progress.processed,
        total: status.progress.total,
        message: status.message,
        elapsed_s: status.elapsed_s || 0,
      })
      setLlmMetrics(status.llm_metrics || null)
      if (status.status === 'done') {
        setJobId(id)
        setRestoreCandidateId(null)
        setWarnings(status.warnings || [])
        return
      }
      if (status.status === 'pending' || status.status === 'running') {
        setActiveJobId(id)
        setBatchRunning(true)
        setRestoringWorkspace(false)
        await pollBatch(id, token, false)
        return
      }
      setWorkspaceError(`Saved batch is ${status.status}. Start a new batch or retry if its state has changed.`)
    } catch (error) {
      if (runToken.current !== token) return
      const prefix = error.status === 404 ? 'Saved batch is no longer available' : 'Could not restore the saved batch'
      setWorkspaceError(`${prefix}: ${error.message}`)
    } finally {
      if (runToken.current === token) setRestoringWorkspace(false)
    }
  }

  const resumeBatch = async () => {
    if (!activeJobId) return
    const token = runToken.current + 1
    runToken.current = token
    setBatchRunning(true)
    setBatchError('')
    setBatchProgress((current) => ({
      ...(current || {}),
      status: 'running',
      message: 'Reconnecting to the existing batch',
    }))
    await pollBatch(activeJobId, token)
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
      setBatchProgress({ status: 'cancelled', stage: 'cancelled', processed: 0, total: 1, message: 'Batch stopped by user' })
      return
    }
    try {
      await api.stop(id)
      if (!batchRunning) await resumeBatch()
    } catch (err) {
      setBatchError(err.message)
    }
  }

  const openEngineerDrillDown = (filter) => {
    setEngineerDrillDown(filter)
    navigateToTab('engineer', { drillDown: filter })
    setMenuOpen(false)
  }

  const openKnowledgeReview = (filter) => {
    setKnowledgeReview(filter)
    navigateToTab('knowledge')
    setMenuOpen(false)
  }

  async function loadRecentJobs({ replace = false } = {}) {
    if (!username) return
    const request = ++recentJobsRequest.current
    setRecentJobsLoading(true)
    setRecentJobsError('')
    try {
      const response = await api.jobs({ cursor: replace ? null : recentJobsCursor })
      if (request !== recentJobsRequest.current) return
      setRecentJobs((current) => replace ? response.items : [...current, ...response.items])
      setRecentJobsCursor(response.next_cursor || null)
    } catch (error) {
      if (request === recentJobsRequest.current) setRecentJobsError(error.message)
    } finally {
      if (request === recentJobsRequest.current) setRecentJobsLoading(false)
    }
  }

  const setResultsViewPreference = (nextView) => {
    const value = nextView === 'manager' ? 'manager' : 'engineer'
    setPreferredResultsView(value)
    localStorage.setItem(preferredViewKey(username), value)
  }

  const openRecentJob = async (job) => {
    setEngineerDrillDown(null)
    setEngineerViewState({ ...DEFAULT_ENGINEER_VIEW_STATE })
    setEngineerFeedbackDrafts({})
    setManagerScope({ ...DEFAULT_MANAGER_SCOPE })
    setRestoreCandidateId(job.job_id)
    navigateToTab(preferredResultsView, {
      jobId: job.job_id,
      drillDown: null,
      engineer: DEFAULT_ENGINEER_VIEW_STATE,
      managerScope: DEFAULT_MANAGER_SCOPE,
    })
    await restoreWorkspaceJob(job.job_id)
  }

  const workspaceSnapshot = (overrides = {}) => ({
    tab,
    jobId: jobId || activeJobId || restoreCandidateId,
    engineer: engineerViewState,
    managerScope,
    drillDown: engineerDrillDown,
    ...overrides,
  })

  const navigateToTab = (nextTab, overrides = {}) => {
    const workspace = workspaceSnapshot({ tab: nextTab, ...overrides })
    const search = workspaceSearch(workspace, window.location.search)
    window.history.pushState(null, '', `${window.location.pathname}${search}${window.location.hash}`)
    setTab(nextTab)
  }

  const clearRestoredWorkspace = () => {
    if (
      (Object.values(engineerFeedbackDrafts).some((value) => value.trim()) || Object.keys(engineerActionDrafts).length > 0) &&
      !window.confirm('Start a new batch and discard unsaved feedback or action edits?')
    ) return
    runToken.current += 1
    setJobId(null)
    setActiveJobId(null)
    setRestoreCandidateId(null)
    setWorkspaceError('')
    setBatchRunning(false)
    setBatchProgress(null)
    setWarnings([])
    setEngineerDrillDown(null)
    setEngineerViewState({ ...DEFAULT_ENGINEER_VIEW_STATE })
    setEngineerFeedbackDrafts({})
    setEngineerActionDrafts({})
    setManagerScope({ ...DEFAULT_MANAGER_SCOPE })
    navigateToTab('home', {
      jobId: null,
      drillDown: null,
      engineer: DEFAULT_ENGINEER_VIEW_STATE,
      managerScope: DEFAULT_MANAGER_SCOPE,
    })
  }

  const toggleAdmin = async () => {
    setAdminError('')
    if (!isAdmin) {
      setAdminOpen(true)
      return
    }
    setLeavingAdmin(true)
    try {
      await logout()
    } catch {
      setAdminError('Could not exit Admin mode. Check the connection and try Exit Admin again.')
    } finally {
      setLeavingAdmin(false)
    }
  }

  const NavButton = ({ id, label }) => {
    const selected = tab === id
    return (
      <button
        onClick={() => {
          debugLog('Tab changed', { tab: id })
          navigateToTab(id)
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

  const monitoringPaused = batchProgress?.status === 'monitoring_error' && !!activeJobId
  const recentBatchProps = {
    jobs: recentJobs,
    activeJobId: jobId || activeJobId || restoreCandidateId,
    loading: recentJobsLoading,
    error: recentJobsError,
    hasMore: !!recentJobsCursor,
    preferredView: preferredResultsView,
    onPreferredViewChange: setResultsViewPreference,
    onOpen: openRecentJob,
    onNew: clearRestoredWorkspace,
    onRefresh: () => loadRecentJobs({ replace: true }),
    onLoadMore: () => loadRecentJobs(),
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

            <nav className="hidden lg:flex items-center gap-1">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
            </nav>

            <div className="hidden lg:flex items-center gap-3">
              <RecentBatches {...recentBatchProps} />
              <ThemeSwitch />
              {(batchRunning || monitoringPaused) && (
                <button
                  onClick={stopBatch}
                  className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-danger transition-colors duration-150 hover:border-danger hover:bg-danger/5 focus-ring"
                >
                  Stop batch
                </button>
              )}
              <button
                onClick={toggleAdmin}
                disabled={checking || leavingAdmin}
                className="rounded-lg border border-border bg-surface px-3 py-2 text-sm text-muted transition-colors duration-150 hover:bg-surface-2 hover:text-ink focus-ring"
              >
                {isAdmin ? 'Exit Admin' : 'Admin'}
              </button>
            </div>

            <button
              className="lg:hidden flex h-10 w-10 items-center justify-center rounded-lg border border-border bg-surface text-ink focus-ring"
              onClick={() => setMenuOpen((o) => !o)}
              aria-label="Toggle menu"
              aria-expanded={menuOpen}
              aria-controls="mobile-navigation"
            >
              {menuOpen ? '✕' : '☰'}
            </button>
          </div>

          {menuOpen && (
            <div id="mobile-navigation" className="lg:hidden mb-3 rounded-panel border border-border bg-surface shadow-md p-4 flex flex-col gap-2">
              {TABS.map(([id, label]) => (
                <NavButton key={id} id={id} label={label} />
              ))}
              <RecentBatches {...recentBatchProps} mobile />
              {(batchRunning || monitoringPaused) && (
                <button
                  onClick={stopBatch}
                  className="rounded-lg border border-border bg-surface px-4 py-2.5 text-sm text-danger focus-ring"
                >
                  Stop batch
                </button>
              )}
              <ThemeSwitch className="justify-center" />
              <button
                onClick={toggleAdmin}
                disabled={checking || leavingAdmin}
                className="rounded-lg border border-border bg-surface px-4 py-2.5 text-sm text-muted focus-ring"
              >
                {isAdmin ? 'Exit Admin' : 'Admin'}
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

        {(restoringWorkspace || workspaceError) && (
          <div className="mx-auto max-w-7xl px-6 py-3">
            <div role={workspaceError ? 'alert' : 'status'} className="flex flex-wrap items-center justify-between gap-3 rounded-panel border border-warning/30 bg-warning/10 px-4 py-3">
              <div>
                <p className="text-sm font-semibold text-warning">
                  {restoringWorkspace ? 'Restoring saved batch' : 'Saved batch unavailable'}
                </p>
                {workspaceError && <p className="mt-0.5 text-xs text-muted">{workspaceError}</p>}
              </div>
              {workspaceError && (
                <div className="flex gap-2">
                  <button className="rounded-lg px-3 py-1.5 text-sm text-accent hover:bg-accent/10 focus-ring" onClick={() => restoreWorkspaceJob(restoreCandidateId)}>Retry</button>
                  <button className="rounded-lg px-3 py-1.5 text-sm text-muted hover:bg-surface-2 focus-ring" onClick={clearRestoredWorkspace}>New batch</button>
                </div>
              )}
            </div>
          </div>
        )}
      </header>

      {(notice || adminError) && (
        <div role="status" className="mx-auto flex max-w-7xl items-center justify-between gap-3 px-6 py-3 text-sm text-warning">
          <span>{adminError || notice}</span>
          <button className="focus-ring rounded-md px-2 py-1" onClick={() => { clearNotice(); setAdminError('') }}>Dismiss</button>
        </div>
      )}
      {adminOpen && <AdminDialog onClose={() => setAdminOpen(false)} />}

      <main>
        {tab === 'home' && (
          <Home
            onStartBatch={startBatch}
            onStopBatch={stopBatch}
            onResumeBatch={resumeBatch}
            processing={batchRunning}
            monitoringPaused={monitoringPaused}
            progress={batchProgress}
            batchError={batchError}
            llmMetrics={llmMetrics}
            files={selectedFiles}
            setFiles={setSelectedFiles}
          />
        )}
        {tab === 'engineer' && (
          <Engineer
            jobId={jobId}
            drillDown={engineerDrillDown}
            onClearDrillDown={() => setEngineerDrillDown(null)}
            onReturnToManager={() => navigateToTab('manager')}
            onReviewKnowledge={openKnowledgeReview}
            initialViewState={engineerViewState}
            onViewStateChange={setEngineerViewState}
            feedbackDrafts={engineerFeedbackDrafts}
            onFeedbackDraftsChange={setEngineerFeedbackDrafts}
            actionDrafts={engineerActionDrafts}
            onActionDraftsChange={setEngineerActionDrafts}
          />
        )}
        {tab === 'manager' && (
          <Manager
            jobId={jobId}
            onDrillDown={openEngineerDrillDown}
            scope={managerScope}
            onScopeChange={setManagerScope}
          />
        )}
        {tab === 'knowledge' && (
          <Knowledge
            jobId={jobId}
            reviewFilter={knowledgeReview}
            onClearReview={() => setKnowledgeReview(null)}
          />
        )}
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
