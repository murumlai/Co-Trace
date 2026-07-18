import { useRef, useState } from 'react'
import { api } from '../api'
import { Badge, Button, Card, IconWell, SectionLabel } from '../components/ui'

// Reads a browser file's relative path (folder uploads set webkitRelativePath).
function relPath(file) {
  return file.webkitRelativePath || file.name
}

export default function Home({ onJobReady }) {
  const [files, setFiles] = useState([])
  const [dragging, setDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(null)
  const [error, setError] = useState('')
  const folderInput = useRef(null)
  const fileInput = useRef(null)

  const addFiles = (list) => {
    setError('')
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
    setUploading(true)
    setError('')
    setProgress({ status: 'uploading', processed: 0, total: files.length })
    try {
      const fd = new FormData()
      for (const f of files) {
        fd.append('files', f)
        fd.append('paths', relPath(f))
      }
      const { job_id } = await api.upload(fd)
      await poll(job_id)
    } catch (err) {
      setError(err.message)
      setUploading(false)
    }
  }

  const poll = async (jobId) => {
    // Poll job status until done/error.
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const s = await api.status(jobId)
      setProgress({
        status: s.status,
        processed: s.progress.processed,
        total: s.progress.total,
        message: s.message,
      })
      if (s.status === 'done') {
        setUploading(false)
        onJobReady(jobId)
        return
      }
      if (s.status === 'error') {
        setError(s.message)
        setUploading(false)
        return
      }
      await new Promise((r) => setTimeout(r, 700))
    }
  }

  const pct = progress && progress.total ? Math.round((progress.processed / progress.total) * 100) : 0

  return (
    <div className="mx-auto max-w-6xl px-4 py-10 sm:px-6 lg:py-16">
      <div className="grid items-end gap-8 lg:grid-cols-[1.1fr_0.9fr]">
        <div>
          <SectionLabel>Batch Intake</SectionLabel>
          <h1 className="mt-5 max-w-3xl font-display text-4xl leading-tight text-foreground md:text-6xl">
            Turn raw tester logs into <span className="gradient-text">actionable yield signals</span>
          </h1>
          <p className="mt-5 max-w-2xl text-lg leading-8 text-muted">
            Drop a folder or select files. The same batch powers engineer diagnostics and manager analytics.
          </p>
        </div>
        <div className="rounded-card bg-foreground p-6 text-white shadow-lift dot-texture">
          <div className="font-mono text-xs uppercase tracking-[0.15em] text-white/60">Current workflow</div>
          <div className="mt-5 grid grid-cols-3 gap-3 text-center">
            {['Upload', 'Analyze', 'Review'].map((step, index) => (
              <div key={step} className="rounded-xl border border-white/10 bg-white/5 p-4">
                <div className="mx-auto flex h-9 w-9 items-center justify-center rounded-full bg-gradient-to-br from-accent to-accent-secondary text-sm font-bold shadow-accent">
                  {index + 1}
                </div>
                <div className="mt-3 text-sm font-semibold">{step}</div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <Card className="mt-10 p-5 shadow-lift md:p-8">
        <div
          onDragOver={(e) => {
            e.preventDefault()
            setDragging(true)
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={[
            'rounded-card border-2 border-dashed p-8 text-center transition-all duration-300 md:p-14',
            dragging ? 'border-accent bg-accent/5 shadow-accent' : 'border-border bg-surface/60',
          ].join(' ')}
        >
          <IconWell className="mx-auto mb-6 h-16 w-16">
            <svg width="30" height="30" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
              <polyline points="17 8 12 3 7 8" />
              <line x1="12" y1="3" x2="12" y2="15" />
            </svg>
          </IconWell>
          <p className="font-display text-2xl text-foreground">
            {dragging ? 'Drop to add files' : 'Drag & drop logs here'}
          </p>
          <p className="mt-2 text-sm text-muted">Choose a folder for best path preservation, or upload individual files.</p>

          <div className="mt-8 flex flex-wrap items-center justify-center gap-4">
            <Button variant="primary" onClick={() => folderInput.current?.click()}>Select folder</Button>
            <Button onClick={() => fileInput.current?.click()}>Select files</Button>
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

        {files.length > 0 && (
          <div className="mt-6 flex items-center justify-between rounded-xl border border-border bg-surface px-5 py-4">
            <span className="text-sm font-semibold text-foreground">
              {files.length} file{files.length === 1 ? '' : 's'} ready
            </span>
            <button
              className="rounded-lg px-2 py-1 text-sm text-muted hover:text-foreground focus-ring"
              onClick={() => setFiles([])}
            >
              Clear
            </button>
          </div>
        )}

        {progress && (
          <div className="mt-6">
            <div className="flex justify-between text-sm text-muted mb-2">
              <span>{progress.message || progress.status}</span>
              <span>{pct}%</span>
            </div>
            <div className="h-3 overflow-hidden rounded-full bg-surface">
              <div
                className="h-full rounded-full bg-gradient-to-r from-accent to-accent-secondary transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {error && (
          <div className="mt-6 rounded-xl border border-danger/20 bg-danger/10 px-4 py-3 text-sm text-danger">
            {error}
          </div>
        )}

        <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
          <Badge tone="accent">Offline stub ready</Badge>
          <Button variant="primary" onClick={start} disabled={!files.length || uploading}>
            {uploading ? 'Processing…' : 'Process batch'}
          </Button>
        </div>
      </Card>
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
