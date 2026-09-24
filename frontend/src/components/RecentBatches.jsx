import { useState } from 'react'

const STATUS_LABELS = {
  pending: 'Pending',
  running: 'Running',
  done: 'Ready',
  error: 'Failed',
  cancelled: 'Cancelled',
}

function formatCreatedAt(value) {
  const date = new Date(Number(value) * 1000)
  if (Number.isNaN(date.getTime())) return 'Time unavailable'
  return date.toLocaleString([], { dateStyle: 'short', timeStyle: 'short' })
}

export default function RecentBatches({
  jobs,
  activeJobId,
  loading,
  error,
  hasMore,
  preferredView,
  onPreferredViewChange,
  onOpen,
  onNew,
  onRefresh,
  onLoadMore,
  mobile = false,
}) {
  const [open, setOpen] = useState(false)
  const ready = jobs.find((job) => job.job_id === activeJobId)
  const label = ready?.display_name || (activeJobId ? `Batch ${activeJobId.slice(0, 8)}` : 'Recent batches')

  return (
    <div className={mobile ? 'w-full' : 'relative'}>
      <button
        type="button"
        aria-expanded={open}
        aria-haspopup="dialog"
        onClick={() => setOpen((value) => !value)}
        className={[
          'flex items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2 text-sm text-ink-2 hover:bg-surface-2 focus-ring',
          mobile ? 'w-full' : 'max-w-48',
        ].join(' ')}
      >
        <span className="truncate">{label}</span>
        <span aria-hidden="true" className="text-muted">▾</span>
      </button>

      {open && (
        <div
          role="dialog"
          aria-label="Recent batches"
          className={[
            'z-40 w-full rounded-panel border border-border bg-surface p-3 shadow-lg',
            mobile ? 'mt-2' : 'absolute right-0 top-12 min-w-80',
          ].join(' ')}
        >
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className="font-display text-sm font-bold text-ink">Recent batches</p>
              <p className="text-xs text-muted">Batches in the shared workspace</p>
            </div>
            <button type="button" className="rounded-md px-2 py-1 text-xs text-accent hover:bg-accent/10 focus-ring" onClick={onRefresh}>
              Refresh
            </button>
          </div>

          <label className="mb-3 flex items-center justify-between gap-3 rounded-lg border border-border bg-surface-2 px-3 py-2 text-xs text-muted">
            Open results in
            <select
              value={preferredView}
              onChange={(event) => onPreferredViewChange(event.target.value)}
              className="rounded-md border border-border bg-surface px-2 py-1 text-xs text-ink focus-ring"
            >
              <option value="engineer">Engineer</option>
              <option value="manager">Manager</option>
            </select>
          </label>

          <button
            type="button"
            onClick={() => {
              setOpen(false)
              onNew()
            }}
            className="mb-2 w-full rounded-lg bg-accent px-3 py-2 text-left text-sm font-medium text-white hover:bg-accent-hover focus-ring"
          >
            New batch
          </button>

          {error && (
            <div role="alert" className="mb-2 rounded-lg border border-danger/30 bg-danger/10 px-3 py-2 text-xs text-danger">
              {error}
            </div>
          )}
          {loading && jobs.length === 0 && <p role="status" className="px-2 py-4 text-center text-sm text-muted">Loading batches…</p>}
          {!loading && jobs.length === 0 && !error && <p className="px-2 py-4 text-center text-sm text-muted">No saved batches.</p>}

          <div className="max-h-72 space-y-1 overflow-y-auto">
            {jobs.map((job) => (
              <button
                type="button"
                key={job.job_id}
                disabled={!job.result_available && !['pending', 'running'].includes(job.status)}
                onClick={() => {
                  setOpen(false)
                  onOpen(job)
                }}
                className={[
                  'w-full rounded-lg border px-3 py-2 text-left focus-ring disabled:cursor-not-allowed disabled:opacity-50',
                  job.job_id === activeJobId ? 'border-accent bg-accent/5' : 'border-transparent hover:border-border hover:bg-surface-2',
                ].join(' ')}
              >
                <div className="flex items-center justify-between gap-3">
                  <span className="truncate text-sm font-medium text-ink">{job.display_name}</span>
                  <span className="shrink-0 text-xs text-muted">{STATUS_LABELS[job.status] || job.status}</span>
                </div>
                <div className="mt-1 flex items-center justify-between gap-3 text-xs text-muted">
                  <span>{formatCreatedAt(job.created_at)}</span>
                  <span>{job.unit_count} attempt{job.unit_count === 1 ? '' : 's'}</span>
                </div>
              </button>
            ))}
          </div>

          {hasMore && (
            <button type="button" disabled={loading} onClick={onLoadMore} className="mt-2 w-full rounded-lg px-3 py-2 text-sm text-accent hover:bg-accent/10 focus-ring disabled:opacity-50">
              {loading ? 'Loading…' : 'Load more'}
            </button>
          )}
        </div>
      )}
    </div>
  )
}