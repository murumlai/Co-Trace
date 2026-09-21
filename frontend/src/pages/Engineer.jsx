import { Fragment, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import { groupAttempts } from '../unitAttempts'
import { DEFAULT_ENGINEER_VIEW_STATE } from '../workspaceState'
import {
  Badge,
  Button,
  Card,
  IconWell,
  Input,
  Panel,
  SegmentedControl,
  StatusBadge,
  ToolbarButton,
  TableShell,
} from '../components/ui'
import TerminalViewer from '../components/TerminalViewer'

const FILTERS = [
  ['all', 'All'],
  ['fail', 'Failing'],
  ['retry_pass', 'Retry-pass'],
  ['first_pass', 'First-pass'],
]

const LARGE_BATCH_THRESHOLD = 150
const LARGE_TABLE_PAGE_SIZE = 75
const LARGE_CARD_PAGE_SIZE = 20

const SORT_OPTIONS = [
  ['latest_failure', 'Latest failure'],
  ['status_priority', 'Status priority'],
  ['attempt_count', 'Attempt count'],
  ['failure_count', 'Failure count'],
  ['station', 'Station'],
  ['duration', 'Duration'],
  ['knowledge_match', 'Knowledge match'],
]

const SEARCH_FIELDS = [
  'unit_id',
  'serial_number',
  'product_code',
  'lot_id',
  'station_id',
  'host',
  'error_code',
  'error_message',
  'failing_step',
  'root_cause',
  'suggested_solution',
  'root_cause_category',
  'evidence_summary',
  'next_debug_action',
  'likely_owner',
  'safety_or_escape_risk',
  'knowledge_match_status',
]

const textValue = (value) => String(value ?? '').toLocaleLowerCase()

const groupMatchesSearch = (group, query) => {
  const normalizedQuery = query.trim().toLocaleLowerCase()
  if (!normalizedQuery) return true
  return groupAttempts(group).some((attempt) =>
    SEARCH_FIELDS.some((field) => textValue(attempt[field]).includes(normalizedQuery)),
  )
}

const latestFailureTime = (group) =>
  Math.max(
    0,
    ...(group.failures || []).map((attempt) =>
      Date.parse(attempt.end_time || attempt.start_time || '') || 0,
    ),
  )

const STATUS_PRIORITY = { fail: 0, retry_pass: 1, unknown: 2, first_pass: 3 }
const KNOWLEDGE_PRIORITY = {
  no_product_knowledge: 0,
  no_match: 1,
  no_product_code: 2,
  matched: 3,
  disabled: 4,
}

const compareGroups = (sortBy) => (left, right) => {
  const descending = (value) => Number(right[value] || 0) - Number(left[value] || 0)
  const station = (group) => textValue(group.final?.station_id || group.final?.host)
  const knowledge = (group) =>
    Math.min(
      5,
      ...(group.failures || []).map(
        (attempt) => KNOWLEDGE_PRIORITY[attempt.knowledge_match_status] ?? 5,
      ),
    )

  const difference = {
    latest_failure: latestFailureTime(right) - latestFailureTime(left),
    status_priority:
      (STATUS_PRIORITY[left.classification] ?? 4) -
      (STATUS_PRIORITY[right.classification] ?? 4),
    attempt_count: descending('attempt_count'),
    failure_count: descending('failure_count'),
    station: station(left).localeCompare(station(right)),
    duration: Number(right.final?.duration_s || 0) - Number(left.final?.duration_s || 0),
    knowledge_match: knowledge(left) - knowledge(right),
  }[sortBy]

  return difference || textValue(left.serial_number || left.unit_id).localeCompare(
    textValue(right.serial_number || right.unit_id),
  )
}

export default function Engineer({ jobId, drillDown, onClearDrillDown, onReviewKnowledge, initialViewState, onViewStateChange, feedbackDrafts = {}, onFeedbackDraftsChange }) {
  const { isAdmin } = useAuth()
  const initialView = { ...DEFAULT_ENGINEER_VIEW_STATE, ...(initialViewState || {}) }
  const [units, setUnits] = useState([])
  const [clusters, setClusters] = useState([])
  const [feedbackEntries, setFeedbackEntries] = useState([])
  const [runCount, setRunCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [unitsError, setUnitsError] = useState('')
  const [clustersError, setClustersError] = useState('')
  const [feedbackError, setFeedbackError] = useState('')
  const [unitsReload, setUnitsReload] = useState(0)
  const [clustersReload, setClustersReload] = useState(0)
  const [feedbackReload, setFeedbackReload] = useState(0)
  const [filter, setFilter] = useState(initialView.filter)
  const [quickFilter, setQuickFilter] = useState(
    initialView.serialFilter !== 'all'
      ? `serial:${initialView.serialFilter}`
      : initialView.filter === 'all' ? 'all' : `class:${initialView.filter}`,
  )
  const [serialFilter, setSerialFilter] = useState(initialView.serialFilter)
  const [searchQuery, setSearchQuery] = useState(initialView.searchQuery)
  const [sortBy, setSortBy] = useState(initialView.sortBy)
  const [activeSignature, setActiveSignature] = useState(initialView.activeSignature)
  const [page, setPage] = useState(1)
  const [view, setView] = useState(initialView.view)
  const [expanded, setExpanded] = useState(initialView.expanded)
  const [visibleColumns, setVisibleColumns] = useState(initialView.columns)
  const [reanalyzing, setReanalyzing] = useState(null)
  const [clearingCache, setClearingCache] = useState(null)
  const [clearingAll, setClearingAll] = useState(false)
  const [exporting, setExporting] = useState(null)
  const [feedbackBusy, setFeedbackBusy] = useState(null)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    if (!jobId) {
      setLoading(false)
      return undefined
    }
    let active = true
    setLoading(true)
    setUnitsError('')
    api.units(jobId).then(
      (unitData) => {
        if (!active) return
      setUnits(unitData.units)
      setRunCount(unitData.run_count ?? unitData.units.length)
      },
      (error) => {
        if (!active) return
        setUnits([])
        setRunCount(0)
        setUnitsError(error.message)
      },
    ).finally(() => {
      if (active) setLoading(false)
    })
    return () => {
      active = false
    }
  }, [jobId, unitsReload])

  useEffect(() => {
    if (!jobId) return undefined
    let active = true
    setClusters([])
    setClustersError('')
    api.clusters(jobId).then(
      (clusterData) => {
        if (!active) return
        setClusters(clusterData.clusters || [])
      },
      (error) => {
        if (active) setClustersError(error.message)
      },
    )
    return () => {
      active = false
    }
  }, [clustersReload, jobId])

  useEffect(() => {
    if (!jobId) return undefined
    let active = true
    setFeedbackEntries([])
    setFeedbackError('')
    api.feedback(jobId).then(
      (feedbackData) => {
        if (!active) return
        setFeedbackEntries(feedbackData.entries || [])
      },
      (error) => {
        if (active) setFeedbackError(error.message)
      },
    )
    return () => {
      active = false
    }
  }, [feedbackReload, jobId])

  useEffect(() => {
    if (!initialViewState) return
    const next = { ...DEFAULT_ENGINEER_VIEW_STATE, ...initialViewState }
    setFilter(next.filter)
    setSerialFilter(next.serialFilter)
    setSearchQuery(next.searchQuery)
    setSortBy(next.sortBy)
    setActiveSignature(next.activeSignature)
    setView(next.view)
    setExpanded(next.expanded)
    setVisibleColumns(next.columns)
    setQuickFilter(
      next.serialFilter !== 'all'
        ? `serial:${next.serialFilter}`
        : next.filter === 'all' ? 'all' : `class:${next.filter}`,
    )
  }, [initialViewState])

  useEffect(() => {
    onViewStateChange?.({
      filter,
      serialFilter,
      searchQuery,
      sortBy,
      activeSignature,
      view,
      expanded,
      columns: visibleColumns,
    })
  }, [activeSignature, expanded, filter, onViewStateChange, searchQuery, serialFilter, sortBy, view, visibleColumns])

  useEffect(() => {
    if (drillDown?.signature) setActiveSignature(drillDown.signature)
  }, [drillDown])

  const counts = useMemo(() => {
    const c = { all: units.length, fail: 0, retry_pass: 0, first_pass: 0, unknown: 0 }
    units.forEach((u) => (c[u.classification] = (c[u.classification] || 0) + 1))
    return c
  }, [units])

  const serials = useMemo(
    () =>
      Array.from(new Set(units.map((u) => u.serial_number || u.unit_id).filter(Boolean))).sort(),
    [units],
  )

  const cachedKeyCount = useMemo(() => {
    const keys = new Set()
    units.forEach((g) =>
      g.failures?.forEach((f) => {
        if (f.analysis_cache_key) keys.add(f.analysis_cache_key)
      }),
    )
    return keys.size
  }, [units])

  const triageSummary = useMemo(() => {
    const failures = units.flatMap((unit) => unit.failures || [])
    const signatures = new Map()
    failures.forEach((failure) => {
      if (!failure.signature) return
      const current = signatures.get(failure.signature) || {
        count: 0,
        label: failure.error_code || failure.error_message || failure.signature,
      }
      current.count += 1
      signatures.set(failure.signature, current)
    })
    const topFailure = [...signatures.values()].sort((left, right) => right.count - left.count)[0]
    const matchedKnowledge = failures.filter(
      (failure) => failure.knowledge_match_status === 'matched',
    ).length
    const newestFailure = Math.max(
      0,
      ...failures.map((failure) => Date.parse(failure.end_time || failure.start_time || '') || 0),
    )

    return {
      failing: units.filter((unit) => unit.classification === 'fail').length,
      retryPass: units.filter((unit) => unit.classification === 'retry_pass').length,
      topFailure: topFailure ? `${topFailure.count} · ${topFailure.label}` : 'None',
      missingDebugLog: failures.filter(
        (failure) => failure.debuglog_status && failure.debuglog_status !== 'excerpt',
      ).length,
      knowledgeCoverage: failures.length
        ? `${Math.round((matchedKnowledge / failures.length) * 100)}%`
        : '—',
      newestFailure: newestFailure
        ? new Date(newestFailure).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
        : '—',
    }
  }, [units])

  const setClassFilter = (cls) => {
    setFilter(cls)
    setSerialFilter('all')
    setQuickFilter(cls === 'all' ? 'all' : `class:${cls}`)
  }

  const setDropdownFilter = (value) => {
    setQuickFilter(value)
    if (value === 'all') {
      setFilter('all')
      setSerialFilter('all')
      return
    }
    if (value.startsWith('class:')) {
      setFilter(value.slice('class:'.length))
      setSerialFilter('all')
      return
    }
    if (value.startsWith('serial:')) {
      setFilter('all')
      setSerialFilter(value.slice('serial:'.length))
    }
  }

  const drillDownUnitIds = useMemo(
    () => new Set(drillDown?.unit_ids || []),
    [drillDown?.unit_ids],
  )

  const shown = useMemo(
    () =>
      units
        .filter((unit) => {
          const serial = unit.serial_number || unit.unit_id
          const hasExactScope = drillDownUnitIds.size > 0
          const matchesExactScope = !hasExactScope || drillDownUnitIds.has(serial)
          const matchesClass = filter === 'all' || unit.classification === filter
          const matchesSerial = serialFilter === 'all' || serial === serialFilter
          const matchesSignature =
            hasExactScope ||
            !activeSignature ||
            unit.failures?.some((failure) => failure.signature === activeSignature)
          const matchesStation =
            hasExactScope ||
            !drillDown?.station_id ||
            groupAttempts(unit).some(
              (attempt) =>
                attempt.station_id === drillDown.station_id &&
                (!drillDown.host || attempt.host === drillDown.host),
            )
          const matchesLot =
            hasExactScope ||
            !drillDown?.lot_id ||
            groupAttempts(unit).some((attempt) => attempt.lot_id === drillDown.lot_id)
          return (
            matchesClass &&
            matchesSerial &&
            matchesExactScope &&
            matchesSignature &&
            matchesStation &&
            matchesLot &&
            groupMatchesSearch(unit, searchQuery)
          )
        })
        .sort(compareGroups(sortBy)),
    [activeSignature, drillDown, drillDownUnitIds, filter, searchQuery, serialFilter, sortBy, units],
  )
  const pageSize = view === 'cards' ? LARGE_CARD_PAGE_SIZE : LARGE_TABLE_PAGE_SIZE
  const pageCount = shown.length > LARGE_BATCH_THRESHOLD ? Math.ceil(shown.length / pageSize) : 1
  const activePage = Math.min(page, pageCount)
  const visibleUnits = pageCount > 1
    ? shown.slice((activePage - 1) * pageSize, activePage * pageSize)
    : shown
  const selectedIndex = expanded ? shown.findIndex((unit) => unit.unit_id === expanded) : -1
  const selectedUnit = selectedIndex >= 0 ? shown[selectedIndex] : null

  useEffect(() => {
    setPage(1)
  }, [activeSignature, drillDown, filter, jobId, searchQuery, serialFilter, sortBy, view])

  const drillDownStats = useMemo(() => {
    if (!drillDown) return null
    if (drillDown.attempt_ids?.length || drillDown.unit_ids?.length) {
      return {
        attempts: drillDown.attempt_ids?.length || 0,
        units: drillDown.unit_ids?.length || 0,
        exact: true,
      }
    }
    const matchesAttempt = (attempt) => {
      if (drillDown.signature) return attempt.signature === drillDown.signature
      if (drillDown.station_id) {
        return (
          attempt.station_id === drillDown.station_id &&
          (!drillDown.host || attempt.host === drillDown.host)
        )
      }
      return attempt.lot_id === drillDown.lot_id
    }
    const matchingUnits = units.filter((unit) => groupAttempts(unit).some(matchesAttempt))
    const attempts = matchingUnits.reduce(
      (total, unit) => total + groupAttempts(unit).filter(matchesAttempt).length,
      0,
    )
    return { attempts, units: matchingUnits.length, exact: false }
  }, [drillDown, units])

  const clearDrillDown = () => {
    if (drillDown?.signature) setActiveSignature(null)
    onClearDrillDown?.()
  }

  // A re-analysis returns a single failing attempt; splice it back into the
  // group that owns it.
  const applyUpdatedFailure = (updated) =>
    setUnits((prev) =>
      prev.map((g) =>
        g.failures?.some((f) => f.unit_id === updated.unit_id)
          ? { ...g, failures: g.failures.map((f) => (f.unit_id === updated.unit_id ? updated : f)) }
          : g,
      ),
    )

  const reanalyze = async (attempt) => {
    setReanalyzing(attempt.unit_id)
    setActionError('')
    try {
      const updated = await api.reanalyze(jobId, attempt.unit_id)
      applyUpdatedFailure(updated)
    } catch (err) {
      setActionError(err.message)
    } finally {
      setReanalyzing(null)
    }
  }

  const clearCache = async (attempt) => {
    if (!attempt.analysis_cache_key) return
    setClearingCache(attempt.analysis_cache_key)
    setActionError('')
    try {
      await api.clearAnalysisCache(attempt.analysis_cache_key)
      setUnits((prev) =>
        prev.map((g) => ({
          ...g,
          failures: g.failures?.map((f) =>
            f.analysis_cache_key === attempt.analysis_cache_key
              ? { ...f, analysis_cache_key: null, cache_cleared: true }
              : f,
          ),
        })),
      )
    } catch (err) {
      setActionError(err.message)
    } finally {
      setClearingCache(null)
    }
  }

  const clearAllCache = async () => {
    if (!jobId || clearingAll || cachedKeyCount === 0) return
    setClearingAll(true)
    setActionError('')
    try {
      await api.clearJobCache(jobId)
      setUnits((prev) =>
        prev.map((g) => ({
          ...g,
          failures: g.failures?.map((f) =>
            f.analysis_cache_key ? { ...f, analysis_cache_key: null, cache_cleared: true } : f,
          ),
        })),
      )
    } catch (err) {
      setActionError(err.message)
    } finally {
      setClearingAll(false)
    }
  }

  const exportPacket = async ({ unitId, signature, filename }) => {
    const exportKey = unitId || signature
    setExporting(exportKey)
    setActionError('')
    try {
      const markdown = await api.debugPacket(jobId, { unitId, signature })
      const url = URL.createObjectURL(new Blob([markdown], { type: 'text/markdown' }))
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    } catch (err) {
      setActionError(err.message)
    } finally {
      setExporting(null)
    }
  }

  const submitFeedback = async (attempt, action, note) => {
    const key = `${attempt.unit_id}:${action}`
    setFeedbackBusy(key)
    setActionError('')
    try {
      const entry = await api.createFeedback(jobId, {
        unit_id: attempt.unit_id,
        action,
        note: note.trim() || null,
      })
      setFeedbackEntries((current) => [...current, entry])
      onFeedbackDraftsChange?.((current) => ({ ...current, [attempt.unit_id]: '' }))
    } catch (err) {
      setActionError(err.message)
      throw err
    } finally {
      setFeedbackBusy(null)
    }
  }

  if (!jobId) return <EmptyState />

  const detailProps = {
    expanded,
    setExpanded,
    reanalyzing,
    onReanalyze: reanalyze,
    clearingCache,
    onClearCache: isAdmin ? clearCache : undefined,
    exporting,
    onExport: exportPacket,
    onReviewKnowledge,
    feedbackEntries: feedbackError ? null : feedbackEntries,
    feedbackBusy,
    onFeedback: submitFeedback,
    visibleColumns,
    feedbackDrafts,
    onFeedbackDraftChange: (attemptId, value) => onFeedbackDraftsChange?.((current) => ({ ...current, [attemptId]: value })),
  }

  const selectUnitAt = (index) => {
    if (index < 0 || index >= shown.length) return
    setExpanded(shown[index].unit_id)
    if (pageCount > 1) setPage(Math.floor(index / pageSize) + 1)
  }

  if (unitsError) {
    return (
      <ResourceErrorState
        title="Unit diagnostics unavailable"
        message={unitsError}
        onRetry={() => setUnitsReload((value) => value + 1)}
      />
    )
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-6">
        <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">
          Engineer view
        </h1>
        {!loading && runCount > units.length && (
          <p className="mt-1 text-sm text-muted">
            {units.length} units from {runCount} test runs. First-pass units need no analysis;
            retry-pass and failing units show root cause and solution for each failure.
          </p>
        )}
      </div>

      {clustersError && (
        <ResourceNotice
          title="Failure families unavailable"
          message={clustersError}
          onRetry={() => setClustersReload((value) => value + 1)}
        />
      )}

      {feedbackError && (
        <ResourceNotice
          title="Engineer feedback unavailable"
          message={feedbackError}
          onRetry={() => setFeedbackReload((value) => value + 1)}
        />
      )}

      {!loading && (
        <TriageStrip summary={triageSummary} />
      )}

      {drillDown && drillDownStats && (
        <div className="mb-4 flex items-center gap-3">
          <Badge tone="accent">
            From Manager: {drillDown.label || 'selection'} · {drillDownStats.attempts} matching attempt{drillDownStats.attempts === 1 ? '' : 's'}
            {drillDownStats.attempts !== drillDownStats.units
              ? ` across ${drillDownStats.units} unit${drillDownStats.units === 1 ? '' : 's'}`
              : ''}
          </Badge>
          <Button variant="ghost" className="px-2 py-1" onClick={clearDrillDown}>
            Clear
          </Button>
        </div>
      )}

      {drillDownStats?.exact && (
        <p className="mb-4 text-xs text-muted">
          Unit rows show each selected unit's latest outcome and available failure evidence; intermediate passing attempts remain included in the Manager count.
        </p>
      )}

      {activeSignature && !drillDown && (
        <div className="mb-4 flex items-center gap-3">
          <Badge tone="accent">
            Failure family: {clusters.find((cluster) => cluster.signature === activeSignature)?.error_code || activeSignature}
          </Badge>
          <Button variant="ghost" className="px-2 py-1" onClick={() => setActiveSignature(null)}>
            Clear
          </Button>
        </div>
      )}

      <div className="mb-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
        <Input
          type="search"
          value={searchQuery}
          onChange={(event) => setSearchQuery(event.target.value)}
          placeholder="Search serial, station, error, step, or diagnosis"
          aria-label="Search units"
        />
        <select
          value={sortBy}
          onChange={(event) => setSortBy(event.target.value)}
          className="rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm font-medium text-ink-2 focus-ring"
          aria-label="Sort units"
        >
          {SORT_OPTIONS.map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-4 mb-4">
        <div className="flex min-w-0 max-w-full flex-wrap items-center gap-2">
          {FILTERS.map(([key, label]) => (
            <ToolbarButton key={key} active={filter === key} onClick={() => setClassFilter(key)}>
              {label} <span className="opacity-60">({counts[key] ?? 0})</span>
            </ToolbarButton>
          ))}
          {counts.unknown > 0 && (
            <ToolbarButton active={filter === 'unknown'} onClick={() => setClassFilter('unknown')}>
              Unknown <span className="opacity-60">({counts.unknown})</span>
            </ToolbarButton>
          )}
          <select
            value={quickFilter}
            onChange={(event) => setDropdownFilter(event.target.value)}
            className="min-w-0 max-w-full rounded-lg border border-border bg-surface px-3.5 py-2 text-sm font-medium text-ink-2 focus-ring"
          >
            <option value="all">All units</option>
            <option value="class:fail">Failing units</option>
            <option value="class:retry_pass">Retry-pass units</option>
            <option value="class:first_pass">First-pass units</option>
            <optgroup label="Serial number">
              {serials.map((serial) => (
                <option key={serial} value={`serial:${serial}`}>
                  {serial}
                </option>
              ))}
            </optgroup>
          </select>
          <ToolbarButton
            onClick={clearAllCache}
            disabled={clearingAll || cachedKeyCount === 0}
            title="Delete cached analysis results for the currently loaded folder/file/zip only"
            className={`disabled:opacity-50 disabled:cursor-not-allowed${isAdmin ? '' : ' hidden'}`}
          >
            {clearingAll ? 'Clearing…' : 'Clear cached results'}
            {cachedKeyCount > 0 && <span className="opacity-60">({cachedKeyCount})</span>}
          </ToolbarButton>
          <ColumnChooser columns={visibleColumns} onChange={setVisibleColumns} />
        </div>

        <SegmentedControl
          options={[
            ['table', 'Table'],
            ['cards', 'Cards'],
          ]}
          value={view}
          onChange={setView}
          className="shrink-0"
        />
      </div>

      {actionError && (
        <div className="mb-4 rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {actionError}
        </div>
      )}

      {pageCount > 1 && (
        <PaginationControls
          page={activePage}
          pageCount={pageCount}
          pageSize={pageSize}
          total={shown.length}
          onChange={setPage}
        />
      )}

      {loading ? (
        <Card className="p-10 text-center text-muted">Loading units…</Card>
      ) : shown.length === 0 ? (
        <Card className="p-10 text-center text-muted">
          <p>No units match the current search and filters.</p>
          {(searchQuery || filter !== 'all' || serialFilter !== 'all' || activeSignature || drillDown) && (
            <Button
              variant="ghost"
              className="mt-3"
              onClick={() => {
                setSearchQuery('')
                setClassFilter('all')
                setActiveSignature(null)
                onClearDrillDown?.()
              }}
            >
              Clear search and filters
            </Button>
          )}
        </Card>
      ) : selectedUnit ? (
        <InspectionWorkspace
          units={visibleUnits}
          selected={selectedUnit}
          selectedIndex={selectedIndex}
          total={shown.length}
          onSelect={(unitId) => setExpanded(unitId)}
          onBack={() => setExpanded(null)}
          onPrevious={() => selectUnitAt(selectedIndex - 1)}
          onNext={() => selectUnitAt(selectedIndex + 1)}
          detailProps={detailProps}
        />
      ) : view === 'table' ? (
        <TableView units={visibleUnits} {...detailProps} />
      ) : (
        <CardsView units={visibleUnits} {...detailProps} />
      )}
      {pageCount > 1 && (
        <PaginationControls
          page={activePage}
          pageCount={pageCount}
          pageSize={pageSize}
          total={shown.length}
          onChange={setPage}
          className="mt-4"
        />
      )}
      {!loading && clusters.length > 0 && (
        <ClusterPanel
          clusters={clusters}
          activeSignature={activeSignature}
          exporting={exporting}
          onExport={exportPacket}
          onSelect={(signature) => {
            onClearDrillDown?.()
            setActiveSignature(signature)
          }}
        />
      )}
    </div>
  )
}

function PaginationControls({ page, pageCount, pageSize, total, onChange, className = 'mb-4' }) {
  const first = (page - 1) * pageSize + 1
  const last = Math.min(page * pageSize, total)
  return (
    <div className={`flex flex-wrap items-center justify-between gap-3 ${className}`}>
      <span className="text-sm text-muted">Showing {first}-{last} of {total} units</span>
      <div className="flex items-center gap-1" aria-label="Unit pages">
        <ToolbarButton
          aria-label="First page"
          title="First page"
          disabled={page === 1}
          className="h-9 w-9 justify-center px-0 disabled:opacity-40"
          onClick={() => onChange(1)}
        >
          «
        </ToolbarButton>
        <ToolbarButton
          aria-label="Previous page"
          title="Previous page"
          disabled={page === 1}
          className="h-9 w-9 justify-center px-0 disabled:opacity-40"
          onClick={() => onChange(page - 1)}
        >
          ‹
        </ToolbarButton>
        <span className="min-w-24 text-center text-sm font-medium text-ink">
          {page} / {pageCount}
        </span>
        <ToolbarButton
          aria-label="Next page"
          title="Next page"
          disabled={page === pageCount}
          className="h-9 w-9 justify-center px-0 disabled:opacity-40"
          onClick={() => onChange(page + 1)}
        >
          ›
        </ToolbarButton>
        <ToolbarButton
          aria-label="Last page"
          title="Last page"
          disabled={page === pageCount}
          className="h-9 w-9 justify-center px-0 disabled:opacity-40"
          onClick={() => onChange(pageCount)}
        >
          »
        </ToolbarButton>
      </div>
    </div>
  )
}

function TriageStrip({ summary }) {
  const items = [
    ['Still failing', summary.failing, 'text-danger'],
    ['Retry-pass', summary.retryPass, 'text-warning'],
    ['Top failed attempts', summary.topFailure, 'text-ink'],
    ['DebugLog missing', summary.missingDebugLog, 'text-warning'],
    ['Knowledge coverage', summary.knowledgeCoverage, 'text-accent'],
    ['Newest failure', summary.newestFailure, 'text-ink'],
  ]
  return (
    <dl className="mb-5 grid border-y border-border bg-surface/50 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
      {items.map(([label, value, tone]) => (
        <div key={label} className="min-w-0 border-b border-border px-3 py-2 last:border-b-0 sm:border-r lg:border-b-0">
          <dt className="text-[0.68rem] font-medium uppercase tracking-wide text-muted">{label}</dt>
          <dd className={`mt-1 truncate text-sm font-bold ${tone}`} title={String(value)}>{value}</dd>
        </div>
      ))}
    </dl>
  )
}

const COLUMN_OPTIONS = [
  ['product', 'Product'],
  ['failure', 'Failure / step'],
  ['evidence', 'Evidence'],
  ['action', 'Next action'],
]

function ColumnChooser({ columns, onChange }) {
  const toggle = (column) => {
    onChange(columns.includes(column)
      ? columns.filter((value) => value !== column)
      : [...columns, column])
  }
  return (
    <details className="relative">
      <summary className="cursor-pointer list-none rounded-lg border border-border bg-surface px-3.5 py-2 text-sm font-medium text-ink-2 hover:bg-surface-2 focus-ring">
        Columns
      </summary>
      <div className="absolute left-0 top-11 z-10 min-w-44 rounded-lg border border-border bg-surface p-2 shadow-md">
        {COLUMN_OPTIONS.map(([value, label]) => (
          <label key={value} className="flex cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-sm text-ink-2 hover:bg-surface-2">
            <input type="checkbox" checked={columns.includes(value)} onChange={() => toggle(value)} className="accent-[var(--accent)]" />
            {label}
          </label>
        ))}
      </div>
    </details>
  )
}

function ClusterPanel({ clusters, activeSignature, exporting, onSelect, onExport }) {
  const [open, setOpen] = useState(false)
  useEffect(() => {
    if (activeSignature) setOpen(true)
  }, [activeSignature])
  return (
    <section className="mt-6 border-t border-border pt-5" aria-labelledby="failure-families-heading">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 id="failure-families-heading" className="font-display text-base font-bold text-ink">
            Failure families
          </h2>
          <p className="text-xs text-muted">Ranked by failed attempts; select a family to filter the worklist above.</p>
        </div>
        <Button variant="ghost" className="px-3 py-1.5" onClick={() => setOpen((value) => !value)} aria-expanded={open}>
          {open ? 'Collapse' : `Show ${clusters.length}`}
        </Button>
      </div>
      {open && <div className="mt-3 overflow-hidden rounded-lg border border-border bg-surface">
        {clusters.map((cluster) => {
          const selected = activeSignature === cluster.signature
          const lastSeen = cluster.last_seen
            ? new Date(cluster.last_seen).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
            : 'Unknown'
          return (
            <div
              key={cluster.signature}
              className={[
                'flex min-w-0 items-center gap-3 border-b border-border px-3 py-2 last:border-b-0',
                selected
                  ? 'bg-accent/10'
                  : 'hover:bg-surface-2',
              ].join(' ')}
            >
              <button
                type="button"
                onClick={() => onSelect(selected ? null : cluster.signature)}
                className="grid min-w-0 flex-1 grid-cols-[auto_minmax(0,1fr)] items-center gap-x-3 text-left focus-ring sm:grid-cols-[auto_minmax(0,1fr)_auto_auto]"
              >
                <Badge tone="fail">{cluster.count} failed</Badge>
                <div className="min-w-0">
                  <p className="truncate text-sm font-semibold text-ink">{cluster.error_code || 'Unknown failure'} · {cluster.error_message || 'No error message'}</p>
                  <p className="truncate text-xs text-muted">{cluster.stations?.join(', ') || 'No station'} · {cluster.lots?.join(', ') || 'No lot'}</p>
                </div>
                <span className="hidden text-xs text-muted sm:block">{cluster.affected_serials?.length || 0} units</span>
                <span className="hidden text-xs text-muted sm:block">Latest {lastSeen}</span>
              </button>
              <Button
                variant="ghost"
                className="shrink-0 px-2 py-1"
                disabled={exporting === cluster.signature}
                onClick={() => onExport({
                  signature: cluster.signature,
                  filename: `co-trace-cluster-${cluster.signature}.md`,
                })}
              >
                {exporting === cluster.signature ? 'Exporting…' : 'Export packet'}
              </Button>
            </div>
          )
        })}
      </div>}
    </section>
  )
}

const attemptsLabel = (u) =>
  u.failure_count > 0 ? `${u.attempt_count} · ${u.failure_count} failed` : `${u.attempt_count}`

const latestFailedAttempt = (unit) => unit.failures?.[unit.failures.length - 1] || null

function evidenceLabel(attempt) {
  if (!attempt) return 'No failure evidence'
  const source = {
    debug_excerpt: 'DebugLog excerpt',
    ftrunner_snippet: 'FTRunner snippet',
    error_message: 'Error message only',
  }[attempt.analysis_context_source] || 'Evidence unavailable'
  return attempt.debuglog_status && !['excerpt', 'not_applicable'].includes(attempt.debuglog_status)
    ? `${source} · DebugLog missing`
    : source
}

function InspectionWorkspace({ units, selected, selectedIndex, total, onSelect, onBack, onPrevious, onNext, detailProps }) {
  const failure = latestFailedAttempt(selected)
  return (
    <div className="grid min-w-0 gap-4 lg:grid-cols-[minmax(18rem,0.72fr)_minmax(0,1.28fr)]">
      <aside className="hidden max-h-[75vh] overflow-y-auto rounded-panel border border-border bg-surface lg:block" aria-label="Filtered unit queue">
        <div className="sticky top-0 border-b border-border bg-surface-2 px-3 py-2 text-xs font-medium text-muted">
          {units.length} units on this page · {total} filtered
        </div>
        {units.map((unit) => {
          const itemFailure = latestFailedAttempt(unit)
          return (
            <button
              key={unit.unit_id}
              type="button"
              aria-current={unit.unit_id === selected.unit_id ? 'true' : undefined}
              onClick={() => onSelect(unit.unit_id)}
              className={[
                'block w-full border-b border-border px-3 py-3 text-left last:border-b-0 focus-ring',
                unit.unit_id === selected.unit_id ? 'bg-accent/10' : 'hover:bg-surface-2',
              ].join(' ')}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate text-sm font-semibold text-ink">{unit.serial_number || unit.unit_id}</span>
                <StatusBadge status={unit.classification} />
              </div>
              <p className="mt-1 truncate text-xs text-muted">{itemFailure?.error_code || itemFailure?.failing_step || 'No failure evidence'}</p>
            </button>
          )
        })}
      </aside>

      <section className="min-w-0" aria-labelledby="selected-unit-heading">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <Button variant="ghost" className="px-2 py-1.5 lg:hidden" onClick={onBack}>Back</Button>
            <div className="min-w-0">
              <p className="text-xs text-muted">Unit {selectedIndex + 1} of {total}</p>
              <h2 id="selected-unit-heading" className="truncate font-display text-lg font-bold text-ink">{selected.serial_number || selected.unit_id}</h2>
            </div>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" className="px-3 py-1.5" disabled={selectedIndex <= 0} onClick={onPrevious}>Previous</Button>
            <Button variant="ghost" className="px-3 py-1.5" disabled={selectedIndex >= total - 1} onClick={onNext}>Next</Button>
          </div>
        </div>
        {failure && <p className="mb-3 truncate text-sm text-muted" title={failure.error_message || ''}>{failure.error_code || failure.error_message}</p>}
        <UnitDetails u={selected} {...detailProps} />
      </section>
    </div>
  )
}


function TableView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge, feedbackEntries, feedbackBusy, onFeedback, visibleColumns, feedbackDrafts, onFeedbackDraftChange }) {
  const columnCount = 6 + visibleColumns.length
  return (
    <TableShell tableClassName="min-w-[1100px] table-fixed">
      <thead>
        <tr className="border-b border-border bg-surface-2 text-left text-muted">
          <th className="px-4 py-3 font-medium">Status</th>
          <th className="px-4 py-3 font-medium">Serial</th>
          {visibleColumns.includes('product') && <th className="px-4 py-3 font-medium">Product</th>}
          <th className="px-4 py-3 font-medium">Station</th>
          {visibleColumns.includes('failure') && <th className="px-4 py-3 font-medium">Failure / step</th>}
          {visibleColumns.includes('evidence') && <th className="px-4 py-3 font-medium">Evidence</th>}
          {visibleColumns.includes('action') && <th className="px-4 py-3 font-medium">Next action</th>}
          <th className="px-4 py-3 font-medium text-right">Attempts</th>
          <th className="px-4 py-3 font-medium text-right">Duration</th>
          <th className="px-4 py-3 font-medium text-right">Actions</th>
        </tr>
      </thead>
      <tbody>
        {units.map((u) => {
          const hasDetails = u.failure_count > 0
          const failure = latestFailedAttempt(u)
          return (
            <Fragment key={u.unit_id}>
              <tr className="border-b border-border/60 text-ink transition-colors hover:bg-surface-2/60">
                <td className="px-4 py-3 whitespace-nowrap">
                  <StatusBadge status={u.classification} />
                </td>
                <td className="px-4 py-3 whitespace-nowrap font-medium">
                  {u.serial_number || u.unit_id}
                </td>
                {visibleColumns.includes('product') && (
                  <td className="px-4 py-3"><span className="block truncate" title={u.final.product_code || ''}>{u.final.product_code || '—'}</span></td>
                )}
                <td className="px-4 py-3 whitespace-nowrap">{u.final.station_id || '—'}</td>
                {visibleColumns.includes('failure') && (
                  <td className="px-4 py-3">
                    <span className="block truncate font-medium" title={failure?.error_message || ''}>{failure?.error_code || failure?.error_message || '—'}</span>
                    <span className="block truncate text-xs text-muted" title={failure?.failing_step || ''}>{failure?.failing_step || 'No failing step'}</span>
                  </td>
                )}
                {visibleColumns.includes('evidence') && (
                  <td className="px-4 py-3"><span className="block truncate text-xs" title={evidenceLabel(failure)}>{evidenceLabel(failure)}</span></td>
                )}
                {visibleColumns.includes('action') && (
                  <td className="px-4 py-3"><span className="block truncate text-xs" title={failure?.next_debug_action || failure?.suggested_solution || ''}>{failure?.next_debug_action || failure?.suggested_solution || '—'}</span></td>
                )}
                <td className="px-4 py-3 text-right whitespace-nowrap">{attemptsLabel(u)}</td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {u.final.duration_s ? `${u.final.duration_s.toFixed(1)}s` : '—'}
                </td>
                <td className="px-4 py-3 text-right whitespace-nowrap">
                  {hasDetails ? (
                    <button
                      className="rounded-md px-2 py-1 text-accent hover:bg-accent/10 focus-ring"
                      onClick={() => setExpanded(expanded === u.unit_id ? null : u.unit_id)}
                    >
                      {expanded === u.unit_id ? 'Hide' : 'Details'}
                    </button>
                  ) : (
                    <span className="text-placeholder">—</span>
                  )}
                </td>
              </tr>
              {hasDetails && expanded === u.unit_id && (
                <tr>
                  <td colSpan={columnCount} className="max-w-0 overflow-hidden bg-surface-2 px-4 pb-5 pt-1">
                    <div className="min-w-0 max-w-full overflow-hidden">
                      <UnitDetails
                        u={u}
                        reanalyzing={reanalyzing}
                        onReanalyze={onReanalyze}
                        clearingCache={clearingCache}
                        onClearCache={onClearCache}
                        exporting={exporting}
                        onExport={onExport}
                        onReviewKnowledge={onReviewKnowledge}
                        feedbackEntries={feedbackEntries}
                        feedbackBusy={feedbackBusy}
                        onFeedback={onFeedback}
                        feedbackDrafts={feedbackDrafts}
                        onFeedbackDraftChange={onFeedbackDraftChange}
                      />
                    </div>
                  </td>
                </tr>
              )}
            </Fragment>
          )
        })}
      </tbody>
    </TableShell>
  )
}

