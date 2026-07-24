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

export default function Manager({ jobId }) {
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    api.manager(jobId).then((d) => {
      setData(d)
      setLoading(false)
    })
  }, [jobId])

  if (!jobId) return <EmptyState />
  if (loading || !data)
    return (
      <div className="mx-auto max-w-6xl px-6 py-12">
        <Card className="p-10 text-center text-muted">Loading metrics…</Card>
      </div>
    )

  const s = data.summary
  const topFailure = data.pareto && data.pareto.length ? data.pareto[0] : null

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-8">
        <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">
          Manager view
        </h1>
        <p className="mt-1 text-sm text-muted">Yield, throughput, and failure breakdown for this batch.</p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4 mb-6">
        <MetricCard
          label="First-pass yield"
          value={`${s.fpy}%`}
          tone="accent"
          hint={`${s.fpy_pass}/${s.fpy_total} first attempts`}
        />
        <MetricCard label="Total runs" value={s.total_runs} hint={`${s.retests} retests`} />
        <MetricCard label="Unique units" value={s.unique_units} />
        <MetricCard label="Passed" value={s.passed} tone="pass" />
        <MetricCard label="Failed" value={s.failed} tone="fail" />
        {topFailure && (
          <MetricCard
            label="Top failure"
            value={`${topFailure.pct}%`}
            tone="fail"
            hint={`${topFailure.reason} · ${topFailure.count} fails`}
          />
        )}
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
        <ChartCard title="Yield trend" subtitle="First-pass yield by day">
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

        <ChartCard title="Failure Pareto" subtitle="Fail count with cumulative %">
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
              <Bar yAxisId="left" dataKey="count" name="Fails" fill={ACCENT} radius={[6, 6, 0, 0]} />
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
              <li key={p.reason} className="flex justify-between gap-4">
                <span className="truncate text-ink-2">{p.reason}</span>
                <span className="shrink-0 text-muted">
                  {p.count} · <span className="text-ink font-medium">{p.pct}%</span>
                </span>
              </li>
            ))}
          </ul>
        </ChartCard>

        <ChartCard title="Station / tester breakdown" subtitle="Pass vs fail per station">
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
        </ChartCard>

        <ChartCard title="Lot-to-lot comparison" subtitle="Yield by lot">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted text-left border-b border-border">
                  <th className="pb-2 font-medium">Lot</th>
                  <th className="pb-2 font-medium text-right">Pass</th>
                  <th className="pb-2 font-medium text-right">Fail</th>
                  <th className="pb-2 font-medium text-right">Yield</th>
                </tr>
              </thead>
              <tbody>
                {data.lots.map((l) => (
                  <tr key={l.lot} className="text-ink border-b border-border/60 last:border-0">
                    <td className="py-2 truncate">{l.lot}</td>
                    <td className="py-2 text-right text-teal">{l.pass}</td>
                    <td className="py-2 text-right text-danger">{l.fail}</td>
                    <td className="py-2 text-right font-semibold">{l.yield}%</td>
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
