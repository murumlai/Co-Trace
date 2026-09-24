import { expect, test } from '@playwright/test'
import { mkdirSync, writeFileSync } from 'node:fs'
import path from 'node:path'
import { installApiFixture, managerView } from './apiFixture'

const UNIT_COUNT = 1200
const RETRY_COUNT = 100
const ATTEMPT_COUNT = UNIT_COUNT + RETRY_COUNT

function largeUnits() {
  return Array.from({ length: UNIT_COUNT }, (_, index) => {
    const unitId = `attempt-${String(index).padStart(4, '0')}`
    const serial = `SERIAL-${String(index).padStart(5, '0')}-LONG-IDENTIFIER`
    const final = {
      unit_id: unitId,
      serial_number: serial,
      product_code: `P${(index % 8) + 1}`,
      lot_id: `LOT-${index % 40}`,
      station_id: `ST-${index % 20}`,
      host: `TESTER-${index % 10}`,
      result: 'PASS',
      duration_s: 10 + (index % 30),
      start_time: `2026-09-${String((index % 28) + 1).padStart(2, '0')}T08:00:00`,
    }
    const failing = index < 100
    const recovered = index >= 100 && index < 100 + RETRY_COUNT
    const failure = failing || recovered ? {
      ...final,
      unit_id: `${unitId}-failure`,
      result: 'FAIL',
      error_code: `ERROR_${index % 100}`,
      error_message: `Long representative failure message ${index} with repeated diagnostic context`,
      failing_step: `STEP_${index % 50}`,
      root_cause: 'Synthetic fixture contact requires verification before replacement.',
      suggested_solution: 'Inspect the fixture contact and compare the captured voltage trace.',
      redacted_snippet: Array.from({ length: 80 }, (_, line) => `${line + 1} INFO synthetic evidence line ${index}`).join('\n'),
      analysis_source: 'llm',
      analysis_context_source: 'debug_excerpt',
      evidence_consumed: true,
    } : null
    return {
      serial_number: serial,
      unit_id: unitId,
      classification: failing ? 'fail' : recovered ? 'retry_pass' : 'first_pass',
      result: failing ? 'FAIL' : 'PASS',
      attempt_count: recovered ? 2 : 1,
      failure_count: failure ? 1 : 0,
      final: failing ? failure : final,
      failures: failure ? [failure] : [],
    }
  })
}

function largeManagerView() {
  const attemptIds = Array.from({ length: ATTEMPT_COUNT }, (_, index) => `attempt-${String(index).padStart(4, '0')}`)
  return {
    ...managerView,
    batch: {
      ...managerView.batch,
      display_name: 'Synthetic 1300-attempt batch',
      included_run_count: ATTEMPT_COUNT,
      discovered_run_count: ATTEMPT_COUNT,
      product_codes: Array.from({ length: 8 }, (_, index) => `P${index + 1}`),
    },
    summary: {
      ...managerView.summary,
      total_runs: ATTEMPT_COUNT,
      failed_attempts: 200,
      unique_units: UNIT_COUNT,
      passed: 1100,
      failed: 100,
      fpy: 83.33,
      fpy_pass: 1000,
      fpy_total: UNIT_COUNT,
      retests: RETRY_COUNT,
      latest_yield: 91.67,
      latest_yield_pass: 1100,
      latest_yield_total: UNIT_COUNT,
      recovered_after_retry: RETRY_COUNT,
      additional_attempt_share: 7.69,
    },
    scope: {
      ...managerView.scope,
      selected_attempt_count: ATTEMPT_COUNT,
      attempt_ids: attemptIds,
      unit_ids: Array.from({ length: UNIT_COUNT }, (_, index) => `SERIAL-${String(index).padStart(5, '0')}-LONG-IDENTIFIER`),
    },
    trend: Array.from({ length: 28 }, (_, index) => ({
      date: `2026-09-${String(index + 1).padStart(2, '0')}`,
      pass: 42,
      fail: 0,
      yield: 100,
    })),
    stations: Array.from({ length: 20 }, (_, index) => ({
      station: `TESTER-${index % 10} / ST-${index}`,
      station_id: `ST-${index}`,
      host: `TESTER-${index % 10}`,
      pass: 60,
      fail: 0,
      total: 60,
      yield: 100,
      attempt_ids: attemptIds.slice(index * 60, (index + 1) * 60),
      unit_ids: [],
    })),
    lots: Array.from({ length: 40 }, (_, index) => ({
      lot: `LOT-${index}`,
      pass: 30,
      fail: 0,
      total: 30,
      yield: 100,
      attempt_ids: attemptIds.slice(index * 30, (index + 1) * 30),
      unit_ids: [],
    })),
    pareto: Array.from({ length: 10 }, (_, index) => ({
      signature: `signature-${index}`,
      reason: `Synthetic failure family ${index}`,
      count: 20,
      total: 200,
      cum_count: (index + 1) * 20,
      pct: 10,
      cum_pct: (index + 1) * 10,
      attempt_ids: attemptIds.slice(index * 20, (index + 1) * 20),
      unit_ids: [],
    })),
  }
}