function CardsView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge, feedbackEntries, feedbackBusy, onFeedback, feedbackDrafts, onFeedbackDraftChange }) {
  return (
    <div className="space-y-4">
      {units.map((u) => {
        const hasDetails = u.failure_count > 0
        const failure = latestFailedAttempt(u)
        return (
          <Card key={u.unit_id} className="p-6">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex items-center gap-3 flex-wrap">
                  <StatusBadge status={u.classification} />
                  <span className="font-display font-bold text-ink truncate">
                    {u.serial_number || u.unit_id}
                  </span>
                </div>
                <div className="mt-2 text-sm text-muted flex flex-wrap gap-x-6 gap-y-1">
                  <span>Product: {u.final.product_code || '—'}</span>
                  <span>Station: {u.final.station_id || '—'}</span>
                  <span>Attempts: {attemptsLabel(u)}</span>
                  {u.final.duration_s ? <span>{u.final.duration_s.toFixed(1)}s</span> : null}
                </div>
                {failure && (
                  <div className="mt-3 grid gap-2 text-xs sm:grid-cols-3">
                    <p className="truncate" title={failure.error_message || ''}><span className="text-muted">Failure:</span> {failure.error_code || failure.error_message || '—'}</p>
                    <p className="truncate" title={evidenceLabel(failure)}><span className="text-muted">Evidence:</span> {evidenceLabel(failure)}</p>
                    <p className="truncate" title={failure.next_debug_action || failure.suggested_solution || ''}><span className="text-muted">Next:</span> {failure.next_debug_action || failure.suggested_solution || '—'}</p>
                  </div>
                )}
              </div>
              {hasDetails && (
                <button
                  className="shrink-0 rounded-md px-2 py-1 text-sm text-accent hover:bg-accent/10 focus-ring"
                  onClick={() => setExpanded(expanded === u.unit_id ? null : u.unit_id)}
                >
                  {expanded === u.unit_id ? 'Hide' : 'Details'}
                </button>
              )}
            </div>

            {hasDetails && (
              <div className="mt-5">
                <UnitDetails
                  u={u}
                  showSnippet={expanded === u.unit_id}
                  reanalyzing={reanalyzing}
                  onReanalyze={onReanalyze}
                  clearingCache={clearingCache}
                  onClearCache={onClearCache}
                  exporting={exporting}
                  onExport={onExport}
                  onReviewKnowledge={onReviewKnowledge}
                  feedbackEntries={feedbackEntries}
                  feedbackBusy={feedbackBusy}
                  onFeedback={onFeedback}
                  feedbackDrafts={feedbackDrafts}
                  onFeedbackDraftChange={onFeedbackDraftChange}
                />
              </div>
            )}
          </Card>
        )
      })}
    </div>
  )
}

