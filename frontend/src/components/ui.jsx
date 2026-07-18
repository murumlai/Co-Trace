export function Card({ className = '', hover = false, children, ...rest }) {
  return (
    <div
      className={[
        'rounded-card border border-border bg-card shadow-soft transition-all duration-300 ease-out',
        hover ? 'hover:-translate-y-0.5 hover:shadow-lift' : '',
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
      ? 'bg-gradient-to-r from-accent to-accent-secondary text-white shadow-accent hover:-translate-y-0.5 hover:brightness-110 active:scale-[0.98]'
      : variant === 'ghost'
        ? 'text-muted hover:bg-surface hover:text-foreground active:scale-[0.98]'
        : ''
  const secondary =
    variant === 'secondary'
      ? 'border border-border bg-card text-foreground shadow-soft hover:-translate-y-0.5 hover:border-accent/30 hover:shadow-lift active:scale-[0.98]'
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
        'flex items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent-secondary text-white shadow-accent',
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
    <Card className="p-5 md:p-6" hover>
      <div className="font-mono text-xs uppercase tracking-[0.15em] text-muted">{label}</div>
      <div
        className={[
          'mt-3 font-display text-3xl md:text-4xl',
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
