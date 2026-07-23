// Neumorphic UI primitives — the shared building blocks for every surface.

export function Card({ className = '', hover = false, children, ...rest }) {
  return (
    <div
      className={[
        'bg-base rounded-card shadow-extruded transition-all duration-300 ease-out',
        hover ? 'hover:-translate-y-0.5 hover:shadow-extruded-hover' : '',
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
    'font-body font-medium rounded-2xl px-6 py-3 transition-all duration-300 ease-out focus-ring ' +
    'disabled:opacity-50 disabled:cursor-not-allowed'
  const styles =
    variant === 'primary'
      ? 'bg-accent text-white shadow-extruded hover:-translate-y-px hover:shadow-extruded-hover ' +
        'active:translate-y-0.5 active:shadow-inset-sm'
      : 'bg-base text-ink shadow-extruded hover:-translate-y-px hover:shadow-extruded-hover ' +
        'active:translate-y-0.5 active:shadow-inset-sm'
  return (
    <button className={[base, styles, className].join(' ')} {...rest}>
      {children}
    </button>
  )
}

export function Input({ className = '', ...rest }) {
  return (
    <input
      className={[
        'w-full bg-base rounded-2xl px-5 py-3 text-ink placeholder-placeholder',
        'shadow-inset outline-none transition-all duration-300',
        'focus:shadow-inset-deep focus-ring',
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
        'flex items-center justify-center rounded-2xl bg-base shadow-inset-deep',
        className,
      ].join(' ')}
    >
      {children}
    </div>
  )
}

export function Badge({ tone = 'muted', children }) {
  const tones = {
    pass: 'text-teal',
    fail: 'text-danger',
    warn: 'text-warning',
    unknown: 'text-muted',
  }
  return (
    <span
      className={[
        'inline-flex items-center gap-2 rounded-full px-4 py-1.5 text-sm font-semibold bg-base shadow-inset-sm',
        tones[tone] || tones.unknown,
      ].join(' ')}
    >
      <span
        className="h-2 w-2 rounded-full"
        style={{
          backgroundColor:
            tone === 'pass'
              ? 'rgb(var(--color-teal))'
              : tone === 'fail'
                ? 'rgb(var(--color-danger))'
                : tone === 'warn'
                  ? 'rgb(var(--color-warning))'
                  : 'rgb(var(--color-muted))',
        }}
      />
      {children}
    </span>
  )
}

export function Stat({ label, value, accent = false }) {
  return (
    <Card className="p-6">
      <div className="text-sm font-body text-muted">{label}</div>
      <div
        className={[
          'font-display font-extrabold tracking-tight mt-2 text-4xl',
          accent ? 'text-accent' : 'text-ink',
        ].join(' ')}
      >
        {value}
      </div>
    </Card>
  )
}