test('records representative large-batch behavior', async ({ page }, testInfo) => {
  const units = largeUnits()
  const manager = largeManagerView()
  const fixture = await installApiFixture(page, new Map([
    ['GET /api/jobs/synthetic-job/units', { units, run_count: ATTEMPT_COUNT }],
    ['GET /api/jobs/synthetic-job/clusters', {
      clusters: Array.from({ length: 100 }, (_, index) => ({
        signature: `signature-${index}`,
        count: 2,
        error_code: `ERROR_${index}`,
        error_message: `Representative failure family ${index}`,
        affected_serials: [`SERIAL-${index}`],
      })),
    }],
    ['GET /api/jobs/synthetic-job/manager', manager],
  ]))
  const runs = []
  let engineerRows = 0
  let engineerDomNodes = 0
  let managerDomNodes = 0
  for (let run = 1; run <= 3; run += 1) {
    const started = Date.now()
    await page.goto('/?job=synthetic-job&tab=engineer')
    await expect(page.getByRole('heading', { name: 'Engineer view' })).toBeVisible()
    await expect(page.getByText(`of ${UNIT_COUNT} units`, { exact: false }).first()).toBeVisible()
    const engineerReadyMs = Date.now() - started
    engineerRows = await page.locator('tbody > tr').count()
    engineerDomNodes = await page.locator('*').count()

    const managerStarted = Date.now()
    await page.getByRole('button', { name: 'Manager', exact: true }).click()
    await expect(page.getByRole('heading', { name: 'Synthetic 1300-attempt batch' })).toBeVisible()
    const managerReadyMs = Date.now() - managerStarted
    managerDomNodes = await page.locator('*').count()

    const reportStarted = Date.now()
    const downloadStarted = page.waitForEvent('download')
    await page.getByRole('button', { name: 'Export CSV' }).click()
    await downloadStarted
    runs.push({
      run,
      engineerReadyMs,
      managerReadyMs,
      reportGenerationMs: Date.now() - reportStarted,
    })
  }
  const usedHeapBytes = await page.evaluate(() => performance.memory?.usedJSHeapSize ?? null)

  const measurements = {
    capturedAt: new Date().toISOString(),
    browser: testInfo.project.name,
    viewport: page.viewportSize(),
    units: UNIT_COUNT,
    attempts: ATTEMPT_COUNT,
    managerPayloadBytes: Buffer.byteLength(JSON.stringify(manager)),
    runs,
    engineerRows,
    engineerDomNodes,
    managerDomNodes,
    usedHeapBytes,
  }
  const evidenceDirectory = path.resolve('test-results/evidence')
  mkdirSync(evidenceDirectory, { recursive: true })
  writeFileSync(
    path.join(evidenceDirectory, 'large-batch-measurements.json'),
    JSON.stringify(measurements, null, 2),
  )
  await testInfo.attach('large-batch-measurements.json', {
    body: Buffer.from(JSON.stringify(measurements, null, 2)),
    contentType: 'application/json',
  })
  console.log(`Large-batch measurements: ${JSON.stringify(measurements)}`)

  expect(engineerRows).toBeLessThanOrEqual(75)
  expect(fixture.unexpected).toEqual([])
})