function UnitDetails({ u, showSnippet = true, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge, feedbackEntries, feedbackBusy, onFeedback, feedbackDrafts = {}, onFeedbackDraftChange }) {
  const passedAfter =
    u.classification === 'retry_pass'
      ? `Passed after ${u.failure_count} failed attempt${u.failure_count === 1 ? '' : 's'}.`
      : null
  return (
    <div className="space-y-4">
      {passedAfter && (
        <div className="flex items-center gap-2 text-sm text-warning font-medium">
          <span>↻</span>
          <span>{passedAfter} Previous failures below.</span>
        </div>
      )}
      {u.classification === 'retry_pass' && <RetryComparison unit={u} />}
      {u.failures.map((attempt, i) => (
        <FailureBlock
          key={attempt.unit_id}
          attempt={attempt}
          index={i + 1}
          total={u.failures.length}
          isFinal={u.classification !== 'retry_pass' && attempt.unit_id === u.final.unit_id}
          showSnippet={showSnippet}
          reanalyzing={reanalyzing}
          onReanalyze={onReanalyze}
          clearingCache={clearingCache}
          onClearCache={onClearCache}
          exporting={exporting}
          onExport={onExport}
          onReviewKnowledge={onReviewKnowledge}
          feedbackEntries={feedbackEntries?.filter((entry) => entry.unit_id === attempt.unit_id) ?? null}
          feedbackBusy={feedbackBusy}
          onFeedback={onFeedback}
          feedbackDraft={feedbackDrafts[attempt.unit_id] || ''}
          onFeedbackDraftChange={(value) => onFeedbackDraftChange?.(attempt.unit_id, value)}
        />
      ))}
    </div>
  )
}

