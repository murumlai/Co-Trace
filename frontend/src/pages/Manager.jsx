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
import { Card, IconWell, MetricCard } from '../components/ui'
import { firstObservedPassMetric, formatRate } from '../managerMetrics'

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
    <Card className="p-6">
      <div className="mb-5">
        <h3 className="font-display font-bold text-ink">{title}</h3>
        {subtitle && <p className="mt-0.5 text-xs text-muted">{subtitle}</p>}
      </div>
      {children}
    </Card>
  )
}

export default function Manager({ jobId, onDrillDown }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [reload, setReload] = useState(0)

  useEffect(() => {
    if (!jobId) {
      setLoading(false)
      return undefined
    }
    let active = true
    setLoading(true)
    setData(null)
    setError('')
    api.manager(jobId).then(
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
  }, [jobId, reload])

  if (!jobId) return <EmptyState />
  if (loading)
    return (
      <div className="mx-auto max-w-6xl px-6 py-12">
        <Card role="status" className="p-10 text-center text-muted">Loading metrics…</Card>
      </div>
    )
  if (error) {
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
  if (!data || !data.summary?.total_runs) return <EmptyMetricsState />

  const s = data.summary
  const topFailure = data.pareto && data.pareto.length ? data.pareto[0] : null
  const firstObservedPass = firstObservedPassMetric(s)

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">
          Manager view
        </h1>
        <p className="mt-1 text-sm text-muted">Latest unit outcomes and attempt-level results for this uploaded batch.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard
          label="First observed pass rate"
          value={firstObservedPass.value}
          tone="accent"
          hint={firstObservedPass.hint}
        />
        <MetricCard label="Test attempts" value={s.total_runs} hint={`${s.retests} additional attempts`} />
        <MetricCard label="Observed units" value={s.unique_units} />
        <MetricCard label="Latest passed units" value={s.passed} tone="pass" hint={`${s.passed}/${s.unique_units} observed units`} />
        <MetricCard label="Latest failing units" value={s.failed} tone="fail" hint={`${s.failed}/${s.unique_units} observed units`} />
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
          <ul className="mt-4 space-y-1.5 text-sm">
            {data.pareto.slice(0, 5).map((p) => (
              <li key={p.signature}>
                <button
                  type="button"
                  onClick={() => onDrillDown({ signature: p.signature, label: p.reason })}
                  className="flex w-full justify-between gap-4 rounded-md px-1 py-1 text-left hover:bg-surface-2 focus-ring"
                >
                <span className="truncate text-ink-2">{p.reason}</span>
                <span className="shrink-0 text-muted">
                  {p.count} · <span className="text-ink font-medium">{p.pct}%</span>
                </span>
                </button>
              </li>
            ))}
          </ul>
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
          <ul className="mt-4 space-y-1.5 text-sm">
            {data.stations.map((station) => (
              <li key={`${station.host || ''}:${station.station_id || ''}`}>
                <button
                  type="button"
                  onClick={() => onDrillDown({
                    station_id: station.station_id,
                    host: station.host,
                    label: station.station,
                  })}
                  className="flex w-full justify-between gap-4 rounded-md px-1 py-1 text-left hover:bg-surface-2 focus-ring"
                >
                  <span className="truncate text-ink-2">{station.station}</span>
                  <span className="shrink-0 text-muted">{station.fail} failed attempts</span>
                </button>
              </li>
            ))}
          </ul>
        </ChartCard>

        <ChartCard title="Lot-to-lot attempt comparison" subtitle="Attempt pass rate by lot">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted text-left border-b border-border">
                  <th className="pb-2 font-medium">Lot</th>
                  <th className="pb-2 font-medium text-right">PASS attempts</th>
                  <th className="pb-2 font-medium text-right">FAIL attempts</th>
                  <th className="pb-2 font-medium text-right">Pass rate</th>
                </tr>
              </thead>
              <tbody>
                {data.lots.map((l) => (
                  <tr
                    key={l.lot}
                    className="cursor-pointer text-ink border-b border-border/60 last:border-0 hover:bg-surface-2"
                    onClick={() => onDrillDown({ lot_id: l.lot, label: l.lot })}
                    tabIndex={0}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter' || event.key === ' ') {
                        event.preventDefault()
                        onDrillDown({ lot_id: l.lot, label: l.lot })
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
    </div>
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

function EmptyMetricsState() {
  return (
    <div className="mx-auto max-w-2xl px-6 py-24 text-center">
      <IconWell className="h-16 w-16 mx-auto mb-6">
        <span className="font-display text-xl font-bold text-muted">0</span>
      </IconWell>
      <h2 className="font-display text-2xl font-bold text-ink">No metrics in this batch</h2>
      <p className="mt-2 text-muted">No PASS, FAIL, or UNKNOWN test runs were available to summarize.</p>
    </div>
  )
}
