import { Fragment, useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Badge, Button, Card, IconWell } from '../components/ui'

const toneOf = (r) => (r === 'PASS' ? 'pass' : r === 'FAIL' ? 'fail' : 'unknown')

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
    const c = { all: units.length, PASS: 0, FAIL: 0, UNKNOWN: 0 }
    units.forEach((u) => (c[u.result] = (c[u.result] || 0) + 1))
    return c
  }, [units])

  const serials = useMemo(
    () =>
      Array.from(new Set(units.map((u) => u.serial_number || u.unit_id).filter(Boolean))).sort(),
    [units],
  )

  const setResultFilter = (result) => {
    setFilter(result)
    setSerialFilter('all')
    setQuickFilter(result === 'all' ? 'all' : `result:${result}`)
  }

  const setDropdownFilter = (value) => {
    setQuickFilter(value)
    if (value === 'all') {
      setFilter('all')
      setSerialFilter('all')
      return
    }
    if (value.startsWith('result:')) {
      setFilter(value.slice('result:'.length))
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
    const matchesResult = filter === 'all' || u.result === filter
    const matchesSerial = serialFilter === 'all' || serial === serialFilter
    return matchesResult && matchesSerial
  })

  const reanalyze = async (unit) => {
    setReanalyzing(unit.unit_id)
    setActionError('')
    try {
      const updated = await api.reanalyze(jobId, unit.unit_id)
      setUnits((prev) => prev.map((u) => (u.unit_id === unit.unit_id ? updated : u)))
    } catch (err) {
      setActionError(err.message)
    } finally {
      setReanalyzing(null)
    }
  }

  const clearCache = async (unit) => {
    if (!unit.analysis_cache_key) return
    setClearingCache(unit.analysis_cache_key)
    setActionError('')
    try {
      await api.clearAnalysisCache(unit.analysis_cache_key)
      setUnits((prev) =>
        prev.map((u) =>
          u.analysis_cache_key === unit.analysis_cache_key
            ? { ...u, analysis_cache_key: null, cache_cleared: true }
            : u,
        ),
      )
    } catch (err) {
      setActionError(err.message)
    } finally {
      setClearingCache(null)
    }
  }

  if (!jobId) return <EmptyState />

  return (
    <div className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="font-display text-4xl font-extrabold tracking-tight text-ink mb-8">
        Engineer view
      </h1>
      {!loading && runCount > units.length && (
        <p className="mb-5 text-sm text-muted">
          Showing latest result for {units.length} serial numbers from {runCount} test runs.
        </p>
      )}

      <div className="flex flex-wrap items-center justify-between gap-4 mb-8">
        <div className="flex flex-wrap gap-3">
          {[
            ['all', 'All'],
            ['FAIL', 'Failed'],
            ['PASS', 'Passed'],
            ['UNKNOWN', 'Unknown'],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setResultFilter(key)}
              className={[
                'rounded-2xl px-5 py-2.5 text-sm font-medium transition-all duration-300 focus-ring',
                filter === key
                  ? 'bg-base text-accent shadow-inset'
                  : 'bg-base text-muted shadow-extruded-sm hover:-translate-y-px',
              ].join(' ')}
            >
              {label} <span className="opacity-60">({counts[key] ?? 0})</span>
            </button>
          ))}
          <select
            value={quickFilter}
            onChange={(event) => setDropdownFilter(event.target.value)}
            className="rounded-2xl bg-base px-5 py-2.5 text-sm font-medium text-muted shadow-extruded-sm focus-ring"
          >
            <option value="all">All units</option>
            <option value="result:FAIL">Failed units</option>
            <option value="result:PASS">Passed units</option>
            <optgroup label="Serial number">
              {serials.map((serial) => (
                <option key={serial} value={`serial:${serial}`}>
                  {serial}
                </option>
              ))}
            </optgroup>
          </select>
        </div>

        <div className="flex items-center gap-1 rounded-2xl bg-base shadow-inset-sm p-1 shrink-0">
          {[
            ['table', 'Table'],
            ['cards', 'Cards'],
          ].map(([key, label]) => (
            <button
              key={key}
              onClick={() => setView(key)}
              className={[
                'rounded-xl px-4 py-2 text-sm font-medium transition-all duration-300 focus-ring',
                view === key
                  ? 'bg-base text-accent shadow-extruded-sm'
                  : 'text-muted hover:text-ink',
              ].join(' ')}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {actionError && <Card className="p-4 mb-4 text-sm text-danger">{actionError}</Card>}

      {loading ? (
        <Card className="p-10 text-center text-muted">Loading units…</Card>
      ) : shown.length === 0 ? (
        <Card className="p-10 text-center text-muted">No units in this filter.</Card>
      ) : view === 'table' ? (
        <TableView
          units={shown}
          expanded={expanded}
          setExpanded={setExpanded}
          reanalyzing={reanalyzing}
          onReanalyze={reanalyze}
          clearingCache={clearingCache}
          onClearCache={clearCache}
        />
      ) : (
        <CardsView
          units={shown}
          expanded={expanded}
          setExpanded={setExpanded}
          reanalyzing={reanalyzing}
          onReanalyze={reanalyze}
          clearingCache={clearingCache}
          onClearCache={clearCache}
        />
      )}
    </div>
  )
}

function TableView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
  return (
    <Card className="p-6 md:p-8">
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted text-left">
              <th className="pb-3 font-medium">Result</th>
              <th className="pb-3 font-medium">Serial</th>
              <th className="pb-3 font-medium">Station</th>
              <th className="pb-3 font-medium">Lot</th>
              <th className="pb-3 font-medium text-right">Duration</th>
              <th className="pb-3 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {units.map((u) => (
              <Fragment key={u.unit_id}>
                <tr className="text-ink border-t border-ink/5">
                  <td className="py-3 whitespace-nowrap">
                    <Badge tone={toneOf(u.result)}>{u.result}</Badge>
                  </td>
                  <td className="py-3 whitespace-nowrap font-medium">
                    {u.serial_number || u.unit_id}
                  </td>
                  <td className="py-3 whitespace-nowrap">{u.station_id || '—'}</td>
                  <td className="py-3 whitespace-nowrap">{u.lot_id || '—'}</td>
                  <td className="py-3 text-right whitespace-nowrap">
                    {u.duration_s ? `${u.duration_s.toFixed(1)}s` : '—'}
                  </td>
                  <td className="py-3 text-right whitespace-nowrap">
                    {u.result === 'FAIL' ? (
                      <button
                        className="text-muted hover:text-ink focus-ring rounded-lg px-2 py-1"
                        onClick={() => setExpanded(expanded === u.unit_id ? null : u.unit_id)}
                      >
                        {expanded === u.unit_id ? 'Hide' : 'Details'}
                      </button>
                    ) : (
                      <span className="text-placeholder">—</span>
                    )}
                  </td>
                </tr>
                {u.result === 'FAIL' && expanded === u.unit_id && (
                  <tr>
                    <td colSpan={6} className="pb-5 pt-1">
                      <FailDetails
                        u={u}
                        showSnippet
                        reanalyzing={reanalyzing}
                        onReanalyze={onReanalyze}
                        clearingCache={clearingCache}
                        onClearCache={onClearCache}
                      />
                    </td>
                  </tr>
                )}
              </Fragment>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  )
}

