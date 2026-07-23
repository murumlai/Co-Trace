import { Fragment, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import {
  Badge,
  Button,
  Card,
  IconWell,
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

const fmtTs = (iso) => (iso ? iso.replace('T', ' ').slice(0, 16) : '—')

export default function Engineer({ jobId }) {
  const [units, setUnits] = useState([])
  const [runCount, setRunCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [quickFilter, setQuickFilter] = useState('all')
  const [serialFilter, setSerialFilter] = useState('all')
  const [view, setView] = useState('table')
  const [expanded, setExpanded] = useState(null)
  const [reanalyzing, setReanalyzing] = useState(null)
  const [clearingCache, setClearingCache] = useState(null)
  const [actionError, setActionError] = useState('')

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    api.units(jobId).then((d) => {
      setUnits(d.units)
      setRunCount(d.run_count ?? d.units.length)
      setLoading(false)
    })
  }, [jobId])

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

  const shown = units.filter((u) => {
    const serial = u.serial_number || u.unit_id
    const matchesClass = filter === 'all' || u.classification === filter
    const matchesSerial = serialFilter === 'all' || serial === serialFilter
    return matchesClass && matchesSerial
  })

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

  if (!jobId) return <EmptyState />

  const detailProps = {
    expanded,
    setExpanded,
    reanalyzing,
    onReanalyze: reanalyze,
    clearingCache,
    onClearCache: clearCache,
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

      {loading ? (
        <Card className="p-10 text-center text-muted">Loading units…</Card>
      ) : shown.length === 0 ? (
        <Card className="p-10 text-center text-muted">No units in this filter.</Card>
      ) : view === 'table' ? (
        <TableView units={shown} {...detailProps} />
      ) : (
        <CardsView units={shown} {...detailProps} />
      )}
    </div>
  )
}

const attemptsLabel = (u) =>
  u.failure_count > 0 ? `${u.attempt_count} · ${u.failure_count} failed` : `${u.attempt_count}`


function TableView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
  return (
    <TableShell>
      <thead>
        <tr className="border-b border-border bg-surface-2 text-left text-muted">
          <th className="px-4 py-3 font-medium">Status</th>
          <th className="px-4 py-3 font-medium">Timestamp</th>
          <th className="px-4 py-3 font-medium">Serial</th>
          <th className="px-4 py-3 font-medium">Product</th>
          <th className="px-4 py-3 font-medium">Station</th>
          <th className="px-4 py-3 font-medium">Lot</th>
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
                <td className="px-4 py-3 whitespace-nowrap text-muted">{fmtTs(u.final.start_time)}</td>
                <td className="px-4 py-3 whitespace-nowrap font-medium">
                  {u.serial_number || u.unit_id}
                </td>
                <td className="px-4 py-3 whitespace-nowrap">{u.final.product_code || '—'}</td>
                <td className="px-4 py-3 whitespace-nowrap">{u.final.station_id || '—'}</td>
                <td className="px-4 py-3 whitespace-nowrap">{u.final.lot_id || '—'}</td>
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
                  <td colSpan={9} className="bg-surface-2 px-4 pb-5 pt-1">
                    <UnitDetails
                      u={u}
                      reanalyzing={reanalyzing}
                      onReanalyze={onReanalyze}
                      clearingCache={clearingCache}
                      onClearCache={onClearCache}
                    />
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

function CardsView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
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
                  <span>{fmtTs(u.final.start_time)}</span>
                  <span>Product: {u.final.product_code || '—'}</span>
                  <span>Station: {u.final.station_id || '—'}</span>
                  <span>Lot: {u.final.lot_id || '—'}</span>
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
                />
              </div>
            )}
          </Card>
        )
      })}
    </div>
  )
}

function UnitDetails({ u, showSnippet = true, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
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
        />
      ))}
    </div>
  )
}

function FailureBlock({ attempt, index, total, isFinal, showSnippet, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
  const canClearCache =
    attempt.analysis_cache_key && ['llm', 'local-cache'].includes(attempt.analysis_source)
  const sourceLabel = attempt.cache_cleared ? 'cache cleared' : attempt.analysis_source
  const when = attempt.start_time ? attempt.start_time.replace('T', ' ').slice(0, 19) : null

  return (
    <Panel className="p-5">
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
          <span className="text-xs text-muted">step: {attempt.failing_step}</span>
        )}
      </div>

      {(attempt.error_code || attempt.error_message) && (
        <p className="text-xs text-muted mb-3">
          {attempt.error_code ? `${attempt.error_code}: ` : ''}
          {attempt.error_message || ''}
        </p>
      )}

      <div className="text-xs uppercase tracking-wide text-muted mb-1">
        Root cause
        {sourceLabel && <span className="ml-2 lowercase opacity-70">· {sourceLabel}</span>}
      </div>
      <p className="text-ink">{attempt.root_cause || 'Analyzing…'}</p>

      <div className="text-xs uppercase tracking-wide text-muted mt-4 mb-1">Suggested solution</div>
      <p className="text-ink">{attempt.suggested_solution || '—'}</p>

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
