import { Card, IconWell } from '../components/ui'

const FEATURES = [
  {
    icon: '📤',
    title: 'Upload logs',
    body: 'Drop FTRunner log folders, individual files, or a single root-level .zip archive for large batches. Processing runs asynchronously with progress polling and manual stop support.',
  },
  {
    icon: '🔧',
    title: 'Engineer view',
    body: 'One row per serial number, classified as first-pass, retry-pass, or failing. Failed attempts get root-cause guidance, log evidence, cache controls, and manual re-analysis.',
  },
  {
    icon: '📊',
    title: 'Manager view',
    body: 'First-pass yield, yield trend, a Pareto of failure reasons, station/tester breakdown, and lot-to-lot comparison.',
  },
  {
    icon: '🔒',
    title: 'Private by design',
    body: 'Credentials, IPs, hostnames, usernames, and MAC addresses are scrubbed from stored artifacts and from text sent to the AI. Serial numbers are retained in stored data for yield math but are scrubbed before any AI call. Passing units never trigger an AI call.',
  },
]

const CLASSES = [
  ['First-pass', 'Passed on the first attempt — no analysis needed.', 'text-teal'],
  ['Retry-pass', 'Failed at least once, then passed. Previous failures are diagnosed.', 'text-warning'],
  ['Failing', 'Still failing on the latest attempt. Each failure is diagnosed.', 'text-danger'],
]

export default function About() {
  return (
    <div className="mx-auto max-w-4xl px-6 py-12">
      <div className="flex items-center gap-4 mb-8">
        <IconWell className="h-14 w-14 shrink-0">
          <span className="text-2xl">🧭</span>
        </IconWell>
        <div>
          <h1 className="font-display text-4xl font-extrabold tracking-tight text-ink">About Co-Trace</h1>
          <p className="mt-1 text-muted">Manufacturing test-log dashboard</p>
        </div>
      </div>

      <Card className="p-8 mb-8">
        <p className="text-ink leading-relaxed">
          Co-Trace turns raw manufacturing test logs into clear, audience-specific insights.
          Upload a batch of FTRunner logs and the app parses every unit run, protects sensitive
          fields, separates first-pass, retry-pass, and failing units, and turns failed attempts
          into actionable evidence for engineers and yield trends for managers.
        </p>
      </Card>

      <h2 className="font-display text-2xl font-bold text-ink mb-4">What it does</h2>
      <div className="grid gap-6 sm:grid-cols-2 mb-8">
        {FEATURES.map((f) => (
          <Card key={f.title} className="p-6">
            <div className="flex items-start gap-4">
              <IconWell className="h-11 w-11 shrink-0">
                <span className="text-lg">{f.icon}</span>
              </IconWell>
              <div>
                <h3 className="font-display font-bold text-ink">{f.title}</h3>
                <p className="mt-1 text-sm text-muted leading-relaxed">{f.body}</p>
              </div>
            </div>
          </Card>
        ))}
      </div>

      <h2 className="font-display text-2xl font-bold text-ink mb-4">How units are classified</h2>
      <Card className="p-6 mb-8">
        <ul className="space-y-4">
          {CLASSES.map(([label, body, tone]) => (
            <li key={label} className="flex items-start gap-3">
              <span className={['mt-1 h-2 w-2 rounded-full shrink-0', tone].join(' ')} style={{ backgroundColor: 'currentColor' }} />
              <div>
                <span className={['font-semibold', tone].join(' ')}>{label}</span>
                <span className="text-muted"> — {body}</span>
              </div>
            </li>
          ))}
        </ul>
        <div className="mt-5 rounded-lg border border-border bg-surface/70 p-4 text-sm text-muted leading-relaxed">
          Runs without a done block are handled by mode. TestApp logs with no ERR line remain
          implicit PASS. APSE logs use a dynamic threshold from explicit PASS durations for the
          same product and OPID, with a 5 second floor, so near-instant FTRunner aborts are
          classified as FAIL.
        </div>
      </Card>

      <p className="text-sm text-muted text-center">
        Upload a batch on the Home tab to get started.
      </p>
    </div>
  )
}