const formatAttemptTime = (value) =>
  value ? value.replace('T', ' ').slice(0, 19) : 'Unavailable'

const stepSummary = (attempt) => {
  const steps = attempt.steps || []
  if (!steps.length) return 'No step data'
  const passed = steps.filter((step) => step.result === 'PASS').length
  const failed = steps.filter((step) => step.result === 'FAIL').length
  return `${steps.length} steps · ${passed} passed${failed ? ` · ${failed} failed` : ''}`
}

function RetryComparison({ unit }) {
  const finalAttempt = unit.final
  const repeatedSteps = new Set(
    (unit.failures || [])
      .map((attempt) => attempt.failing_step)
      .filter((step, index, all) => step && all.indexOf(step) !== index),
  )

  return (
    <section className="border-y border-border py-4" aria-label="Retry comparison">
      <div className="mb-3 flex items-center justify-between gap-3">
        <h3 className="font-display text-sm font-bold text-ink">Failed attempts vs final pass</h3>
        <Badge tone="pass">Final pass</Badge>
      </div>
      <div className="space-y-3">
        {unit.failures.map((failure, index) => {
          const stationChanged =
            (failure.station_id || failure.host) &&
            (failure.station_id !== finalAttempt.station_id || failure.host !== finalAttempt.host)
          const durationDifference = Math.abs(
            Number(failure.duration_s || 0) - Number(finalAttempt.duration_s || 0),
          )
          const durationChanged =
            durationDifference >= 5 &&
            durationDifference >= Math.max(1, Number(finalAttempt.duration_s || 0) * 0.5)
          const repeatedStep = repeatedSteps.has(failure.failing_step)

          return (
            <div key={failure.unit_id} className="grid min-w-0 gap-3 md:grid-cols-2">
              <ComparisonAttempt
                title={`Failed attempt ${index + 1}`}
                attempt={failure}
                tone="fail"
                highlights={{ stationChanged, durationChanged, repeatedStep }}
              />
              <ComparisonAttempt
                title="Final passing attempt"
                attempt={finalAttempt}
                tone="pass"
                highlights={{ stationChanged, durationChanged }}
              />
            </div>
          )
        })}
      </div>
    </section>
  )
}