function CardsView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
  return (
    <div className="space-y-4">
      {units.map((u) => (
        <Card key={u.unit_id} className="p-6">
          <div className="flex items-start justify-between gap-4">
            <div className="min-w-0">
              <div className="flex items-center gap-3 flex-wrap">
                <Badge tone={toneOf(u.result)}>{u.result}</Badge>
                <span className="font-display font-bold text-ink truncate">
                  {u.serial_number || u.unit_id}
                </span>
              </div>
              <div className="mt-2 text-sm text-muted flex flex-wrap gap-x-6 gap-y-1">
                <span>Product: {u.product_code || '—'}</span>
                <span>Station: {u.station_id || '—'}</span>
                <span>Lot: {u.lot_id || '—'}</span>
                {u.duration_s ? <span>{u.duration_s.toFixed(1)}s</span> : null}
              </div>
            </div>
            {u.result === 'FAIL' && (
              <button
                className="shrink-0 text-sm text-muted hover:text-ink focus-ring rounded-lg px-2 py-1"
                onClick={() => setExpanded(expanded === u.unit_id ? null : u.unit_id)}
              >
                {expanded === u.unit_id ? 'Hide' : 'Details'}
              </button>
            )}
          </div>

          {u.result === 'FAIL' && (
            <div className="mt-5">
              <FailDetails
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
      ))}
    </div>
  )
}

function FailDetails({ u, showSnippet, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
  const canClearCache = u.analysis_cache_key && ['llm', 'local-cache'].includes(u.analysis_source)
  const sourceLabel = u.cache_cleared ? 'cache cleared' : u.analysis_source

  return (
    <div className="rounded-2xl bg-base shadow-inset p-5">
      <div className="text-xs uppercase tracking-wide text-muted mb-1">
        Root cause
        {sourceLabel && (
          <span className="ml-2 lowercase opacity-70">· {sourceLabel}</span>
        )}
      </div>
      <p className="text-ink">{u.root_cause || 'Analyzing…'}</p>

      <div className="text-xs uppercase tracking-wide text-muted mt-4 mb-1">
        Suggested solution
      </div>
      <p className="text-ink">{u.suggested_solution || '—'}</p>

      {showSnippet && (
        <div className="mt-4">
          <div className="text-xs uppercase tracking-wide text-muted mb-2">
            Redacted log snippet
          </div>
          <pre className="rounded-xl bg-base shadow-inset-sm p-4 text-xs text-ink overflow-x-auto whitespace-pre-wrap">
            {u.redacted_snippet || '(none)'}
          </pre>
        </div>
      )}

      <div className="mt-4 flex flex-wrap gap-3">
        <Button onClick={() => onReanalyze(u)} disabled={reanalyzing === u.unit_id}>
          {reanalyzing === u.unit_id ? 'Re-analyzing…' : 'Re-analyze this unit'}
        </Button>
        {canClearCache && (
          <Button onClick={() => onClearCache(u)} disabled={clearingCache === u.analysis_cache_key}>
            {clearingCache === u.analysis_cache_key ? 'Clearing cache…' : 'Clear cached result'}
          </Button>
        )}
      </div>
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
