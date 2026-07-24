import { useRef, useState } from 'react'
import { Button, Card, IconWell } from '../components/ui'

// Reads a browser file's relative path (folder uploads set webkitRelativePath).
function relPath(file) {
  return file.webkitRelativePath || file.name
}

function isSingleZip(files) {
  return files.length === 1 && relPath(files[0]).toLowerCase().endsWith('.zip')
}

function formatCount(count, singular, plural = `${singular}s`) {
  return `${count} ${count === 1 ? singular : plural}`
}

function summarizeNames(names, limit = 3) {
  const visible = names.slice(0, limit)
  const extra = names.length - visible.length
  return extra > 0 ? [...visible, `+ ${extra} more`] : visible
}

function uploadSummary(files) {
  if (!files.length) return null

  const paths = files.map(relPath)

  if (isSingleZip(files)) {
    return {
      title: paths[0],
      detail: 'ZIP archive ready',
      names: [paths[0]],
    }
  }

  const folderRoots = Array.from(
    new Set(paths.filter((path) => path.includes('/')).map((path) => path.split('/')[0])),
  )

  if (folderRoots.length) {
    return {
      title: summarizeNames(folderRoots).join(', '),
      detail: `${formatCount(files.length, 'file')} selected from ${formatCount(folderRoots.length, 'folder')}`,
      names: summarizeNames(folderRoots),
    }
  }

  return {
    title: summarizeNames(paths).join(', '),
    detail: `${formatCount(files.length, 'file')} ready`,
    names: summarizeNames(paths),
  }
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value || 0)
}

function formatCredits(value) {
  const amount = Number(value || 0)
  if (amount === 0) return '0'
  return amount < 1 ? amount.toFixed(4) : amount.toFixed(2)
}

function providerLabel(provider) {
  return provider ? provider.replace(/_/g, ' ') : 'Not used yet'
}

function tokenLabel(modelMetrics) {
  const prefix = modelMetrics?.token_counts_estimated ? '~' : ''
  const input = formatNumber(modelMetrics?.input_tokens)
  const output = formatNumber(modelMetrics?.output_tokens)
  return `${prefix}${input} in / ${prefix}${output} out`
}

function charsLabel(modelMetrics) {
  return `${formatNumber(modelMetrics?.input_chars)} in / ${formatNumber(modelMetrics?.output_chars)} out`
}

function ModelMetricsCard({ title, metrics }) {
  const calls = metrics?.calls || 0
  const modelName = metrics?.model || (calls ? 'Configured model' : 'Not used')
  return (
    <div className="rounded-panel border border-border bg-surface-2 p-5">
      <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">{title}</p>
          <p className="mt-1 truncate font-display text-lg font-semibold text-ink" title={modelName}>
            {modelName}
          </p>
        </div>
        <div className="rounded-lg border border-border bg-surface px-3 py-2 text-right">
          <p className="text-xs text-muted">Calls</p>
          <p className="font-display text-xl font-extrabold text-accent">{formatNumber(calls)}</p>
        </div>
      </div>
      <div className="mt-5 grid gap-3 sm:grid-cols-2">
        <MetricRow label="Prompt / output size" value={charsLabel(metrics)} />
        <MetricRow label="Tokens" value={tokenLabel(metrics)} />
        <MetricRow label="Estimated credits" value={formatCredits(metrics?.estimated_credits)} />
        <MetricRow label="Errors" value={formatNumber(metrics?.errors)} />
      </div>
    </div>
  )
}

function MetricRow({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-4 py-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 font-mono text-sm font-semibold text-ink break-words">{value}</p>
    </div>
  )
}

function LlmMetricsPanel({ metrics }) {
  if (!metrics) return null
  return (
    <Card className="mt-6 p-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <p className="text-xs font-semibold uppercase tracking-wide text-muted">LLM usage</p>
          <h2 className="mt-1 font-display text-2xl font-extrabold text-ink">Model cost and size metrics</h2>
        </div>
        <div className="grid grid-cols-2 gap-2 sm:grid-cols-4 lg:min-w-[28rem]">
          <SummaryMetric label="Provider" value={providerLabel(metrics.provider)} />
          <SummaryMetric label="Live calls" value={formatNumber(metrics.total_calls)} />
          <SummaryMetric label="Cache hits" value={formatNumber(metrics.cache_hits)} />
          <SummaryMetric label="Credits" value={formatCredits(metrics.total_estimated_credits)} />
        </div>
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        <ModelMetricsCard title="Mini model" metrics={metrics.mini} />
        <ModelMetricsCard title="Reasoning model" metrics={metrics.reasoning} />
      </div>

      <div className="mt-4 flex flex-wrap gap-3 text-xs text-muted">
        <span>{metrics.credit_basis || 'Estimated token credits.'}</span>
        <span>{formatNumber(metrics.calls_skipped_by_cache)} call{metrics.calls_skipped_by_cache === 1 ? '' : 's'} skipped by cache.</span>
      </div>
    </Card>
  )
}

function SummaryMetric({ label, value }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2 px-3 py-2">
      <p className="text-[0.68rem] uppercase tracking-wide text-muted">{label}</p>
      <p className="mt-1 truncate font-display text-sm font-bold text-ink" title={String(value)}>{value}</p>
    </div>
  )
}