function ComparisonAttempt({ title, attempt, tone, highlights = {} }) {
  return (
    <div className="min-w-0 rounded-lg border border-border bg-surface px-4 py-3">
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <Badge tone={tone}>{title}</Badge>
        {highlights.stationChanged && <Badge tone="warn">Station changed</Badge>}
        {highlights.durationChanged && <Badge tone="warn">Duration changed</Badge>}
        {highlights.repeatedStep && <Badge tone="warn">Repeated failing step</Badge>}
      </div>
      <dl className="grid grid-cols-[6rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-xs">
        <dt className="text-muted">Station / host</dt>
        <dd className="break-words text-ink">{attempt.station_id || '—'} / {attempt.host || '—'}</dd>
        <dt className="text-muted">Duration</dt>
        <dd className="text-ink">{attempt.duration_s ? `${attempt.duration_s.toFixed(1)}s` : 'Unavailable'}</dd>
        <dt className="text-muted">Steps</dt>
        <dd className="break-words text-ink">{stepSummary(attempt)}</dd>
        <dt className="text-muted">Failing step</dt>
        <dd className="break-words text-ink">{attempt.failing_step || 'None'}</dd>
        <dt className="text-muted">Started</dt>
        <dd className="break-words text-ink">{formatAttemptTime(attempt.start_time)}</dd>
        <dt className="text-muted">Ended</dt>
        <dd className="break-words text-ink">{formatAttemptTime(attempt.end_time)}</dd>
      </dl>
    </div>
  )
}

