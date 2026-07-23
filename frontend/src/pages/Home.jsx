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

export default function Home({ onStartBatch, onStopBatch, processing, progress, batchError }) {
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
            'rounded-card p-10 md:p-16 text-center transition-all duration-300',
            dragging ? 'bg-base shadow-inset-deep' : 'bg-base shadow-inset',
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
            <div className="mt-6 mx-auto max-w-2xl rounded-2xl bg-base shadow-inset-sm px-5 py-4 text-left">
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
                      className="inline-block max-w-full truncate rounded-full bg-base px-3 py-1 text-xs font-medium text-muted shadow-extruded-sm"
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
            <div className="h-4 rounded-full bg-base shadow-inset-sm overflow-hidden">
              <div
                className="h-full rounded-full bg-accent transition-all duration-500"
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )}

        {error && (
          <div className="mt-6 rounded-2xl bg-base shadow-inset-sm px-4 py-3 text-sm text-danger">
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
