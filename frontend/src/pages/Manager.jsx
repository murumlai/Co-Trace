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
import { Card, IconWell, Stat } from '../components/ui'

const AXIS = { fill: '#6B7280', fontSize: 12, fontFamily: 'DM Sans' }
const GRID = '#c9d0da'

function ChartCard({ title, children }) {
  return (
    <Card className="p-6 md:p-8">
      <h3 className="font-display font-bold text-ink mb-6">{title}</h3>
      {children}
    </Card>
  )
}

const tooltipStyle = {
  background: '#E0E5EC',
  border: 'none',
  borderRadius: 16,
  boxShadow: '6px 6px 12px rgb(163 177 198 / 0.6), -6px -6px 12px rgb(255 255 255 / 0.5)',
  color: '#3D4852',
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

  return (
    <div className="mx-auto max-w-6xl px-6 py-12">
      <h1 className="font-display text-4xl font-extrabold tracking-tight text-ink mb-8">
        Manager view
      </h1>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-6 mb-8">
        <Stat label="First-pass yield" value={`${s.fpy}%`} accent />
        <Stat label="Total runs" value={s.total_runs} />
        <Stat label="Passed" value={s.passed} />
        <Stat label="Failed" value={s.failed} />
      </div>

      <div className="grid lg:grid-cols-2 gap-6">
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
                stroke="#6C63FF"
                strokeWidth={3}
                dot={{ fill: '#6C63FF', r: 4 }}
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
              <Bar dataKey="count" fill="#6C63FF" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
          <ul className="mt-4 space-y-1 text-sm text-muted">
            {data.pareto.slice(0, 5).map((p) => (
              <li key={p.reason} className="flex justify-between gap-4">
                <span className="truncate">{p.reason}</span>
                <span className="shrink-0 text-ink font-medium">
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
              <Bar dataKey="pass" stackId="a" fill="#38B2AC" radius={[0, 0, 0, 0]} />
              <Bar dataKey="fail" stackId="a" fill="#E05260" radius={[8, 8, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </ChartCard>

        <ChartCard title="Lot-to-lot comparison">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-muted text-left">
                  <th className="pb-3 font-medium">Lot</th>
                  <th className="pb-3 font-medium text-right">Pass</th>
                  <th className="pb-3 font-medium text-right">Fail</th>
                  <th className="pb-3 font-medium text-right">Yield</th>
                </tr>
              </thead>
              <tbody>
                {data.lots.map((l) => (
                  <tr key={l.lot} className="text-ink">
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
      <IconWell className="h-20 w-20 mx-auto mb-6">
        <span className="text-2xl">📊</span>
      </IconWell>
      <h2 className="font-display text-2xl font-bold text-ink">No batch loaded</h2>
      <p className="mt-2 text-muted">Upload logs on the Home tab to see yield metrics.</p>
    </div>
  )
}