const KNOWLEDGE_CATEGORY_LABEL = {
  debug_learning: 'debug learning',
  hld: 'HLD',
  product_overview: 'product overview',
  uncategorized: 'uncategorized',
}

function KnowledgeBadge({ attempt }) {
  const status = attempt.knowledge_match_status
  if (!status || status === 'disabled') return null
  const categories = attempt.knowledge_categories || []
  const sectionCount = (attempt.knowledge_section_ids || []).length
  if (status === 'matched' && attempt.knowledge_used) {
    const cats = categories.map((c) => KNOWLEDGE_CATEGORY_LABEL[c] || c).join(', ')
    return (
      <div className="mb-3 text-xs text-teal">
        <span className="font-semibold">◆ Product knowledge used:</span>{' '}
        {cats || 'matched'} · {sectionCount} section{sectionCount === 1 ? '' : 's'}
      </div>
    )
  }
  const message = {
    no_match: 'Product knowledge: no matching section for this failure',
    no_product_knowledge: 'No product knowledge for this product code',
    no_product_code: 'No product code — product knowledge not applied',
  }[status]
  if (!message) return null
  return <div className="mb-3 text-xs text-muted">◇ {message}</div>
}

function DebugLogStatus({ attempt }) {
  const status = attempt.debuglog_status
  if (!status || status === 'not_applicable') return null
  const message = attempt.debuglog_message || 'DebugLog status unavailable'
  const tone = status === 'excerpt' ? 'accent' : status === 'empty' || status === 'loose_present' ? 'warn' : 'muted'
  return (
    <div className="mb-3 flex flex-wrap items-center gap-2 text-xs text-muted">
      <Badge tone={tone}>DebugLog</Badge>
      <span className="break-words [overflow-wrap:anywhere]">{message}</span>
    </div>
  )
}

