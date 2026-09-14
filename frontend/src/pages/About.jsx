import { Card, IconWell } from '../components/ui'

const FEATURES = [
  {
    icon: '📤',
    title: 'Batch processing',
    body: 'Load FTRunner folders, individual text logs, or a root-level ZIP. Processing reports its current stage, elapsed time, cache use, and Copilot calls, and can be stopped safely.',
  },
  {
    icon: '🔧',
    title: 'Engineer triage',
    body: 'Search and sort serial groups, start from the highest-volume failure family, inspect every failed attempt, compare retry-pass runs, and re-analyze when new evidence is available.',
  },
  {
    icon: '📊',
    title: 'Yield and drill-down',
    body: 'Review first-pass yield, trends, signature-keyed Pareto failures, stations, and lots. Manager selections open the exact affected units in Engineer view.',
  },
  {
    icon: '◈',
    title: 'Evidence-aware RCA',
    body: 'Diagnoses show confidence, category, likely owner, risk, evidence summary, and next debug action when available, together with the sources that support them.',
  },
  {
    icon: '📚',
    title: 'Debug memory',
    body: 'Product documents, RFC knowledge, and approved acronyms ground analysis. Reviewed known-failure playbooks provide deterministic guidance before cache or Copilot lookup.',
  },
  {
    icon: '✓',
    title: 'Handoff and feedback',
    body: 'Export bounded, redacted Markdown packets for a unit or failure family. Engineers can record whether guidance helped, fixed the issue, or missed the root cause.',
  },
  {
    icon: '🔒',
    title: 'Private by design',
    body: 'Credentials, IPs, hosts, usernames, MAC addresses, and serials are scrubbed before AI calls. Feedback and exports are redacted, job data is owner-scoped, and passing units never trigger analysis.',
  },
  {
    icon: '↔',
    title: 'Production-scale review',
    body: 'Large Engineer result sets are paginated while search, sorting, and filters still evaluate the complete batch, keeping detailed table and card workflows responsive.',
  },
]

const CLASSES = [
  ['First-pass', 'Passed on the first attempt — no analysis needed.', 'text-teal'],
  ['Retry-pass', 'Failed at least once, then passed. Previous failures are diagnosed.', 'text-warning'],
  ['Failing', 'Still failing on the latest attempt. Each failure is diagnosed.', 'text-danger'],
]

const DIAGNOSIS_SOURCES = [
  ['Reviewed playbook', 'An administrator-approved exact signature match, checked before cache or Copilot.', 'text-teal'],
  ['Copilot analysis', 'A fresh diagnosis generated from bounded, redacted evidence and matched product knowledge.', 'text-accent'],
  ['Saved or reused analysis', 'A prior result reused from disk or from a matching signature in the current batch.', 'text-muted'],
  ['Offline placeholder', 'A local fallback when live analysis is unavailable; clearly marked as weak evidence.', 'text-warning'],
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
          <p className="mt-1 text-muted">Manufacturing failure triage and debug handoff</p>
        </div>
      </div>

      <Card className="p-8 mb-8">
        <p className="text-ink leading-relaxed">
          Co-Trace turns raw manufacturing test logs into clear, audience-specific insights.
          Upload a batch of FTRunner logs and the app parses every unit run, protects sensitive
          fields, groups recurring failures by stable signatures, and connects yield signals to
          evidence-backed root-cause guidance, next actions, and reusable debug knowledge.
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

      <h2 className="font-display text-2xl font-bold text-ink mb-4">Where guidance comes from</h2>
      <Card className="p-6 mb-8">
        <ul className="grid gap-4 sm:grid-cols-2">
          {DIAGNOSIS_SOURCES.map(([label, body, tone]) => (
            <li key={label} className="min-w-0 border-l-2 border-border pl-3">
              <div className={['font-semibold', tone].join(' ')}>{label}</div>
              <p className="mt-1 text-sm leading-relaxed text-muted">{body}</p>
            </li>
          ))}
        </ul>
      </Card>

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
        Co-Trace supports triage and evidence review; engineers remain responsible for validating
        diagnoses and confirming corrective actions on the actual unit and station.
      </p>
    </div>
  )
}