export default function Home({ onStartBatch, onStopBatch, processing, progress, batchError, llmMetrics }) {
  const [files, setFiles] = useState([])
  const [dragging, setDragging] = useState(false)
  const [localError, setLocalError] = useState('')
  const folderInput = useRef(null)
  const fileInput = useRef(null)
  const selectedUpload = uploadSummary(files)

  const addFiles = (list) => {
    setLocalError('')
    setFiles(Array.from(list))
  }

  const onDrop = async (e) => {
    e.preventDefault()
    setDragging(false)
    const dropped = []
    const items = e.dataTransfer.items
    if (items && items.length && items[0].webkitGetAsEntry) {
      await Promise.all(
        Array.from(items).map((it) => traverse(it.webkitGetAsEntry(), dropped)),
      )
    } else {
      dropped.push(...Array.from(e.dataTransfer.files))
    }
    if (dropped.length) setFiles(dropped)
  }

  const start = async () => {
    if (!files.length) return
    if (files.length > 1000 && !isSingleZip(files)) {
      setLocalError(`This upload has ${files.length} files. Upload a .zip archive to avoid the 1000-file browser/API limit.`)
      return
    }
    setLocalError('')
    onStartBatch(files)
  }

  const pct = progress && progress.total ? Math.round((progress.processed / progress.total) * 100) : 0
  const progressLabel = progress && progress.total ? `${progress.processed}/${progress.total} • ${pct}%` : `${pct}%`
  const error = localError || batchError

  return (
    <div className="mx-auto max-w-4xl px-6 py-12">
      <div className="text-center mb-10">
        <h1 className="font-display text-4xl md:text-5xl font-extrabold tracking-tight text-ink">
          Upload test logs
        </h1>
        <p className="mt-3 text-muted max-w-xl mx-auto">
          Drop a folder of manufacturing logs, pick individual files, or upload a .zip
          archive for large batches. The same batch powers both the Engineer and Manager views.
        </p>
      </div>

      <Card className="p-8 md:p-12">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={[
            'rounded-panel border-2 border-dashed p-10 md:p-16 text-center transition-colors duration-200',
            dragging ? 'border-accent bg-accent/5' : 'border-border bg-surface-2',
          ].join(' ')}
        >
          <IconWell className="h-20 w-20 mx-auto mb-6">
            <svg className="text-accent" width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </IconWell>
          <p className="font-display text-lg font-semibold text-ink">
            {dragging ? 'Drop to add files' : 'Drag & drop logs or a .zip here'}
          </p>
          <p className="mt-1 text-sm text-muted">or choose below</p>

          {selectedUpload && (
            <div className="mt-6 mx-auto max-w-2xl rounded-lg border border-border bg-surface px-5 py-4 text-left">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                  <p className="text-xs font-semibold uppercase tracking-wide text-muted">Selected upload</p>
                  <p className="mt-1 truncate font-display text-lg font-semibold text-ink" title={selectedUpload.title}>
                    {selectedUpload.title}
                  </p>
                  <p className="mt-1 text-sm text-muted">{selectedUpload.detail}</p>
                </div>
                <button
                  className="self-start rounded-lg px-2 py-1 text-sm text-muted hover:text-ink focus-ring"
                  onClick={() => setFiles([])}
                  disabled={processing}
                >
                  Clear
                </button>
              </div>
              {selectedUpload.names.length > 1 && (
                <div className="mt-4 flex flex-wrap gap-2">
                  {selectedUpload.names.map((name, index) => (
                    <span
                      key={`${name}-${index}`}
                      className="inline-block max-w-full truncate rounded-full border border-border bg-surface px-3 py-1 text-xs font-medium text-ink-2"
                      title={name}
                    >
                      {name}
                    </span>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Button onClick={() => folderInput.current?.click()}>Select folder</Button>
            <Button onClick={() => fileInput.current?.click()}>Select files or .zip</Button>
          </div>

          <input
            ref={folderInput}
            type="file"
            className="hidden"
            webkitdirectory=""
            directory=""
            multiple
            onChange={(e) => addFiles(e.target.files)}
          />
          <input
            ref={fileInput}
            type="file"
            className="hidden"
            multiple
            onChange={(e) => addFiles(e.target.files)}
          />
        </div>

        {progress && (
          <div className="mt-6">
            <div className="flex justify-between text-sm text-muted mb-2">
              <span>{progress.message || progress.status}</span>
              <span>{progressLabel}</span>
            </div>
            <div className="h-3 rounded-full bg-surface-2 border border-border overflow-hidden">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {error && (
          <div className="mt-6 rounded-lg border border-danger/30 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="mt-8 flex justify-center">
          <div className="flex flex-wrap justify-center gap-3">
            <Button variant="primary" onClick={start} disabled={!files.length || processing}>
              {processing ? 'Processing…' : 'Process batch'}
            </Button>
            {processing && (
              <Button onClick={onStopBatch}>Stop batch</Button>
            )}
          </div>
        </div>
      </Card>

      <LlmMetricsPanel metrics={llmMetrics} />
    </div>
  )
}

// Recursively walk a dropped directory entry, collecting File objects with paths.
function traverse(entry, out, path = '') {
  return new Promise((resolve) => {
    if (!entry) return resolve()
    if (entry.isFile) {
      entry.file((file) => {
        Object.defineProperty(file, 'webkitRelativePath', {
          value: path + entry.name,
          configurable: true,
        })
        out.push(file)
        resolve()
      })
    } else if (entry.isDirectory) {
      const reader = entry.createReader()
      const readAll = () => {
        reader.readEntries(async (entries) => {
          if (!entries.length) return resolve()
          await Promise.all(entries.map((e) => traverse(e, out, path + entry.name + '/')))
          readAll()
        })
      }
      readAll()
    } else {
      resolve()
    }
  })
}