const ANALYSIS_SOURCE_LABEL = {
  llm: 'Copilot analysis',
  stub: 'Offline placeholder',
  cached: 'Reused in batch',
  'local-cache': 'Saved analysis',
  playbook: 'Reviewed playbook',
}

const CONTEXT_SOURCE_LABEL = {
  debug_excerpt: 'DebugLog excerpt',
  ftrunner_snippet: 'FTRunner snippet',
  error_message: 'Error message only',
}

function EvidenceQuality({ attempt }) {
  const weakReasons = []
  if (attempt.analysis_source === 'stub') weakReasons.push('Offline placeholder, not a live diagnosis')
  if (attempt.analysis_context_source === 'error_message') weakReasons.push('Only the error message was available')
  if (attempt.knowledge_match_status && attempt.knowledge_match_status !== 'matched') {
    weakReasons.push('No matching product knowledge')
  }
  if (
    attempt.debuglog_status &&
    !['excerpt', 'not_applicable'].includes(attempt.debuglog_status)
  ) {
    weakReasons.push(attempt.debuglog_message || 'DebugLog evidence was unavailable')
  }
  const unknownAcronyms = attempt.unknown_acronyms || []

  return (
    <div className="mb-4 border-y border-border/60 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge tone={weakReasons.length ? 'warn' : 'pass'}>
          {weakReasons.length ? 'Weak evidence' : 'Grounded evidence'}
        </Badge>
        <Badge tone={attempt.analysis_source === 'stub' ? 'warn' : attempt.analysis_source === 'playbook' ? 'pass' : 'muted'}>
          {ANALYSIS_SOURCE_LABEL[attempt.analysis_source] || attempt.analysis_source || 'Pending analysis'}
        </Badge>
        <Badge tone="muted">
          {CONTEXT_SOURCE_LABEL[attempt.analysis_context_source] || 'Context source unavailable'}
        </Badge>
        {attempt.knowledge_match_status === 'matched' && <Badge tone="pass">Product knowledge matched</Badge>}
      </div>
      {weakReasons.length > 0 && (
        <ul className="mt-2 space-y-1 text-xs text-warning">
          {weakReasons.map((reason) => <li key={reason}>{reason}</li>)}
        </ul>
      )}
      {unknownAcronyms.length > 0 && (
        <div className="mt-3 flex flex-wrap items-center gap-2 text-xs text-muted">
          <span>Review acronyms:</span>
          {unknownAcronyms.map((acronym) => (
            <Badge key={acronym} tone="warn">{acronym}</Badge>
          ))}
        </div>
      )}
    </div>
  )
}

function StructuredRca({ attempt }) {
  const hasStructuredRca =
    attempt.confidence != null ||
    attempt.root_cause_category ||
    attempt.evidence_summary ||
    attempt.next_debug_action ||
    attempt.likely_owner ||
    attempt.safety_or_escape_risk ||
    attempt.needs_more_evidence != null
  if (!hasStructuredRca) return null

  const confidence =
    attempt.confidence != null ? `${Math.round(attempt.confidence * 100)}% confidence` : null

  return (
    <div className="mb-4">
      <div className="flex flex-wrap gap-2">
        {attempt.root_cause_category && <Badge tone="accent">{attempt.root_cause_category}</Badge>}
        {confidence && <Badge tone="muted">{confidence}</Badge>}
        {attempt.likely_owner && <Badge tone="muted">Owner: {attempt.likely_owner}</Badge>}
        {attempt.safety_or_escape_risk && (
          <Badge tone={attempt.safety_or_escape_risk.toLowerCase() === 'low' ? 'pass' : 'warn'}>
            Risk: {attempt.safety_or_escape_risk}
          </Badge>
        )}
        {attempt.needs_more_evidence === true && <Badge tone="warn">Needs more evidence</Badge>}
      </div>
      {attempt.evidence_summary && (
        <div className="mt-3">
          <div className="mb-1 text-xs uppercase tracking-wide text-muted">Evidence summary</div>
          <p className="text-sm text-ink-2 whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {attempt.evidence_summary}
          </p>
        </div>
      )}
      {attempt.next_debug_action && (
        <div className="mt-3 border-l-2 border-accent pl-3">
          <div className="mb-1 text-xs uppercase tracking-wide text-muted">Next debug action</div>
          <p className="font-medium text-ink whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
            {attempt.next_debug_action}
          </p>
        </div>
      )}
    </div>
  )
}

