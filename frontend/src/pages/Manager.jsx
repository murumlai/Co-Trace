import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ComposedChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api'
import { Button, Card, IconWell, MetricCard } from '../components/ui'
import { additionalAttemptMetric, firstObservedPassMetric, formatRate, latestObservedYieldMetric } from '../managerMetrics'
import { DEFAULT_MANAGER_SCOPE } from '../workspaceState'

const AXIS = { fill: 'rgb(var(--color-muted))', fontSize: 12, fontFamily: 'DM Sans' }
const GRID = 'rgb(var(--color-grid))'
const ACCENT = 'rgb(var(--color-accent))'
const TEAL = 'rgb(var(--color-teal))'
const DANGER = 'rgb(var(--color-danger))'
const WARNING = 'rgb(var(--color-warning))'

const tooltipStyle = {
  background: 'rgb(var(--color-surface))',
  border: '1px solid rgb(var(--color-border))',
  borderRadius: 8,
  boxShadow: 'var(--shadow-md)',
  color: 'rgb(var(--color-ink))',
  fontSize: 12,
}

function ChartCard({ title, subtitle, children }) {
  return (
    <Card className="min-w-0 overflow-hidden p-6">
      <div className="mb-5">
        <h3 className="font-display font-bold text-ink">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {children}
    </Card>
  )
}

