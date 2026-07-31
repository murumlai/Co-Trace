import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { Badge, Button, Card, Panel } from '../components/ui'
import { log } from '../logger'

const CATEGORY_TONE = {
  debug_learning: 'fail',
  hld: 'accent',
  product_overview: 'pass',
  uncategorized: 'muted',
}

const CATEGORY_LABEL = {
  debug_learning: 'Debug learning',
  hld: 'HLD',
  product_overview: 'Product overview',
  uncategorized: 'Uncategorized',
}

function categoryBadge(category) {
  return (
    <Badge tone={CATEGORY_TONE[category] || 'muted'} dot={false}>
      {CATEGORY_LABEL[category] || category}
    </Badge>
  )
}

export default function Knowledge() {
  const [status, setStatus] = useState(null)
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [sections, setSections] = useState([])
  const [openProduct, setOpenProduct] = useState(null)
  const [job, setJob] = useState(null)
  const fileInput = useRef(null)

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.knowledge()
      setStatus(data)
      setError('')
    } catch (err) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    load()
  }, [])

  const manifest = status?.manifest || null
  const products = manifest?.products || []
  const documents = manifest?.documents || []

  const docsByProduct = useMemo(() => {
    const map = {}
    documents.forEach((d) => {
      const key = d.product_code || 'UNKNOWN'
      ;(map[key] = map[key] || []).push(d)
    })
    return map
  }, [documents])

  const runAction = async (label, fn) => {
    setBusy(label)
    setError('')
    setNotice('')
    setJob(null)
    try {
      await fn()
      await load()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const rebuild = () =>
    runAction('rebuild', async () => {
      await api.knowledgeRebuild()
      setNotice('Knowledge pack rebuilt.')
      log('info', 'Knowledge rebuilt')
    })

  const upload = (event) => {
    const file = event.target.files?.[0]
    if (!file) return
    event.target.value = ''
    uploadDocument(file)
  }

  const uploadDocument = async (file) => {
    setBusy('upload')
    setError('')
    setNotice('')
    setJob({
      status: 'running',
      message: `Uploading ${file.name}`,
      progress: { processed: 0, total: 1 },
    })
    try {
      const form = new FormData()
      form.append('file', file)
      const started = await api.knowledgeUpload(form)
      if (started.job) setJob(started.job)
      await pollKnowledgeJob(started.job_id, `Uploaded and ingested ${file.name}.`)
    } catch (err) {
      setError(err.message)
      setBusy('')
    }
  }

  const pollKnowledgeJob = async (jobId, successMessage) => {
    if (!jobId) return
    while (true) {
      const current = await api.knowledgeJob(jobId)
      setJob(current)
      if (current.status === 'done') {
        setNotice(successMessage)
        await load()
        setBusy('')
        return
      }
      if (current.status === 'error') {
        setError(current.error || current.message || 'Knowledge ingestion failed.')
        setBusy('')
        return
      }
      await new Promise((resolve) => setTimeout(resolve, 700))
    }
  }

  const deleteDocument = (doc) =>
    runAction(`del:${doc.doc_id}`, async () => {
      await api.knowledgeDeleteDocument(doc.doc_id)
      setNotice(`Deleted ${doc.filename}.`)
    })

  const deletePack = () =>
    runAction('deletePack', async () => {
      await api.knowledgeDeletePack()
      setNotice('Knowledge pack deleted.')
    })

  const toggleSections = async (productCode) => {
    if (openProduct === productCode) {
      setOpenProduct(null)
      return
    }
    setOpenProduct(productCode)
    try {
      const data = await api.knowledgeSections(productCode)
      setSections(data.sections || [])
    } catch (err) {
      setError(err.message)
    }
  }

  if (loading) {
    return (
      <div className="mx-auto max-w-6xl px-6 py-12">
        <Card className="p-10 text-center text-muted">Loading knowledge pack…</Card>
      </div>
    )
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <div className="mb-8 flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="font-display text-3xl font-extrabold tracking-tight text-ink">
            Product knowledge
          </h1>
          <p className="mt-1 text-sm text-muted">
            Curated product/card summaries used to make failure diagnosis product-aware. Runtime
            diagnosis sends only matched summaries, never whole documents.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".pdf,.docx"
            onChange={upload}
            className="hidden"
          />
          <Button onClick={() => fileInput.current?.click()} disabled={!!busy}>
            {busy === 'upload' ? 'Uploading…' : 'Upload document'}
          </Button>
          <Button variant="primary" onClick={rebuild} disabled={!!busy}>
            {busy === 'rebuild' ? 'Rebuilding…' : 'Rebuild pack'}
          </Button>
        </div>
      </div>

      {!status?.enabled && (
        <Panel className="p-4 mb-4 border-warning/30 bg-warning/10">
          <p className="text-sm text-warning">
            Product-aware diagnosis is disabled (PRODUCT_KNOWLEDGE_ENABLED=0). You can still manage
            the pack, but retrieval is off during analysis.
          </p>
        </Panel>
      )}
      {!status?.llm_available && (
        <Panel className="p-4 mb-4 border-warning/30 bg-warning/10">
          <p className="text-sm text-warning">
            No LLM backend detected. Summarization requires it — run <code>copilot auth login</code>{' '}
            before rebuilding.
          </p>
        </Panel>
      )}
      {error && (
        <Panel className="p-4 mb-4 border-danger/30 bg-danger/5">
          <p className="text-sm text-danger">{error}</p>
        </Panel>
      )}
      {notice && (
        <Panel className="p-4 mb-4 border-teal/30 bg-teal/5">
          <p className="text-sm text-teal">{notice}</p>
        </Panel>
      )}

      {busy && <KnowledgeProgress busy={busy} job={job} />}

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-6">
        <StatCard label="Products" value={products.length} />
        <StatCard label="Documents" value={documents.length} />
        <StatCard
          label="Sections"
          value={products.reduce((n, p) => n + (p.section_count || 0), 0)}
        />
        <StatCard label="Summary model" value={status?.summary_model || '—'} small />
      </div>

      {manifest?.generated_at && (
        <p className="text-xs text-muted mb-4">
          Generated {manifest.generated_at.replace('T', ' ').slice(0, 19)} · hash{' '}
          {manifest.global_hash}
        </p>
      )}

      {products.length === 0 ? (
        <Card className="p-10 text-center text-muted">
          No product knowledge yet. Upload a PDF/DOCX product doc or place files in a source folder,
          then rebuild.
        </Card>
      ) : (
        <div className="space-y-4">
          {products.map((p) => (
            <Card key={p.product_code} className="p-5">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3 flex-wrap">
                  <span className="font-display font-bold text-ink">{p.product_code}</span>
                  <span className="text-xs text-muted">
                    {p.document_count} doc{p.document_count === 1 ? '' : 's'} · {p.section_count}{' '}
                    section{p.section_count === 1 ? '' : 's'}
                  </span>
                  <div className="flex gap-1 flex-wrap">
                    {Object.entries(p.category_counts || {}).map(([cat, count]) => (
                      <span key={cat} className="text-xs">
                        {categoryBadge(cat)}
                        <span className="ml-1 text-muted">{count}</span>
                      </span>
                    ))}
                  </div>
                </div>
                <Button onClick={() => toggleSections(p.product_code)}>
                  {openProduct === p.product_code ? 'Hide sections' : 'View sections'}
                </Button>
              </div>

              <div className="mt-3 space-y-1">
                {(docsByProduct[p.product_code] || []).map((doc) => (
                  <div
                    key={doc.doc_id}
                    className="flex items-center justify-between gap-3 text-xs text-muted"
                  >
                    <span className="flex items-center gap-2">
                      {categoryBadge(doc.category)}
                      <span className="text-ink">{doc.filename}</span>
                      {doc.warnings?.length > 0 && (
                        <span className="text-warning">· {doc.warnings.length} warning(s)</span>
                      )}
                    </span>
                    <button
                      className="text-danger hover:underline focus-ring rounded px-1"
                      onClick={() => deleteDocument(doc)}
                      disabled={!!busy}
                    >
                      {busy === `del:${doc.doc_id}` ? 'Deleting…' : 'Delete'}
                    </button>
                  </div>
                ))}
              </div>

              {openProduct === p.product_code && (
                <div className="mt-4 space-y-3 border-t border-border pt-4">
                  {sections.length === 0 ? (
                    <p className="text-sm text-muted">No sections.</p>
                  ) : (
                    sections.map((s) => <SectionPreview key={s.section_id} section={s} />)
                  )}
                </div>
              )}
            </Card>
          ))}
        </div>
      )}

      {manifest?.warnings?.length > 0 && (
        <Panel className="p-4 mt-6 border-warning/30 bg-warning/10">
          <p className="text-sm font-semibold text-warning mb-1">
            {manifest.warnings.length} ingestion warning(s)
          </p>
          <ul className="list-disc list-inside text-xs text-warning/80 max-h-40 overflow-auto">
            {manifest.warnings.map((w, i) => (
              <li key={i}>{w}</li>
            ))}
          </ul>
        </Panel>
      )}

      {products.length > 0 && (
        <div className="mt-8">
          <button
            className="text-xs text-danger hover:underline focus-ring rounded px-1"
            onClick={deletePack}
            disabled={!!busy}
          >
            {busy === 'deletePack' ? 'Deleting pack…' : 'Delete entire knowledge pack'}
          </button>
        </div>
      )}
    </div>
  )
}

function KnowledgeProgress({ busy, job }) {
  const progress = job?.progress || { processed: 0, total: 1 }
  const total = Math.max(1, progress.total || 1)
  const processed = Math.max(0, progress.processed || 0)
  const pct = job?.status === 'done' ? 100 : Math.max(5, Math.min(99, Math.round((processed / total) * 100)))
  const label = job?.message || (busy === 'rebuild' ? 'Rebuilding knowledge pack' : 'Working')
  const detail = busy === 'upload'
    ? 'Parsing the document and summarizing each section with the configured LLM.'
    : 'This action can take a few minutes on larger document sets.'

  return (
    <Panel className="p-4 mb-6 border-accent/20 bg-accent/5">
      <div className="flex items-center justify-between gap-3 mb-2">
        <div>
          <p className="text-sm font-semibold text-ink">{label}</p>
          <p className="text-xs text-muted">{detail}</p>
        </div>
        <span className="text-sm font-semibold text-accent">{pct}%</span>
      </div>
      <div className="h-2 w-full overflow-hidden rounded-full bg-surface-2 border border-border">
        <div className="h-full rounded-full bg-accent transition-all duration-300" style={{ width: `${pct}%` }} />
      </div>
      {total > 1 && (
        <p className="mt-2 text-xs text-muted">
          {processed}/{total} sections summarized
        </p>
      )}
    </Panel>
  )
}

function StatCard({ label, value, small = false }) {
  return (
    <Panel className="p-4">
      <div className="text-xs uppercase tracking-wide text-muted">{label}</div>
      <div className={`mt-1 font-display font-bold text-ink ${small ? 'text-sm' : 'text-2xl'}`}>
        {value}
      </div>
    </Panel>
  )
}

function SectionPreview({ section }) {
  return (
    <div className="rounded-lg border border-border bg-surface-2/40 p-3">
      <div className="flex items-center gap-2 flex-wrap mb-1">
        {categoryBadge(section.category)}
        <span className="text-sm font-medium text-ink">{section.heading || '(section)'}</span>
        <span className="text-xs text-muted">· {section.source_filename}</span>
      </div>
      {section.summary && <p className="text-sm text-ink">{section.summary}</p>}
      {section.known_failures?.length > 0 && (
        <ul className="mt-2 list-disc list-inside text-xs text-muted space-y-0.5">
          {section.known_failures.map((kf, i) => (
            <li key={i}>
              {[kf.symptom, kf.root_cause, kf.corrective_action].filter(Boolean).join(' → ')}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