function FailureBlock({ attempt, index, total, isFinal, showSnippet, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge, feedbackEntries, feedbackBusy, onFeedback, feedbackDraft, onFeedbackDraftChange }) {
  const canClearCache =
    !!onClearCache &&
    attempt.analysis_cache_key && ['llm', 'local-cache'].includes(attempt.analysis_source)
  const sourceLabel = attempt.cache_cleared
    ? 'cache cleared'
    : ANALYSIS_SOURCE_LABEL[attempt.analysis_source] || attempt.analysis_source
  const when = attempt.start_time ? attempt.start_time.replace('T', ' ').slice(0, 19) : null

  return (
    <Panel className="min-w-0 overflow-hidden p-5">
      <div className="flex items-center justify-between gap-3 mb-3">
        <div className="flex items-center gap-2 flex-wrap">
          <Badge tone="fail">FAIL</Badge>
          <span className="text-sm font-medium text-ink">
            {total > 1 ? `Attempt ${index} of ${total}` : 'Failed attempt'}
            {isFinal ? ' · latest' : ''}
          </span>
          {when && <span className="text-xs text-muted">· {when}</span>}
        </div>
        {attempt.failing_step && (
          <span className="min-w-0 max-w-full text-xs text-muted break-words [overflow-wrap:anywhere]">
            step: {attempt.failing_step}
          </span>
        )}
      </div>

      {(attempt.error_code || attempt.error_message) && (
        <p className="mb-3 text-xs text-muted whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
          {attempt.error_code ? `${attempt.error_code}: ` : ''}
          {attempt.error_message || ''}
        </p>
      )}

      <KnowledgeBadge attempt={attempt} />
      <DebugLogStatus attempt={attempt} />
      <EvidenceQuality attempt={attempt} />
      {attempt.analysis_source === 'playbook' && (
        <div className="mb-4 flex flex-wrap items-center gap-2 border-l-2 border-teal pl-3">
          <Badge tone="pass">Deterministic playbook guidance</Badge>
          <Button
            variant="ghost"
            className="px-2 py-1"
            onClick={() => onReviewKnowledge?.({
              productCode: attempt.product_code,
              playbookId: attempt.playbook_id,
            })}
          >
            Open playbook
          </Button>
        </div>
      )}
      <StructuredRca attempt={attempt} />
      <FeedbackControls
        attempt={attempt}
        entries={feedbackEntries}
        busy={feedbackBusy}
        onSubmit={onFeedback}
        note={feedbackDraft}
        onNoteChange={onFeedbackDraftChange}
      />

      <div className="text-xs uppercase tracking-wide text-muted mb-1">
        Root cause
        {sourceLabel && <span className="ml-2 lowercase opacity-70">· {sourceLabel}</span>}
      </div>
      <p className="text-ink whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
        {attempt.root_cause || 'Analyzing…'}
      </p>

      <div className="text-xs uppercase tracking-wide text-muted mt-4 mb-1">Suggested solution</div>
      <p className="text-ink whitespace-pre-wrap break-words [overflow-wrap:anywhere]">
        {attempt.suggested_solution || '—'}
      </p>

      {showSnippet && (
        <div className="mt-4">
          <TerminalViewer
            text={attempt.redacted_snippet || ''}
            title="Redacted log snippet"
            errorCode={attempt.error_code || null}
            failingStep={attempt.failing_step || null}
            timestamp={when || null}
          />
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-3">
        <Button onClick={() => onReanalyze(attempt)} disabled={reanalyzing === attempt.unit_id}>
          {reanalyzing === attempt.unit_id ? 'Re-analyzing…' : 'Re-analyze this attempt'}
        </Button>
        {canClearCache && (
          <Button
            onClick={() => onClearCache(attempt)}
            disabled={clearingCache === attempt.analysis_cache_key}
          >
            {clearingCache === attempt.analysis_cache_key ? 'Clearing cache…' : 'Clear cached result'}
          </Button>
        )}
        <Button
          variant="ghost"
          onClick={() => onExport({
            unitId: attempt.unit_id,
            filename: `co-trace-unit-${attempt.serial_number || attempt.unit_id}.md`,
          })}
          disabled={exporting === attempt.unit_id}
        >
          {exporting === attempt.unit_id ? 'Exporting…' : 'Export packet'}
        </Button>
        {(attempt.knowledge_match_status !== 'matched' || attempt.unknown_acronyms?.length > 0) && (
          <Button
            variant="ghost"
            onClick={() => onReviewKnowledge?.({
              productCode: attempt.product_code,
              acronym: attempt.unknown_acronyms?.[0] || null,
              playbookId: attempt.playbook_id,
            })}
          >
            Review knowledge
          </Button>
        )}
      </div>
    </Panel>
  )
}

const FEEDBACK_ACTIONS = [
  ['helpful', 'Helpful'],
  ['not_helpful', 'Not helpful'],
  ['fixed_after_action', 'Fixed after action'],
  ['not_root_cause', 'Not root cause'],
]

function FeedbackControls({ attempt, entries, busy, onSubmit, note, onNoteChange }) {
  if (entries === null) {
    return (
      <div className="mb-4 border-y border-border/60 py-3 text-sm text-warning">
        Existing feedback is unavailable. Retry the feedback request above before adding a response.
      </div>
    )
  }
  const submit = async (action) => {
    try {
      await onSubmit(attempt, action, note)
    } catch {
      // The page-level action error carries the API message.
    }
  }

  return (
    <div className="mb-4 border-y border-border/60 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="text-xs uppercase tracking-wide text-muted">Engineer feedback</div>
        {entries.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {entries.slice(-3).map((entry) => (
              <Badge key={entry.feedback_id} tone={entry.action.includes('not_') ? 'warn' : 'pass'}>
                {FEEDBACK_ACTIONS.find(([value]) => value === entry.action)?.[1] || entry.action}
              </Badge>
            ))}
          </div>
        )}
      </div>
      <textarea
        value={note}
        maxLength={2000}
        onChange={(event) => onNoteChange?.(event.target.value)}
        placeholder="Optional engineer note"
        className="mt-3 min-h-20 w-full resize-y rounded-lg border border-border bg-surface px-3.5 py-2.5 text-sm text-ink placeholder-placeholder outline-none focus:border-accent focus-ring"
      />
      <div className="mt-2 flex flex-wrap gap-2">
        {FEEDBACK_ACTIONS.map(([action, label]) => (
          <Button
            key={action}
            variant="ghost"
            className="px-3 py-1.5"
            disabled={busy === `${attempt.unit_id}:${action}`}
            onClick={() => submit(action)}
          >
            {busy === `${attempt.unit_id}:${action}` ? 'Saving…' : label}
          </Button>
        ))}
      </div>
    </div>
  )
}

function ResourceNotice({ title, message, onRetry }) {
  return (
    <div role="status" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3">
      <div>
        <p className="text-sm font-semibold text-warning">{title}</p>
        <p className="mt-0.5 text-xs text-muted">{message}</p>
      </div>
      <Button variant="ghost" className="px-3 py-1.5" onClick={onRetry}>Retry</Button>
    </div>
  )
}

function ResourceErrorState({ title, message, onRetry }) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center">
      <IconWell className="h-16 w-16 mx-auto mb-6">
        <span className="font-display text-xl font-bold text-danger">!</span>
      </IconWell>
      <h2 className="font-display text-2xl font-bold text-ink">{title}</h2>
      <p role="alert" className="mt-2 text-muted">{message}</p>
      <Button variant="primary" className="mt-6" onClick={onRetry}>Retry</Button>
    </div>
  )
}

function EmptyState() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center">
      <IconWell className="h-20 w-20 mx-auto mb-6">
        <span className="text-2xl">🔧</span>
      </IconWell>
      <h2 className="font-display text-2xl font-bold text-ink">No batch loaded</h2>
      <p className="mt-2 text-muted">Upload logs on the Home tab to see unit diagnostics.</p>
    </div>
  )
}