export default function Manager({ jobId, onDrillDown, scope = DEFAULT_MANAGER_SCOPE, onScopeChange }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)
  const [lotSort, setLotSort] = useState({ key: 'yield', direction: 'asc' })

  useEffect(() => {
    if (!jobId) {
      setLoading(false)
      return undefined
    }
    let active = true
    setLoading(true)
    setError('')
    api.manager(jobId, scope).then(
      (nextData) => {
        if (active) setData(nextData)
      },
      (requestError) => {
        if (active) setError(requestError.message)
      },
    ).finally(() => {
      if (active) setLoading(false)
    })
    return () => {
      active = false
    }
  }, [jobId, reload, scope])

  if (!jobId) return <EmptyState />
  if (loading && !data)
    return (
      <div className="mx-auto max-w-6xl px-6 py-12">
        <Card role="status" className="p-10 text-center text-muted">Loading metrics…</Card>
      </div>
    )
  if (error && !data) {
    return (
      <div className="mx-auto max-w-2xl px-6 py-24 text-center">
        <IconWell className="h-16 w-16 mx-auto mb-6">
          <span className="font-display text-xl font-bold text-danger">!</span>
        </IconWell>
        <h2 className="font-display text-2xl font-bold text-ink">Manager metrics unavailable</h2>
        <p role="alert" className="mt-2 text-muted">{error}</p>
        <button
          type="button"
          onClick={() => setReload((value) => value + 1)}
          className="mt-6 rounded-lg bg-accent px-4 py-2.5 text-sm font-medium text-white shadow-sm hover:bg-accent-hover focus-ring"
        >
          Retry
        </button>
      </div>
    )
  }
  if (!data) return <EmptyMetricsState />

  const s = data.summary
  const topFailure = data.pareto && data.pareto.length ? data.pareto[0] : null
  const firstObservedPass = firstObservedPassMetric(s)
  const latestObservedYield = latestObservedYieldMetric(s)
  const additionalAttempts = additionalAttemptMetric(s)
  const batch = data.batch || {}
  const scoped = data.scope || { options: { products: [], lots: [], stations: [] } }
  const activeScopeCount = scope.products.length + scope.lots.length + scope.stations.length + (scope.startTime ? 1 : 0) + (scope.endTime ? 1 : 0)
  const sortedLots = (() => {
    const direction = lotSort.direction === 'asc' ? 1 : -1
    return [...(data.lots || [])].sort((left, right) => {
      const result = lotSort.key === 'lot'
        ? String(left.lot).localeCompare(String(right.lot))
        : Number(left[lotSort.key] || 0) - Number(right[lotSort.key] || 0)
      return result * direction
    })
  })()
  const changeLotSort = (key) => setLotSort((current) => ({
    key,
    direction: current.key === key && current.direction === 'asc' ? 'desc' : 'asc',
  }))

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-6">
        <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">
          {batch.display_name || 'Manager view'}
        </h1>
        <p className="mt-1 text-sm text-muted">
          Latest unit outcomes and attempt-level results for this uploaded batch.
        </p>
      </div>

      <BatchQualityStatus batch={batch} />
      <ScopeControls
        scope={scope}
        options={scoped.options || { products: [], lots: [], stations: [] }}
        activeCount={activeScopeCount}
        loading={loading}
        onChange={onScopeChange}
      />

      {loading && <p role="status" className="mb-4 text-sm text-muted">Updating selected scope…</p>}
      {error && (
        <div role="alert" className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
          <span>{error}. Showing the previous scope.</span>
          <Button variant="ghost" className="px-3 py-1.5" onClick={() => setReload((value) => value + 1)}>Retry</Button>
        </div>
      )}
      {scoped.missing_timestamp_excluded > 0 && (
        <div className="mb-4 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-warning">
          {scoped.missing_timestamp_excluded} attempt{scoped.missing_timestamp_excluded === 1 ? '' : 's'} excluded because the selected time range could not be compared to its timestamp.
        </div>
      )}

      {!s.total_runs ? (
        <EmptyMetricsState scoped />
      ) : (
      <>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard
          label="First observed pass rate"
          value={firstObservedPass.value}
          tone="accent"
          hint={firstObservedPass.hint}
        />
        <MetricCard label="Latest observed unit yield" value={latestObservedYield.value} tone="pass" hint={latestObservedYield.hint} />
        <MetricCard label="Still-failing units" value={s.failed} tone="fail" hint={`${s.failed}/${s.unique_units} observed units`} />
        <MetricCard label="Additional-attempt share" value={additionalAttempts.value} tone="warn" hint={additionalAttempts.hint} />
        <MetricCard label="Test attempts" value={s.total_runs} hint={`${s.retests} additional attempts`} />
        <MetricCard label="Observed units" value={s.unique_units} />
        <MetricCard label="Recovered after retry" value={s.recovered_after_retry || 0} tone="pass" hint="Latest outcome passed after an observed first failure" />
        <MetricCard label="Latest unknown units" value={s.unknown || 0} hint={`${s.unknown || 0}/${s.unique_units} observed units`} />
        {topFailure && (
          <MetricCard
            label="Top failed-attempt family"
            value={`${topFailure.pct}%`}
            tone="fail"
            hint={`${topFailure.reason} · ${topFailure.count} failed attempts`}
          />
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <ChartCard title="Attempt pass-rate trend" subtitle="PASS attempts / PASS + FAIL attempts by day">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={data.trend} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} unit="%" />
              <Tooltip contentStyle={tooltipStyle} />
              <Line
                type="monotone"
                dataKey="yield"
                stroke={ACCENT}
                strokeWidth={2.5}
                dot={{ fill: ACCENT, r: 3 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Failed-attempt Pareto" subtitle="Failed attempts with cumulative share">
          <ResponsiveContainer width="100%" height={280}>
            <ComposedChart data={data.pareto} margin={{ top: 5, right: 4, left: -10, bottom: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="reason" tick={false} axisLine={false} tickLine={false} />
              <YAxis yAxisId="left" tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
              <YAxis
                yAxisId="right"
                orientation="right"
                domain={[0, 100]}
                unit="%"
                tick={AXIS}
                tickLine={false}
                axisLine={false}
              />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar yAxisId="left" dataKey="count" name="Failed attempts" fill={ACCENT} radius={[6, 6, 0, 0]} />
              <Line
                yAxisId="right"
                type="monotone"
                dataKey="cum_pct"
                name="Cumulative %"
                stroke={WARNING}
                strokeWidth={2}
                dot={{ fill: WARNING, r: 3 }}
              />
            </ComposedChart>
          </ResponsiveContainer>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[30rem] text-sm">
              <thead><tr className="border-b border-border text-left text-muted"><th className="pb-2 font-medium">Rank</th><th className="pb-2 font-medium">Failure family</th><th className="pb-2 text-right font-medium">Attempts</th><th className="pb-2 text-right font-medium">Share</th><th className="pb-2 text-right font-medium">Cumulative</th></tr></thead>
              <tbody>
            {data.pareto.map((p, index) => (
              <tr key={p.signature} className="border-b border-border/60 last:border-0">
                <td className="py-2 text-muted">{index + 1}</td>
                <td className="py-2">
                <button
                  type="button"
                  onClick={() => onDrillDown({
                    signature: p.signature,
                    label: p.reason,
                    attempt_ids: p.attempt_ids || [],
                    unit_ids: p.unit_ids || [],
                  })}
                  className="max-w-[22rem] truncate rounded-md px-1 py-1 text-left text-ink-2 hover:bg-surface-2 focus-ring"
                  title={p.reason}
                >
                  {p.reason}
                </button>
                </td>
                <td className="py-2 text-right">{p.count}</td>
                <td className="py-2 text-right">{p.pct}%</td>
                <td className="py-2 text-right">{p.cum_pct}%</td>
              </tr>
            ))}
              </tbody>
            </table>
          </div>
          {data.pareto.length > 0 && (
            <p className="mt-3 text-xs text-muted">Showing up to the top 10 failure families. Shares use all failed attempts in scope; visible cumulative share may be below 100%.</p>
          )}
        </ChartCard>

        <ChartCard title="Station / tester attempts" subtitle="PASS vs FAIL attempts per station">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data.stations} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="4 4" vertical={false} />
              <XAxis dataKey="station" tick={false} axisLine={false} tickLine={false} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="pass" name="Pass" stackId="a" fill={TEAL} />
              <Bar dataKey="fail" name="Fail" stackId="a" fill={DANGER} radius={[6, 6, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[28rem] text-sm">
              <thead><tr className="border-b border-border text-left text-muted"><th className="pb-2 font-medium">Station / tester</th><th className="pb-2 text-right font-medium">Volume</th><th className="pb-2 text-right font-medium">PASS</th><th className="pb-2 text-right font-medium">FAIL</th><th className="pb-2 text-right font-medium">Failure rate</th></tr></thead>
              <tbody>
            {data.stations.map((station) => (
              <tr key={`${station.host || ''}:${station.station_id || ''}`} className="border-b border-border/60 last:border-0">
                <td className="py-2">
                <button
                  type="button"
                  onClick={() => onDrillDown({
                    station_id: station.station_id,
                    host: station.host,
                    label: station.station,
                    attempt_ids: station.attempt_ids || [],
                    unit_ids: station.unit_ids || [],
                  })}
                  className="max-w-64 truncate rounded-md px-1 py-1 text-left text-ink-2 hover:bg-surface-2 focus-ring"
                  title={station.station}
                >
                  {station.station}
                </button>
                </td>
                <td className="py-2 text-right">{station.total}</td>
                <td className="py-2 text-right text-teal">{station.pass}</td>
                <td className="py-2 text-right text-danger">{station.fail}</td>
                <td className="py-2 text-right font-medium">{formatRate(station.total ? (station.fail / station.total) * 100 : 0, station.total)}</td>
              </tr>
            ))}
              </tbody>
            </table>
          </div>
        </ChartCard>

        <ChartCard title="Lot-to-lot attempt comparison" subtitle="Attempt pass rate by lot">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted text-left border-b border-border">
                  <th className="pb-2 font-medium"><SortButton label="Lot" column="lot" sort={lotSort} onChange={changeLotSort} /></th>
                  <th className="pb-2 font-medium text-right">PASS attempts</th>
                  <th className="pb-2 font-medium text-right"><SortButton label="FAIL attempts" column="fail" sort={lotSort} onChange={changeLotSort} /></th>
                  <th className="pb-2 font-medium text-right"><SortButton label="Pass rate" column="yield" sort={lotSort} onChange={changeLotSort} /></th>
                </tr>
              </thead>
              <tbody>
                {sortedLots.map((l) => (
                  <tr
                    key={l.lot}
                    className="cursor-pointer text-ink border-b border-border/60 last:border-0 hover:bg-surface-2"
                    onClick={() => onDrillDown({
                      lot_id: l.lot,
                      label: l.lot,
                      attempt_ids: l.attempt_ids || [],
                      unit_ids: l.unit_ids || [],
                    })}
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onDrillDown({
                          lot_id: l.lot,
                          label: l.lot,
                          attempt_ids: l.attempt_ids || [],
                          unit_ids: l.unit_ids || [],
                        })
                      }
                    }}
                  >
                    <td className="py-2 truncate">{l.lot}</td>
                    <td className="py-2 text-right text-teal">{l.pass}</td>
                    <td className="py-2 text-right text-danger">{l.fail}</td>
                    <td className="py-2 text-right font-semibold">{formatRate(l.yield, l.total)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </ChartCard>
      </div>
      </>
      )}
    </div>
  )
}

function SortButton({ label, column, sort, onChange }) {
  const active = sort.key === column
  return (
    <button type="button" onClick={() => onChange(column)} className="rounded px-1 py-0.5 hover:bg-surface-2 focus-ring" aria-label={`Sort by ${label}`}>
      {label}{active ? (sort.direction === 'asc' ? ' ↑' : ' ↓') : ''}
    </button>
  )
}

function ScopeControls({ scope, options, activeCount, loading, onChange }) {
  const setSingle = (field, value) => onChange?.({ ...scope, [field]: value ? [value] : [] })
  const setTime = (field, value) => onChange?.({ ...scope, [field]: value })
  return (
    <section className="mb-6 border-y border-border bg-surface/50 py-4" aria-labelledby="manager-scope-heading">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 id="manager-scope-heading" className="font-display text-sm font-bold text-ink">Analysis scope</h2>
          <p className="text-xs text-muted">Metrics recalculate within the selected attempts.</p>
        </div>
        {activeCount > 0 && (
          <Button variant="ghost" className="px-3 py-1.5" disabled={loading} onClick={() => onChange?.({ ...DEFAULT_MANAGER_SCOPE })}>
            Clear {activeCount} filter{activeCount === 1 ? '' : 's'}
          </Button>
        )}
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
        <ScopeSelect label="Product" value={scope.products[0] || ''} options={options.products || []} disabled={loading} onChange={(value) => setSingle('products', value)} />
        <ScopeSelect label="Lot" value={scope.lots[0] || ''} options={options.lots || []} disabled={loading} onChange={(value) => setSingle('lots', value)} />
        <ScopeSelect label="Station / tester" value={scope.stations[0] || ''} options={options.stations || []} disabled={loading} onChange={(value) => setSingle('stations', value)} />
        <ScopeDate label="From" value={scope.startTime} disabled={loading} onChange={(value) => setTime('startTime', value)} />
        <ScopeDate label="Through" value={scope.endTime} disabled={loading} onChange={(value) => setTime('endTime', value)} />
      </div>
    </section>
  )
}

function ScopeSelect({ label, value, options, disabled, onChange }) {
  return (
    <label className="text-xs text-muted">
      <span className="mb-1 block font-medium">{label}</span>
      <select value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus-ring disabled:opacity-60">
        <option value="">All</option>
        {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
      </select>
    </label>
  )
}

function ScopeDate({ label, value, disabled, onChange }) {
  return (
    <label className="text-xs text-muted">
      <span className="mb-1 block font-medium">{label}</span>
      <input type="datetime-local" value={value} disabled={disabled} onChange={(event) => onChange(event.target.value)} className="w-full rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink focus-ring disabled:opacity-60" />
    </label>
  )
}

function BatchQualityStatus({ batch }) {
  const available = batch.included_run_count != null
  const gaps = Number(batch.parse_excluded_count || 0) + Number(batch.incomplete_folder_count || 0) + Number(batch.unknown_result_count || 0) + Number(batch.missing_debuglog_count || 0)
  const period = batch.observed_start_time && batch.observed_end_time
    ? `${batch.observed_start_time} to ${batch.observed_end_time}`
    : 'Observed period unavailable'
  return (
    <section className="mb-5 flex flex-wrap items-center justify-between gap-3 border-l-2 border-accent pl-4" aria-label="Batch scope and completeness">
      <div className="min-w-0">
        <p className="text-sm font-medium text-ink">
          {batch.product_codes?.length ? batch.product_codes.join(', ') : 'Products unavailable'}
        </p>
        <p className="mt-0.5 break-words text-xs text-muted">
          {period} · Timezone {batch.timestamp_timezone === 'offset' ? 'from source offsets' : batch.timestamp_timezone || 'unavailable'}
        </p>
      </div>
      <div className="text-right">
        <p className={gaps ? 'text-sm font-semibold text-warning' : 'text-sm font-semibold text-teal'}>
          {!available ? 'Completeness unavailable' : gaps ? `${gaps} quality flag${gaps === 1 ? '' : 's'}` : 'No quality flags'}
        </p>
        {available && <p className="text-xs text-muted">{batch.included_run_count}/{batch.discovered_run_count ?? batch.included_run_count} parsed runs included</p>}
        {available && gaps > 0 && (
          <p className="text-xs text-muted">
            {batch.parse_excluded_count || 0} parse excluded · {batch.incomplete_folder_count || 0} incomplete · {batch.unknown_result_count || 0} unknown · {batch.missing_debuglog_count || 0} missing DebugLog
          </p>
        )}
      </div>
    </section>
  )
}

function EmptyState() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center">
      <IconWell className="h-16 w-16 mx-auto mb-6">
        <span className="text-2xl">📊</span>
      </IconWell>
      <h2 className="font-display text-2xl font-bold text-ink">No batch loaded</h2>
      <p className="mt-2 text-muted">Upload logs on the Home tab to see yield metrics.</p>
    </div>
  )
}

function EmptyMetricsState({ scoped = false }) {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center">
      <IconWell className="h-16 w-16 mx-auto mb-6">
        <span className="font-display text-xl font-bold text-muted">0</span>
      </IconWell>
      <h2 className="font-display text-2xl font-bold text-ink">No metrics in this {scoped ? 'scope' : 'batch'}</h2>
      <p className="mt-2 text-muted">No PASS, FAIL, or UNKNOWN test attempts were available to summarize.</p>
    </div>
  )
}
