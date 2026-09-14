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

export default function Engineer({ jobId }) {
  const { isAdmin } = useAuth()
  const [units, setUnits] = useState([])
  const [runCount, setRunCount] = useState(0)
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [quickFilter, setQuickFilter] = useState('all')
  const [serialFilter, setSerialFilter] = useState('all')
  const [searchQuery, setSearchQuery] = useState('')
  const [sortBy, setSortBy] = useState('latest_failure')
  const [view, setView] = useState('table')
  const [expanded, setExpanded] = useState(null)
  const [reanalyzing, setReanalyzing] = useState(null)
  const [clearingCache, setClearingCache] = useState(null)
  const [clearingAll, setClearingAll] = useState(false)
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
          return matchesClass && matchesSerial && groupMatchesSearch(unit, searchQuery)
        })
        .sort(compareGroups(sortBy)),
    [filter, searchQuery, serialFilter, sortBy, units],
  )

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

  if (!jobId) return <EmptyState />

  const detailProps = {
    expanded,
    setExpanded,
    reanalyzing,
    onReanalyze: reanalyze,
    clearingCache,
    onClearCache: isAdmin ? clearCache : undefined,
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
          {(searchQuery || filter !== 'all' || serialFilter !== 'all') && (
            <Button
              variant="ghost"
              className="mt-3"
              onClick={() => {
                setSearchQuery('')
                setClassFilter('all')
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

const attemptsLabel = (u) =>
  u.failure_count > 0 ? `${u.attempt_count} · ${u.failure_count} failed` : `${u.attempt_count}`


function TableView({ units, expanded, setExpanded, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
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

function FailureBlock({ attempt, index, total, isFinal, showSnippet, reanalyzing, onReanalyze, clearingCache, onClearCache }) {
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
