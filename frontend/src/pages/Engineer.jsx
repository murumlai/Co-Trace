import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Badge, Button, Card, IconWell, SectionLabel } from '../components/ui'

const toneOf = (r) => (r === 'PASS' ? 'pass' : r === 'FAIL' ? 'fail' : 'unknown')

export default function Engineer({ jobId }) {
  const [units, setUnits] = useState([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState('all')
  const [expanded, setExpanded] = useState(null)
  const [reanalyzing, setReanalyzing] = useState(null)

  useEffect(() => {
    if (!jobId) return
    setLoading(true)
    api.units(jobId).then((d) => {
      setUnits(d.units)
      setLoading(false)
    })
  }, [jobId])

  const counts = useMemo(() => {
    const c = { all: units.length, PASS: 0, FAIL: 0, UNKNOWN: 0 }
    units.forEach((u) => (c[u.result] = (c[u.result] || 0) + 1))
    return c
  }, [units])

  const shown = units.filter((u) => filter === 'all' || u.result === filter)

  const reanalyze = async (unit) => {
    setReanalyzing(unit.unit_id)
    try {
      const updated = await api.reanalyze(jobId, unit.unit_id)
      setUnits((prev) => prev.map((u) => (u.unit_id === unit.unit_id ? updated : u)))
    } finally {
      setReanalyzing(null)
    }
  }

  if (!jobId) return <EmptyState />

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:py-14">
      <div className="mb-8 flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <SectionLabel>Engineer Diagnostics</SectionLabel>
          <h1 className="mt-4 font-display text-4xl leading-tight text-foreground md:text-5xl">
            Unit-level <span className="gradient-text">failure intelligence</span>
          </h1>
          <p className="mt-3 max-w-2xl text-muted">Filter failed units, inspect redacted context, and force a fresh diagnosis when a signature needs another look.</p>
        </div>
      </div>

      <div className="mb-8 flex flex-wrap gap-3">
        {[
          ['all', 'All'],
          ['FAIL', 'Failed'],
          ['PASS', 'Passed'],
          ['UNKNOWN', 'Unknown'],
        ].map(([key, label]) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            className={[
              'rounded-xl px-4 py-2.5 text-sm font-semibold transition-all duration-200 focus-ring',
              filter === key
                ? 'bg-accent text-white shadow-accent'
                : 'border border-border bg-card text-muted shadow-soft hover:-translate-y-0.5 hover:text-foreground',
            ].join(' ')}
          >
            {label} <span className="opacity-60">({counts[key] ?? 0})</span>
          </button>
        ))}
      </div>

      {loading ? (
        <Card className="p-10 text-center text-muted">Loading units…</Card>
      ) : (
        <div className="space-y-4">
          {shown.map((u) => (
            <Card key={u.unit_id} className="p-5 md:p-6" hover>
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <div className="flex items-center gap-3 flex-wrap">
                    <Badge tone={toneOf(u.result)}>{u.result}</Badge>
                    <span className="truncate font-semibold text-foreground">
                      {u.serial_number || u.unit_id}
                    </span>
                  </div>
                  <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-sm text-muted">
                    <span>Product: {u.product_code || '—'}</span>
                    <span>Station: {u.station_id || '—'}</span>
                    <span>Lot: {u.lot_id || '—'}</span>
                    {u.duration_s ? <span>{u.duration_s.toFixed(1)}s</span> : null}
                  </div>
                </div>
                {u.result === 'FAIL' && (
                  <button
                    className="shrink-0 rounded-lg px-2 py-1 text-sm font-semibold text-muted hover:text-foreground focus-ring"
                    onClick={() => setExpanded(expanded === u.unit_id ? null : u.unit_id)}
                  >
                    {expanded === u.unit_id ? 'Hide' : 'Details'}
                  </button>
                )}
              </div>

              {u.result === 'FAIL' && (
                <div className="mt-5 rounded-card border border-border bg-surface/70 p-5">
                  <div className="mb-1 font-mono text-xs uppercase tracking-[0.15em] text-muted">
                    Root cause
                    {u.analysis_source && (
                      <span className="ml-2 lowercase opacity-70">· {u.analysis_source}</span>
                    )}
                  </div>
                  <p className="text-foreground">{u.root_cause || 'Analyzing…'}</p>

                  <div className="mb-1 mt-4 font-mono text-xs uppercase tracking-[0.15em] text-muted">
                    Suggested solution
                  </div>
                  <p className="text-foreground">{u.suggested_solution || '—'}</p>

                  {expanded === u.unit_id && (
                    <div className="mt-4">
                      <div className="mb-2 font-mono text-xs uppercase tracking-[0.15em] text-muted">
                        Redacted log snippet
                      </div>
                      <pre className="overflow-x-auto whitespace-pre-wrap rounded-xl border border-border bg-white p-4 text-xs text-foreground">
                        {u.redacted_snippet || '(none)'}
                      </pre>
                    </div>
                  )}

                  <div className="mt-4">
                    <Button
                      onClick={() => reanalyze(u)}
                      disabled={reanalyzing === u.unit_id}
                    >
                      {reanalyzing === u.unit_id ? 'Re-analyzing…' : 'Re-analyze this unit'}
                    </Button>
                  </div>
                </div>
              )}
            </Card>
          ))}
          {shown.length === 0 && (
            <Card className="p-10 text-center text-muted">No units in this filter.</Card>
          )}
        </div>
      )}
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
      <p className="mt-2 text-muted">Upload logs on the Home tab to see unit diagnostics.</p>
    </div>
  )
}
