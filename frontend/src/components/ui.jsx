export function Card({ className = '', hover = false, children, ...rest }) {
  return (
    <div
      className={[
        'rounded-card border border-border bg-card transition-all duration-200 ease-out',
        hover ? 'hover:-translate-y-px hover:border-accent/30 hover:shadow-soft' : '',
        className,
      ].join(' ')}
      {...rest}
    >
      {children}
    </div>
  )
}

export function Button({ variant = 'secondary', className = '', children, ...rest }) {
  const base =
    'group inline-flex min-h-12 items-center justify-center rounded-xl px-5 py-3 font-body text-sm font-semibold transition-all duration-200 ease-out focus-ring ' +
    'disabled:opacity-50 disabled:cursor-not-allowed'
  const styles =
    variant === 'primary'
      ? 'bg-gradient-to-r from-accent to-accent-secondary text-white hover:-translate-y-0.5 hover:shadow-accent hover:brightness-110 active:scale-[0.98]'
      : variant === 'ghost'
        ? 'text-muted hover:bg-surface hover:text-foreground active:scale-[0.98]'
        : ''
  const secondary =
    variant === 'secondary'
      ? 'border border-border bg-card text-foreground hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-soft active:scale-[0.98]'
      : ''
  return (
    <button className={[base, styles, secondary, className].join(' ')} {...rest}>
      {children}
    </button>
  )
}

export function Input({ className = '', ...rest }) {
  return (
    <input
      className={[
        'h-12 w-full rounded-xl border border-border bg-white px-4 text-foreground placeholder-placeholder',
        'outline-none transition-all duration-200 focus:border-accent focus:ring-4 focus:ring-accent/10',
        className,
      ].join(' ')}
      {...rest}
    />
  )
}

export function IconWell({ children, className = '' }) {
  return (
    <div
      className={[
        'flex items-center justify-center rounded-lg bg-gradient-to-br from-accent to-accent-secondary text-white',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  )
}

export function Badge({ tone = 'muted', children }) {
  const tones = {
    pass: 'border-success/25 bg-success/10 text-success',
    fail: 'border-danger/25 bg-danger/10 text-danger',
    unknown: 'border-border bg-surface text-muted',
    accent: 'border-accent/30 bg-accent/5 text-accent',
  }
  const dot = tone === 'pass' ? '#059669' : tone === 'fail' ? '#DC2626' : tone === 'accent' ? '#0052FF' : '#64748B'
  return (
    <span
      className={[
        'inline-flex items-center gap-2 rounded-full border px-3 py-1.5 font-mono text-xs uppercase tracking-[0.15em]',
        tones[tone] || tones.unknown,
      ].join(' ')}
    >
      <span className="h-2 w-2 rounded-full animate-pulse-dot" style={{ backgroundColor: dot }} />
      {children}
    </span>
  )
}

export function Stat({ label, value, accent = false }) {
  return (
    <Card className="p-4 md:p-5" hover>
      <div className="font-mono text-xs uppercase tracking-[0.15em] text-muted">{label}</div>
      <div
        className={[
          'mt-3 text-3xl font-semibold tracking-tight md:text-4xl',
          accent ? 'gradient-text' : 'text-foreground',
        ].join(' ')}
      >
        {value}
      </div>
    </Card>
  )
}

export function SectionLabel({ children }) {
  return <Badge tone="accent">{children}</Badge>
}
