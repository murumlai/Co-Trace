import { useEffect, useMemo, useState } from 'react'
import { api } from '../api'
import { Badge, Button, Card, IconWell } from '../components/ui'

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
    <div className="mx-auto max-w-5xl px-6 py-12">
      <h1 className="font-display text-4xl font-extrabold tracking-tight text-ink mb-8">
        Engineer view
      </h1>

      <div className="flex flex-wrap gap-3 mb-8">
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
              'rounded-2xl px-5 py-2.5 text-sm font-medium transition-all duration-300 focus-ring',
              filter === key
                ? 'bg-base text-accent shadow-inset'
                : 'bg-base text-muted shadow-extruded-sm hover:-translate-y-px',
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
                <div className="mt-5 rounded-2xl bg-base shadow-inset p-5">
                  <div className="text-xs uppercase tracking-wide text-muted mb-1">
                    Root cause
                    {u.analysis_source && (
                      <span className="ml-2 lowercase opacity-70">· {u.analysis_source}</span>
                    )}
                  </div>
                  <p className="text-ink">{u.root_cause || 'Analyzing…'}</p>

                  <div className="text-xs uppercase tracking-wide text-muted mt-4 mb-1">
                    Suggested solution
                  </div>
                  <p className="text-ink">{u.suggested_solution || '—'}</p>

                  {expanded === u.unit_id && (
                    <div className="mt-4">
                      <div className="text-xs uppercase tracking-wide text-muted mb-2">
                        Redacted log snippet
                      </div>
                      <pre className="rounded-xl bg-base shadow-inset-sm p-4 text-xs text-ink overflow-x-auto whitespace-pre-wrap">
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
      <IconWell className="h-20 w-20 mx-auto mb-6">
        <span className="text-2xl">🔧</span>
      </IconWell>
      <h2 className="font-display text-2xl font-bold text-ink">No batch loaded</h2>
      <p className="mt-2 text-muted">Upload logs on the Home tab to see unit diagnostics.</p>
    </div>
  )
}
