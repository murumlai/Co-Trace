// Hybrid UI primitives — enterprise light-shell building blocks.
//
// Surfaces use borders + subtle low-blur elevation instead of the old
// Neumorphic extruded/inset shadows. Every color token is theme-aware (defined
// for both light and enterprise-dark in index.css).

/* --------------------------------------------------------------------------
 * Containers
 * ------------------------------------------------------------------------ */

export function Card({ className = '', hover = false, children, ...rest }) {
  return (
    <div
      className={[
        'bg-surface border border-border rounded-panel shadow-sm transition-shadow duration-200',
        hover ? 'hover:shadow-md' : '',
        className,
      ].join(' ')}
      {...rest}
    >
      {children}
    </div>
  )
}

// Flush secondary surface for nested sections (no elevation).
export function Panel({ className = '', children, ...rest }) {
  return (
    <div
      className={['bg-surface-2 border border-border rounded-panel', className].join(' ')}
      {...rest}
    >
      {children}
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Controls
 * ------------------------------------------------------------------------ */

const BUTTON_VARIANTS = {
  primary:
    'bg-accent text-white border border-transparent hover:bg-accent-hover shadow-sm',
  secondary:
    'bg-surface text-ink border border-border hover:bg-surface-2 hover:border-border-strong',
  ghost: 'bg-transparent text-ink-2 border border-transparent hover:bg-surface-2',
  danger:
    'bg-surface text-danger border border-border hover:border-danger hover:bg-danger/5',
}

export function Button({ variant = 'secondary', className = '', children, ...rest }) {
  const base =
    'inline-flex items-center justify-center gap-2 font-body font-medium rounded-lg px-4 py-2.5 ' +
    'text-sm transition-colors duration-150 focus-ring disabled:opacity-50 disabled:cursor-not-allowed'
  return (
    <button className={[base, BUTTON_VARIANTS[variant] || BUTTON_VARIANTS.secondary, className].join(' ')} {...rest}>
      {children}
    </button>
  )
}

// Compact button used inside filter/action toolbars, with an active state.
export function ToolbarButton({ active = false, className = '', children, ...rest }) {
  return (
    <button
      className={[
        'inline-flex items-center gap-2 rounded-lg px-3.5 py-2 text-sm font-medium transition-colors duration-150 focus-ring',
        active
          ? 'bg-accent/10 text-accent border border-accent/30'
          : 'bg-surface text-ink-2 border border-border hover:bg-surface-2 hover:text-ink',
        className,
      ].join(' ')}
      {...rest}
    >
      {children}
    </button>
  )
}

export function Input({ className = '', ...rest }) {
  return (
    <input
      className={[
        'w-full bg-surface border border-border rounded-lg px-3.5 py-2.5 text-ink placeholder-placeholder',
        'outline-none transition-colors duration-150 focus:border-accent focus-ring',
        className,
      ].join(' ')}
      {...rest}
    />
  )
}

// A grouped set of mutually-exclusive options (view switchers, small filters).
export function SegmentedControl({ options, value, onChange, className = '' }) {
  return (
    <div
      className={[
        'inline-flex items-center gap-1 rounded-lg bg-surface-2 border border-border p-1',
        className,
      ].join(' ')}
      role="tablist"
    >
      {options.map(([key, label]) => {
        const selected = value === key
        return (
          <button
            key={key}
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(key)}
            className={[
              'rounded-md px-3.5 py-1.5 text-sm font-medium transition-colors duration-150 focus-ring',
              selected ? 'bg-surface text-accent shadow-sm' : 'text-muted hover:text-ink',
            ].join(' ')}
          >
            {label}
          </button>
        )
      })}
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Iconography
 * ------------------------------------------------------------------------ */

export function IconWell({ children, className = '' }) {
  return (
    <div
      className={[
        'flex items-center justify-center rounded-lg bg-surface-2 border border-border',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  )
}

/* --------------------------------------------------------------------------
 * Status + badges
 * ------------------------------------------------------------------------ */

const TONES = {
  pass: 'text-teal bg-teal/10 border-teal/20',
  fail: 'text-danger bg-danger/10 border-danger/20',
  warn: 'text-warning bg-warning/10 border-warning/20',
  accent: 'text-accent bg-accent/10 border-accent/20',
  muted: 'text-muted bg-surface-2 border-border',
  unknown: 'text-muted bg-surface-2 border-border',
}

const DOT = {
  pass: 'bg-teal',
  fail: 'bg-danger',
  warn: 'bg-warning',
  accent: 'bg-accent',
  muted: 'bg-muted',
  unknown: 'bg-muted',
}

export function Badge({ tone = 'muted', dot = true, children }) {
  return (
    <span
      className={[
        'inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold',
        TONES[tone] || TONES.muted,
      ].join(' ')}
    >
      {dot && <span className={['h-1.5 w-1.5 rounded-full', DOT[tone] || DOT.muted].join(' ')} />}
      {children}
    </span>
  )
}

// Maps a unit classification / result to a labelled status badge.
const STATUS_META = {
  first_pass: { tone: 'pass', label: 'First-pass' },
  retry_pass: { tone: 'warn', label: 'Retry-pass' },
  fail: { tone: 'fail', label: 'Failing' },
  unknown: { tone: 'unknown', label: 'Unknown' },
  PASS: { tone: 'pass', label: 'Pass' },
  FAIL: { tone: 'fail', label: 'Fail' },
  UNKNOWN: { tone: 'unknown', label: 'Unknown' },
}

export function StatusBadge({ status, label }) {
  const meta = STATUS_META[status] || STATUS_META.unknown
  return <Badge tone={meta.tone}>{label || meta.label}</Badge>
}

/* --------------------------------------------------------------------------
 * Metrics
 * ------------------------------------------------------------------------ */

const METRIC_TONE = {
  default: 'text-ink',
  accent: 'text-accent',
  pass: 'text-teal',
  fail: 'text-danger',
  warn: 'text-warning',
}

export function MetricCard({ label, value, tone = 'default', hint = null, className = '' }) {
  return (
    <Card className={['p-5', className].join(' ')}>
      <div className="text-xs font-medium uppercase tracking-wide text-muted">{label}</div>
      <div
        className={[
          'mt-2 font-display font-extrabold tracking-tight text-3xl leading-none',
          METRIC_TONE[tone] || METRIC_TONE.default,
        ].join(' ')}
      >
        {value}
      </div>
      {hint && <div className="mt-2 text-xs text-muted">{hint}</div>}
    </Card>
  )
}

// Back-compat alias — behaves like MetricCard with the accent flag.
export function Stat({ label, value, accent = false }) {
  return <MetricCard label={label} value={value} tone={accent ? 'accent' : 'default'} />
}

/* --------------------------------------------------------------------------
 * Tables
 * ------------------------------------------------------------------------ */

// Card-wrapped, horizontally-scrollable table shell. Caller supplies the
// <thead>/<tbody> as children.
export function TableShell({ className = '', children }) {
  return (
    <Card className={['p-0 overflow-hidden', className].join(' ')}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">{children}</table>
      </div>
    </Card>
  )
}
