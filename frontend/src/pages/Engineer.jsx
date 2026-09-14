import { Fragment, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { useAuth } from '../auth'
import {
  Badge,
  Button,
  Card,
  IconWell,
  Input,
  MetricCard,
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

const groupAttempts = (group) => [group.final, ...(group.failures || [])].filter(Boolean)

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

export default function Engineer({ jobId, drillDown, onClearDrillDown, onReviewKnowledge }) {
  const { isAdmin } = useAuth()
  const [units, setUnits] = useState([])
  const [clusters, setClusters] = useState([])
  const [runCount, setRunCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [quickFilter, setQuickFilter] = useState('all')
  const [serialFilter, setSerialFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState('latest_failure')
  const [activeSignature, setActiveSignature] = useState(null)
  const [view, setView] = useState('table')
  const [expanded, setExpanded] = useState(null)
  const [reanalyzing, setReanalyzing] = useState(null)
  const [clearingCache, setClearingCache] = useState(null)
  const [clearingAll, setClearingAll] = useState(false)
  const [exporting, setExporting] = useState(null)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    setActiveSignature(null)
    Promise.all([api.units(jobId), api.clusters(jobId).catch(() => ({ clusters: [] }))]).then(
      ([unitData, clusterData]) => {
      setUnits(unitData.units)
      setClusters(clusterData.clusters || [])
      setRunCount(unitData.run_count ?? unitData.units.length)
      setLoading(false)
      },
    )
  }, [jobId])

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

  const shown = useMemo(
    () =>
      units
        .filter((unit) => {
          const serial = unit.serial_number || unit.unit_id
          const matchesClass = filter === 'all' || unit.classification === filter
          const matchesSerial = serialFilter === 'all' || serial === serialFilter
          const matchesSignature =
            !activeSignature ||
            unit.failures?.some((failure) => failure.signature === activeSignature)
          const matchesStation =
            !drillDown?.station_id ||
            groupAttempts(unit).some(
              (attempt) =>
                attempt.station_id === drillDown.station_id &&
                (!drillDown.host || attempt.host === drillDown.host),
            )
          const matchesLot =
            !drillDown?.lot_id ||
            groupAttempts(unit).some((attempt) => attempt.lot_id === drillDown.lot_id)
          return (
            matchesClass &&
            matchesSerial &&
            matchesSignature &&
            matchesStation &&
            matchesLot &&
            groupMatchesSearch(unit, searchQuery)
          )
        })
        .sort(compareGroups(sortBy)),
    [activeSignature, drillDown, filter, searchQuery, serialFilter, sortBy, units],
  )

  const drillDownStats = useMemo(() => {
    if (!drillDown) return null
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
    return { attempts, units: matchingUnits.length }
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

      {!loading && (
        <div className="mb-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <MetricCard label="Still failing" value={triageSummary.failing} tone="fail" />
          <MetricCard label="Retry-pass" value={triageSummary.retryPass} tone="warn" />
          <MetricCard
            label="Top failure"
            value={triageSummary.topFailure}
            className="[&_div:nth-child(2)]:break-words [&_div:nth-child(2)]:text-lg"
          />
          <MetricCard
            label="DebugLog missing"
            value={triageSummary.missingDebugLog}
            tone="warn"
          />
          <MetricCard
            label="Knowledge coverage"
            value={triageSummary.knowledgeCoverage}
            tone="accent"
          />
          <MetricCard
            label="Newest failure"
            value={triageSummary.newestFailure}
            className="[&_div:nth-child(2)]:text-lg"
          />
        </div>
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

      {drillDown && drillDownStats && (
        <div className="mb-4 flex items-center gap-3">
          <Badge tone="accent">
            From Manager: {drillDown.label || 'selection'} · {drillDownStats.attempts} attempt{drillDownStats.attempts === 1 ? '' : 's'}
            {drillDownStats.attempts !== drillDownStats.units
              ? ` across ${drillDownStats.units} units`
              : ''}
          </Badge>
          <Button variant="ghost" className="px-2 py-1" onClick={clearDrillDown}>
            Clear
          </Button>
        </div>
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

      <div className="flex flex-wrap items-center justify-between gap-4 mb-6">
        <div className="flex flex-wrap items-center gap-2">
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
            className="rounded-lg border border-border bg-surface px-3.5 py-2 text-sm font-medium text-ink-2 focus-ring"
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

      <div className="mb-6 grid gap-3 sm:grid-cols-[minmax(0,1fr)_220px]">
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

      {actionError && (
        <div className="mb-4 rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          {actionError}
        </div>
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
      ) : view === 'table' ? (
        <TableView units={shown} {...detailProps} />
      ) : (
        <CardsView units={shown} {...detailProps} />
      )}
    </div>
  )
}

function ClusterPanel({ clusters, activeSignature, exporting, onSelect, onExport }) {
  return (
    <section className="mb-6" aria-labelledby="failure-families-heading">
      <div className="mb-3 flex items-end justify-between gap-4">
        <div>
          <h2 id="failure-families-heading" className="font-display text-lg font-bold text-ink">
            Failure families
          </h2>
          <p className="text-sm text-muted">Grouped by normalized error signature.</p>
        </div>
        <span className="text-xs text-muted">{clusters.length} families</span>
      </div>
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {clusters.map((cluster) => {
          const selected = activeSignature === cluster.signature
          const knowledge = Object.entries(cluster.knowledge_status_summary || {})
            .map(([status, count]) => `${count} ${status.replaceAll('_', ' ')}`)
            .join(', ')
          const sources = Object.entries(cluster.analysis_source_summary || {})
            .map(([source, count]) => `${count} ${source}`)
            .join(', ')
          const lastSeen = cluster.last_seen
            ? new Date(cluster.last_seen).toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
            : 'Unknown'
          return (
            <div
              key={cluster.signature}
              className={[
                'min-w-0 rounded-panel border p-4 text-left transition-colors',
                selected
                  ? 'border-accent bg-accent/10'
                  : 'border-border bg-surface hover:border-border-strong hover:bg-surface-2',
              ].join(' ')}
            >
              <button
                type="button"
                onClick={() => onSelect(selected ? null : cluster.signature)}
                className="block w-full text-left focus-ring"
              >
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0">
                  <div className="font-semibold text-ink break-words [overflow-wrap:anywhere]">
                    {cluster.error_code || 'Unknown failure'}
                  </div>
                  <div className="mt-1 line-clamp-2 text-sm text-muted break-words [overflow-wrap:anywhere]">
                    {cluster.error_message || 'No error message'}
                  </div>
                </div>
                <Badge tone="fail">{cluster.count}</Badge>
              </div>
              <div className="mt-3 space-y-1 text-xs text-muted">
                <div>{cluster.stations?.join(', ') || 'No station'} · {cluster.lots?.join(', ') || 'No lot'}</div>
                <div>{knowledge || 'Knowledge status unavailable'}</div>
                <div>{sources || 'Analysis source unavailable'}</div>
                <div>Latest: {lastSeen}</div>
              </div>
              </button>
              <Button
                variant="ghost"
                className="mt-3 px-2 py-1"
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
      </div>
    </section>
  )
}

const attemptsLabel = (u) =>
  u.failure_count > 0 ? `${u.attempt_count} · ${u.failure_count} failed` : `${u.attempt_count}`


function TableView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge }) {
  return (
    <TableShell tableClassName="table-fixed min-w-[760px]">
      <colgroup>
        <col className="w-[14%]" />
        <col className="w-[24%]" />
        <col className="w-[18%]" />
        <col className="w-[14%]" />
        <col className="w-[14%]" />
        <col className="w-[16%]" />
      </colgroup>
      <thead>
        <tr className="border-b border-border bg-surface-2 text-left text-muted">
          <th className="px-4 py-3 font-medium">Status</th>
          <th className="px-4 py-3 font-medium">Serial</th>
          <th className="px-4 py-3 font-medium">Station</th>
          <th className="px-4 py-3 font-medium text-right">Attempts</th>
          <th className="px-4 py-3 font-medium text-right">Duration</th>
          <th className="px-4 py-3 font-medium text-right">Actions</th>
        </tr>
      </thead>
      <tbody>
        {units.map((u) => {
          const hasDetails = u.failure_count > 0
          return (
            <Fragment key={u.unit_id}>
              <tr className="border-b border-border/60 text-ink transition-colors hover:bg-surface-2/60">
                <td className="px-4 py-3 whitespace-nowrap">
                  <StatusBadge status={u.classification} />
                </td>
                <td className="px-4 py-3 whitespace-nowrap font-medium">
                  {u.serial_number || u.unit_id}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">{u.final.station_id || '—'}</td>
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
                  <td colSpan={6} className="max-w-0 overflow-hidden bg-surface-2 px-4 pb-5 pt-1">
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

function CardsView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge }) {
  return (
    <div className="space-y-4">
      {units.map((u) => {
        const hasDetails = u.failure_count > 0
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
                  <span>Station: {u.final.station_id || '—'}</span>
                  <span>Attempts: {attemptsLabel(u)}</span>
                  {u.final.duration_s ? <span>{u.final.duration_s.toFixed(1)}s</span> : null}
                </div>
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
                />
              </div>
            )}
          </Card>
        )
      })}
    </div>
  )
}

function UnitDetails({ u, showSnippet = true, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge }) {
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
        <Badge tone={attempt.analysis_source === 'stub' ? 'warn' : 'muted'}>
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

function FailureBlock({ attempt, index, total, isFinal, showSnippet, reanalyzing, onReanalyze, clearingCache, onClearCache, exporting, onExport, onReviewKnowledge }) {
  const canClearCache =
    !!onClearCache &&
    attempt.analysis_cache_key && ['llm', 'local-cache'].includes(attempt.analysis_source)
  const sourceLabel = attempt.cache_cleared ? 'cache cleared' : attempt.analysis_source
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
      <StructuredRca attempt={attempt} />

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
            })}
          >
            Review knowledge
          </Button>
        )}
      </div>
    </Panel>
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
