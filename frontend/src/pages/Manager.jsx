import { useEffect, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from '../api'
import { Card, IconWell, SectionLabel, Stat } from '../components/ui'

const AXIS = { fill: '#64748B', fontSize: 12, fontFamily: 'Inter' }
const GRID = '#E2E8F0'

function ChartCard({ title, children }) {
  return (
    <Card className="p-5 md:p-6" hover>
      <h3 className="mb-6 text-lg font-semibold text-foreground">{title}</h3>
      {children}
    </Card>
  )
}

const tooltipStyle = {
  background: '#FFFFFF',
  border: '1px solid #E2E8F0',
  borderRadius: 12,
  boxShadow: '0 16px 36px rgb(15 23 42 / 0.12)',
  color: '#0F172A',
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
      <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6">
        <Card className="p-10 text-center text-muted">Loading metrics…</Card>
      </div>
    )

  const s = data.summary

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:py-14">
      <div className="mb-8 rounded-card bg-foreground p-6 text-white shadow-lift dot-texture md:p-8">
        <SectionLabel>Manager Analytics</SectionLabel>
        <h1 className="mt-5 font-display text-4xl leading-tight md:text-5xl">
          Yield performance with <span className="gradient-text">executive clarity</span>
        </h1>
        <p className="mt-4 max-w-2xl text-white/70">Track first-pass yield, repeated failures, station breakdown, and lot-to-lot movement from the active batch.</p>
      </div>

      <div className="mb-8 grid grid-cols-2 gap-4 lg:grid-cols-4 lg:gap-6">
        <Stat label="First-pass yield" value={`${s.fpy}%`} accent />
        <Stat label="Total runs" value={s.total_runs} />
        <Stat label="Passed" value={s.passed} />
        <Stat label="Failed" value={s.failed} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <ChartCard title="Yield trend">
          <ResponsiveContainer width="100%" height={280}>
            <LineChart data={data.trend} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="4 4" />
              <XAxis dataKey="date" tick={AXIS} tickLine={false} axisLine={false} />
              <YAxis domain={[0, 100]} tick={AXIS} tickLine={false} axisLine={false} unit="%" />
              <Tooltip contentStyle={tooltipStyle} />
              <Line
                type="monotone"
                dataKey="yield"
                stroke="#0052FF"
                strokeWidth={3}
                dot={{ fill: '#0052FF', r: 4 }}
              />
            </LineChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Top failure reasons (Pareto)">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data.pareto} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="4 4" />
              <XAxis dataKey="reason" tick={false} axisLine={false} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="count" fill="#0052FF" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <ul className="mt-4 space-y-2 text-sm text-muted">
            {data.pareto.slice(0, 5).map((p) => (
              <li key={p.reason} className="flex justify-between gap-4 rounded-lg bg-surface px-3 py-2">
                <span className="truncate">{p.reason}</span>
                <span className="shrink-0 font-semibold text-foreground">
                  {p.count} · {p.pct}%
                </span>
              </li>
            ))}
          </ul>
        </ChartCard>

        <ChartCard title="Station / tester breakdown">
          <ResponsiveContainer width="100%" height={280}>
            <BarChart data={data.stations} margin={{ top: 5, right: 10, left: -10, bottom: 0 }}>
              <CartesianGrid stroke={GRID} strokeDasharray="4 4" />
              <XAxis dataKey="station" tick={false} axisLine={false} />
              <YAxis tick={AXIS} tickLine={false} axisLine={false} />
              <Tooltip contentStyle={tooltipStyle} />
              <Bar dataKey="pass" stackId="a" fill="#059669" radius={[0, 0, 0, 0]} />
              <Bar dataKey="fail" stackId="a" fill="#DC2626" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Lot-to-lot comparison">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-muted">
                  <th className="pb-3 font-medium">Lot</th>
                  <th className="pb-3 font-medium text-right">Pass</th>
                  <th className="pb-3 font-medium text-right">Fail</th>
                  <th className="pb-3 font-medium text-right">Yield</th>
                </tr>
              </thead>
              <tbody>
                {data.lots.map((l) => (
                  <tr key={l.lot} className="border-t border-border text-foreground">
                    <td className="py-2 truncate">{l.lot}</td>
                    <td className="py-2 text-right text-success">{l.pass}</td>
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
      <IconWell className="mx-auto mb-6 h-16 w-16">
        <span className="font-display text-2xl">CT</span>
      </IconWell>
      <h2 className="font-display text-3xl text-foreground">No batch loaded</h2>
      <p className="mt-2 text-muted">Upload logs on the Home tab to see yield metrics.</p>
    </div>
  )
}
