import { useId, useMemo, useState } from 'react'

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
}) {
  const [query, setQuery] = useState('')
  const searchId = useId()

  const allLines = useMemo(() => (text ? String(text).split(/\r?\n/) : []), [text])
  const hasContent = allLines.some((l) => l.trim().length > 0)

  const lines = useMemo(() => {
    if (!query) return allLines.map((line, i) => ({ line, n: i + 1 }))
    const needle = query.toLowerCase()
    return allLines
      .map((line, i) => ({ line, n: i + 1 }))
      .filter(({ line }) => line.toLowerCase().includes(needle))
  }, [allLines, query])

  return (
    <section className="overflow-hidden rounded-panel border border-term-border bg-term-bg font-mono">
      {/* Header */}
      <div className="flex flex-wrap items-center gap-2 border-b border-term-border bg-term-surface px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className="flex gap-1.5" aria-hidden="true">
            <span className="h-2.5 w-2.5 rounded-full bg-term-error/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-term-warn/70" />
            <span className="h-2.5 w-2.5 rounded-full bg-term-success/70" />
          </span>
          <span className="text-xs font-semibold text-term-text">{title}</span>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
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
          placeholder="Filter lines…"
          className="w-48 rounded-md border border-term-border bg-term-bg px-2.5 py-1.5 text-xs text-term-text placeholder-term-muted outline-none focus-visible:border-term-accent focus-visible:outline-none"
        />
        <span className="text-xs text-term-muted">
          {query ? `${lines.length} of ${allLines.length} lines` : `${allLines.length} lines`}
        </span>
      </div>

      {/* Body */}
      {!hasContent ? (
        <div className="px-4 py-10 text-center text-xs text-term-muted">
          No trace snippet available for this attempt.
        </div>
      ) : lines.length === 0 ? (
        <div className="px-4 py-10 text-center text-xs text-term-muted">
          No lines match “{query}”.
        </div>
      ) : (
        <div className="max-h-96 overflow-auto px-2 py-3">
          <div>
            {lines.map(({ line, n }) => (
              <div key={n} className="flex gap-3 px-2 leading-relaxed">
                <span className="w-10 shrink-0 select-none text-right text-xs text-term-muted/60">
                  {n}
                </span>
                <code
                  className={['text-xs whitespace-pre-wrap break-words', severityClass(line)].join(' ')}
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
    <span className={['rounded border px-1.5 py-0.5 text-[11px] font-medium', cls].join(' ')}>
      {children}
    </span>
  )
}
