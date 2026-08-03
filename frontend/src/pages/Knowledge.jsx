import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../api'
import { Badge, Button, Card, Input, Panel, SegmentedControl } from '../components/ui'
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

      <AcronymGlossary />

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

const ACRONYM_STATUS_TONE = {
  approved: 'pass',
  needs_review: 'warn',
  rejected: 'muted',
}
const ACRONYM_STATUS_LABEL = {
  approved: 'Approved',
  needs_review: 'Pending',
  rejected: 'Rejected',
}

function acronymStatusBadge(status) {
  return (
    <Badge tone={ACRONYM_STATUS_TONE[status] || 'muted'} dot={false}>
      {ACRONYM_STATUS_LABEL[status] || status}
    </Badge>
  )
}

const ACRONYM_STATUS_FILTERS = [
  ['', 'All'],
  ['needs_review', 'Pending'],
  ['approved', 'Approved'],
  ['rejected', 'Rejected'],
]

function AcronymGlossary() {
  const [entries, setEntries] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [productFilter, setProductFilter] = useState('')
  const [busy, setBusy] = useState('')
  const [form, setForm] = useState({ acronym: '', definition: '', product_code: '', status: 'approved' })

  const load = async () => {
    setLoading(true)
    try {
      const data = await api.acronyms()
      setEntries(data.entries || [])
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

  const filtered = useMemo(() => {
    const product = productFilter.trim().toLowerCase()
    return entries.filter((e) => {
      if (statusFilter && e.status !== statusFilter) return false
      if (product) {
        const scope = (e.product_code || 'global').toLowerCase()
        if (!scope.includes(product) && !e.acronym.toLowerCase().includes(product)) return false
      }
      return true
    })
  }, [entries, statusFilter, productFilter])

  const counts = useMemo(() => {
    const c = { approved: 0, needs_review: 0, rejected: 0 }
    entries.forEach((e) => {
      c[e.status] = (c[e.status] || 0) + 1
    })
    return c
  }, [entries])

  const apply = async (entry, changes) => {
    const key = `${entry.acronym}:${entry.product_code || ''}`
    setBusy(key)
    setError('')
    setNotice('')
    try {
      await api.upsertAcronym({
        acronym: entry.acronym,
        product_code: entry.product_code || null,
        definition: changes.definition ?? null,
        status: changes.status,
      })
      await load()
      setNotice(`${entry.acronym} ${changes.status === 'approved' ? 'approved' : 'updated'}.`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const remove = async (entry) => {
    const key = `${entry.acronym}:${entry.product_code || ''}`
    setBusy(key)
    setError('')
    setNotice('')
    try {
      await api.deleteAcronym(entry.acronym, entry.product_code || undefined)
      await load()
      setNotice(`Deleted ${entry.acronym}.`)
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  const addEntry = async (event) => {
    event.preventDefault()
    const acronym = form.acronym.trim()
    if (!acronym) {
      setError('Acronym is required.')
      return
    }
    if (form.status === 'approved' && !form.definition.trim()) {
      setError('A definition is required to approve an acronym.')
      return
    }
    setBusy('add')
    setError('')
    setNotice('')
    try {
      await api.upsertAcronym({
        acronym,
        definition: form.definition.trim() || null,
        product_code: form.product_code.trim() || null,
        status: form.status,
      })
      setForm({ acronym: '', definition: '', product_code: '', status: 'approved' })
      await load()
      setNotice(`Saved ${acronym.toUpperCase()}.`)
      log('info', 'Acronym saved', { acronym })
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy('')
    }
  }

  return (
    <Card className="mt-8 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="font-display text-xl font-bold text-ink">Acronym glossary</h2>
          <p className="mt-1 text-sm text-muted">
            Approved expansions are injected into every failure diagnosis. Only{' '}
            <span className="text-ink">approved</span> entries are used by the model — pending
            acronyms are shown for review and never expanded until you approve them.
          </p>
        </div>
        <div className="flex gap-2 text-xs text-muted">
          <span>{counts.approved} approved</span>
          <span>·</span>
          <span className="text-warning">{counts.needs_review} pending</span>
          <span>·</span>
          <span>{counts.rejected} rejected</span>
        </div>
      </div>

      {error && (
        <Panel className="p-3 mb-3 border-danger/30 bg-danger/5">
          <p className="text-sm text-danger">{error}</p>
        </Panel>
      )}
      {notice && (
        <Panel className="p-3 mb-3 border-teal/30 bg-teal/5">
          <p className="text-sm text-teal">{notice}</p>
        </Panel>
      )}

      <form onSubmit={addEntry} className="mb-4 grid grid-cols-1 gap-2 md:grid-cols-[110px_1fr_140px_140px_auto]">
        <Input
          placeholder="ACRONYM"
          value={form.acronym}
          onChange={(e) => setForm({ ...form, acronym: e.target.value })}
        />
        <Input
          placeholder="Definition (required to approve)"
          value={form.definition}
          onChange={(e) => setForm({ ...form, definition: e.target.value })}
        />
        <Input
          placeholder="Product (blank = global)"
          value={form.product_code}
          onChange={(e) => setForm({ ...form, product_code: e.target.value })}
        />
        <select
          className="w-full bg-surface border border-border rounded-lg px-3 py-2.5 text-sm text-ink focus-ring"
          value={form.status}
          onChange={(e) => setForm({ ...form, status: e.target.value })}
        >
          <option value="approved">Approved</option>
          <option value="needs_review">Pending</option>
          <option value="rejected">Rejected</option>
        </select>
        <Button type="submit" variant="primary" disabled={busy === 'add'}>
          {busy === 'add' ? 'Saving…' : 'Add'}
        </Button>
      </form>

      <div className="flex flex-wrap items-center gap-3 mb-3">
        <SegmentedControl options={ACRONYM_STATUS_FILTERS} value={statusFilter} onChange={setStatusFilter} />
        <Input
          className="max-w-xs"
          placeholder="Filter by product or acronym…"
          value={productFilter}
          onChange={(e) => setProductFilter(e.target.value)}
        />
      </div>

      {loading ? (
        <p className="text-sm text-muted">Loading acronyms…</p>
      ) : filtered.length === 0 ? (
        <p className="text-sm text-muted">
          No acronyms {entries.length ? 'match the filter' : 'yet'}. Pending entries appear here
          automatically as new acronyms are observed in failed runs.
        </p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-muted border-b border-border">
                <th className="py-2 pr-3">Acronym</th>
                <th className="py-2 pr-3">Scope</th>
                <th className="py-2 pr-3">Status</th>
                <th className="py-2 pr-3">Definition</th>
                <th className="py-2 pr-3">Observed</th>
                <th className="py-2">Actions</th>
              </tr>
            </thead>
            <tbody>
              {filtered.map((entry) => (
                <AcronymRow
                  key={`${entry.acronym}:${entry.product_code || ''}`}
                  entry={entry}
                  busy={busy}
                  onApply={apply}
                  onDelete={remove}
                />
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}

function AcronymRow({ entry, busy, onApply, onDelete }) {
  const [definition, setDefinition] = useState(entry.definition || '')
  const key = `${entry.acronym}:${entry.product_code || ''}`
  const rowBusy = busy === key
  const dirty = (definition || '') !== (entry.definition || '')

  return (
    <tr className="border-b border-border/60 align-top">
      <td className="py-2 pr-3 font-mono font-semibold text-ink">{entry.acronym}</td>
      <td className="py-2 pr-3 text-muted">{entry.product_code || 'global'}</td>
      <td className="py-2 pr-3">{acronymStatusBadge(entry.status)}</td>
      <td className="py-2 pr-3 min-w-[200px]">
        <Input
          value={definition}
          onChange={(e) => setDefinition(e.target.value)}
          placeholder={entry.status === 'needs_review' ? 'Enter an approved definition…' : 'Definition'}
        />
      </td>
      <td className="py-2 pr-3 text-xs text-muted whitespace-nowrap">
        {entry.observed_count || 0}
        {entry.observed_in_fields?.length ? ` · ${entry.observed_in_fields.join(', ')}` : ''}
      </td>
      <td className="py-2">
        <div className="flex flex-wrap gap-2 text-xs">
          {entry.status !== 'approved' && (
            <button
              className="text-teal hover:underline focus-ring rounded px-1 disabled:opacity-40"
              onClick={() => onApply(entry, { status: 'approved', definition })}
              disabled={rowBusy || !definition.trim()}
            >
              Approve
            </button>
          )}
          {entry.status === 'approved' && (
            <button
              className="text-accent hover:underline focus-ring rounded px-1 disabled:opacity-40"
              onClick={() => onApply(entry, { status: 'approved', definition })}
              disabled={rowBusy || !definition.trim() || !dirty}
            >
              Save
            </button>
          )}
          {entry.status !== 'rejected' && (
            <button
              className="text-warning hover:underline focus-ring rounded px-1 disabled:opacity-40"
              onClick={() => onApply(entry, { status: 'rejected', definition })}
              disabled={rowBusy}
            >
              Reject
            </button>
          )}
          {entry.status === 'rejected' && (
            <button
              className="text-ink-2 hover:underline focus-ring rounded px-1 disabled:opacity-40"
              onClick={() => onApply(entry, { status: 'needs_review', definition })}
              disabled={rowBusy}
            >
              Restore
            </button>
          )}
          <button
            className="text-danger hover:underline focus-ring rounded px-1 disabled:opacity-40"
            onClick={() => onDelete(entry)}
            disabled={rowBusy}
          >
            Delete
          </button>
        </div>
      </td>
    </tr>
  )
}

