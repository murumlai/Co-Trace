import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { buildEvidenceView, moveMatch, visibleEvidenceText } from '../logEvidence'

// Severity keywords, ordered by precedence (highest first). A line is colored
// by the highest-precedence keyword it contains.
const SEVERITY = [
  { level: 'error', re: /\b(CRITICAL|FAILED|FAIL|ERROR|ERR)\b/i, cls: 'text-term-error' },
  { level: 'warn', re: /\b(WARNING|WARN)\b/i, cls: 'text-term-warn' },
  { level: 'info', re: /\b(INFO)\b/i, cls: 'text-term-accent' },
]

function severityClass(line) {
  for (const s of SEVERITY) {
    if (s.re.test(line)) return s.cls
  }
  return 'text-term-text'
}

// Split a line around case-insensitive matches of `query`, wrapping matches in
// a highlight span. Returns an array of React nodes.
function highlightMatches(line, query, keyPrefix) {
  if (!query) return line
  const lower = line.toLowerCase()
  const needle = query.toLowerCase()
  const nodes = []
  let from = 0
  let idx = lower.indexOf(needle, from)
  let n = 0
  while (idx !== -1) {
    if (idx > from) nodes.push(line.slice(from, idx))
    nodes.push(
      <mark key={`${keyPrefix}-${n++}`} className="rounded bg-term-accent/30 text-term-text">
        {line.slice(idx, idx + needle.length)}
      </mark>,
    )
    from = idx + needle.length
    idx = lower.indexOf(needle, from)
  }
  if (from < line.length) nodes.push(line.slice(from))
  return nodes
}

/**
 * TerminalViewer — terminal-dark viewer for raw/redacted trace snippets.
 *
 * Props:
 *  - text: raw or redacted snippet string.
 *  - title?: heading label (default "Log trace").
 *  - sourceLabel?: small chip describing the analysis/source origin.
 *  - errorCode?: error code chip.
 *  - failingStep?: failing step chip.
 *  - timestamp?: timestamp chip.
 */
