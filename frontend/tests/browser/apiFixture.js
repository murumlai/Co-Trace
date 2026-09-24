const sharedUser = {
  workspace_id: 'shared-workspace',
  username: 'shared-workspace',
  is_admin: false,
}

const completedJob = {
  job_id: 'synthetic-job',
  display_name: 'Synthetic batch',
  created_at: 1_790_121_600,
  status: 'done',
  result_available: true,
  unit_count: 0,
}

export const managerView = {
  batch: {
    display_name: completedJob.display_name,
    product_codes: [],
    included_run_count: 0,
    discovered_run_count: 0,
  },
  summary: {
    total_runs: 0,
    unique_units: 0,
    passed: 0,
    failed: 0,
    unknown: 0,
    fpy: 0,
    fpy_pass: 0,
    fpy_total: 0,
    retests: 0,
    latest_yield: 0,
    latest_yield_pass: 0,
    latest_yield_total: 0,
    recovered_after_retry: 0,
    additional_attempt_share: 0,
  },
  scope: {
    attempt_ids: [],
    unit_ids: [],
    selected_attempt_count: 0,
    missing_timestamp_excluded: 0,
    options: { products: [], lots: [], stations: [] },
  },
  trend: [],
  pareto: [],
  stations: [],
  lots: [],
}

const defaultResponses = new Map([
  ['GET /api/me', sharedUser],
  ['POST /api/auth/admin/login', { user: { ...sharedUser, username: 'admin', is_admin: true } }],
  ['POST /api/logout', { ok: true }],
  ['POST /api/logs/frontend', { ok: true }],
  ['GET /api/jobs', { items: [completedJob], next_cursor: null }],
  ['GET /api/jobs/synthetic-job/status', {
    status: 'done',
    progress: { stage: 'complete', processed: 0, total: 0 },
    message: 'Analysis complete',
    elapsed_s: 1,
    warnings: [],
  }],
  ['GET /api/jobs/synthetic-job/units', { units: [], run_count: 0 }],
  ['GET /api/jobs/synthetic-job/clusters', { clusters: [] }],
  ['GET /api/jobs/synthetic-job/feedback', { entries: [] }],
  ['GET /api/jobs/synthetic-job/actions', { entries: [] }],
  ['GET /api/jobs/synthetic-job/manager', managerView],
  ['GET /api/jobs/synthetic-job/comparison', {
    available: false,
    reason: 'No earlier comparable batch',
  }],
])

export async function installApiFixture(page, overrides = new Map()) {
  const unexpected = []

  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const key = `${request.method()} ${url.pathname}`
    const response = overrides.has(key) ? overrides.get(key) : defaultResponses.get(key)

    if (response === undefined) {
      unexpected.push(`${key}${url.search}`)
      await route.fulfill({
        status: 599,
        contentType: 'application/json',
        body: JSON.stringify({ detail: `Unexpected test request: ${key}` }),
      })
      return
    }

    if (typeof response === 'function') {
      await response(route)
      return
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(response),
    })
  })

  return { unexpected }
}