export default function TerminalViewer({
  text,
  title = 'Log trace',
  sourceLabel = null,
  errorCode = null,
  failingStep = null,
  timestamp = null,
  focusLine = null,
}) {
  const [query, setQuery] = useState('')
  const [activeMatch, setActiveMatch] = useState(0)
  const [wrap, setWrap] = useState(true)
  const [copyStatus, setCopyStatus] = useState('')
  const searchId = useId()
  const sectionRef = useRef(null)
  const lineRefs = useRef(new Map())

  const view = useMemo(() => buildEvidenceView(text, query), [query, text])
  const hasContent = useMemo(
    () => String(text || '').split(/\r?\n/).some((line) => line.trim().length > 0),
    [text],
  )
  const currentLine = view.matchIndexes[activeMatch] == null ? null : view.matchIndexes[activeMatch] + 1

  useEffect(() => {
    setActiveMatch(0)
    setCopyStatus('')
  }, [query, text])

  useEffect(() => {
    if (currentLine != null) lineRefs.current.get(currentLine)?.scrollIntoView({ block: 'center' })
  }, [currentLine])

  useEffect(() => {
    if (focusLine != null) {
      setQuery('')
      lineRefs.current.get(focusLine)?.scrollIntoView({ block: 'center' })
    }
  }, [focusLine, view.lines])

  const navigateMatches = (direction) => {
    setActiveMatch((current) => moveMatch(current, direction, view.matchIndexes.length))
  }

  const copyEvidence = async () => {
    const selection = window.getSelection?.()
    const selected = selection?.anchorNode && sectionRef.current?.contains(selection.anchorNode)
      ? selection.toString().trim()
      : ''
    const copyText = selected || visibleEvidenceText(view.lines)
    if (!copyText) return
    try {
      await navigator.clipboard.writeText(copyText)
      setCopyStatus(selected ? 'Selected evidence copied' : 'Visible evidence copied')
    } catch {
      setCopyStatus('Copy was blocked by the browser')
    }
  }

  return (
    <section ref={sectionRef} className="min-w-0 max-w-full overflow-hidden rounded-panel border border-term-border bg-term-bg font-mono">
      {/* Header */}
      <div className="flex min-w-0 flex-wrap items-center gap-2 border-b border-term-border bg-term-surface px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="flex gap-1.5" aria-hidden="true">
            <span className="h-2.5 w-2.5 rounded-full bg-term-error/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-term-warn/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-term-success/70" />
          </span>
          <span className="text-xs font-semibold text-term-text">{title}</span>
        </div>
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5">
          {timestamp && <Chip accent>{timestamp}</Chip>}
          {errorCode && <Chip tone="error">{errorCode}</Chip>}
          {failingStep && <Chip>step: {failingStep}</Chip>}
          {sourceLabel && <Chip>{sourceLabel}</Chip>}
        </div>
      </div>

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-3 border-b border-term-border bg-term-surface/60 px-4 py-2">
        <label htmlFor={searchId} className="sr-only">
          Filter log lines
        </label>
        <input
          id={searchId}
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && view.matchIndexes.length) {
              event.preventDefault()
              navigateMatches(event.shiftKey ? -1 : 1)
            }
          }}
          placeholder="Filter lines…"
          className="w-48 rounded-md border border-term-border bg-term-bg px-2.5 py-1.5 text-xs text-term-text placeholder-term-muted outline-none focus-visible:border-term-accent focus-visible:outline-none"
        />
        <span className="text-xs text-term-muted">
          {query
            ? `${view.matchIndexes.length} match${view.matchIndexes.length === 1 ? '' : 'es'} · ${view.lines.length} of ${view.allLineCount} lines shown`
            : `${view.allLineCount} excerpt lines`}
        </span>
        <div className="ml-auto flex items-center gap-1">
          <button type="button" aria-label="Previous match" title="Previous match" disabled={!view.matchIndexes.length} onClick={() => navigateMatches(-1)} className="h-8 w-8 rounded-md border border-term-border text-term-text hover:bg-term-bg focus-visible:outline-none disabled:opacity-40">↑</button>
          <span className="min-w-14 text-center text-xs text-term-muted">{view.matchIndexes.length ? `${activeMatch + 1}/${view.matchIndexes.length}` : '0/0'}</span>
          <button type="button" aria-label="Next match" title="Next match" disabled={!view.matchIndexes.length} onClick={() => navigateMatches(1)} className="h-8 w-8 rounded-md border border-term-border text-term-text hover:bg-term-bg focus-visible:outline-none disabled:opacity-40">↓</button>
          <label className="ml-2 flex items-center gap-1.5 text-xs text-term-muted">
            <input type="checkbox" checked={wrap} onChange={(event) => setWrap(event.target.checked)} className="accent-cyan-500" />
            Wrap
          </label>
          <button type="button" disabled={!view.lines.length} onClick={copyEvidence} className="ml-2 rounded-md border border-term-border px-2.5 py-1.5 text-xs text-term-text hover:bg-term-bg focus-visible:outline-none disabled:opacity-40">Copy</button>
        </div>
      </div>

      {(query || copyStatus) && (
        <div role="status" className="border-b border-term-border bg-term-surface/40 px-4 py-1.5 text-xs text-term-muted">
          {copyStatus || (view.matchIndexes.length ? 'Showing two excerpt lines before and after each match.' : 'No matching excerpt lines.')}
        </div>
      )}

      {/* Body */}
      {!hasContent ? (
        <div className="px-4 py-10 text-center text-xs text-term-muted">
          No trace snippet available for this attempt.
        </div>
      ) : view.lines.length === 0 ? (
        <div className="px-4 py-10 text-center text-xs text-term-muted">
          No lines match “{query}”.
        </div>
      ) : (
        <div className="max-h-96 max-w-full overflow-auto px-2 py-3">
          <div className="min-w-0">
            {view.lines.map(({ line, n, isMatch }) => (
              <div
                key={n}
                ref={(element) => {
                  if (element) lineRefs.current.set(n, element)
                  else lineRefs.current.delete(n)
                }}
                className={[
                  'flex min-w-0 gap-3 border-l-2 px-2 leading-relaxed',
                  n === currentLine || n === focusLine ? 'border-term-accent bg-term-accent/10' : 'border-transparent',
                ].join(' ')}
              >
                <span className="w-10 shrink-0 select-none text-right text-xs text-term-muted/60">
                  {n}
                </span>
                <code
                  className={[
                    'min-w-0 flex-1 text-xs',
                    wrap ? 'whitespace-pre-wrap break-words [overflow-wrap:anywhere]' : 'whitespace-pre',
                    isMatch ? 'font-semibold' : '',
                    severityClass(line),
                  ].join(' ')}
                >
                  {line ? highlightMatches(line, query, n) : '\u00A0'}
                </code>
              </div>
            ))}
          </div>
        </div>
      )}
    </section>
  )
}

function Chip({ children, tone = 'muted', accent = false }) {
  const cls = accent
    ? 'text-term-accent border-term-accent/30'
    : tone === 'error'
      ? 'text-term-error border-term-error/30'
      : 'text-term-muted border-term-border'
  return (
    <span className={[
      'max-w-full rounded border px-1.5 py-0.5 text-[11px] font-medium break-words [overflow-wrap:anywhere]',
      cls,
    ].join(' ')}>
      {children}
    </span>
  )
}
