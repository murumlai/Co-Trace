import { expect, test } from '@playwright/test'
import { installApiFixture, managerView } from './apiFixture'

test('opens Home, reopens a batch, and navigates the real shell', async ({ page }) => {
  const pageErrors = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  const fixture = await installApiFixture(page)

  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'Upload test logs' })).toBeVisible()
  await expect(page.getByText('Sign in with GitHub')).toHaveCount(0)

  await page.getByRole('button', { name: 'Recent batches' }).click()
  await expect(page.getByText('Batches in the shared workspace')).toBeVisible()
  await expect(page.getByText('0 attempts')).toBeVisible()
  await page.getByRole('button', { name: /Synthetic batch/ }).click()
  await expect(page.getByRole('heading', { name: 'Engineer view' })).toBeVisible()

  await page.getByRole('button', { name: 'Manager', exact: true }).click()
  await expect(page.getByRole('heading', { name: 'Synthetic batch' })).toBeVisible()
  const downloadStarted = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export CSV' }).click()
  const download = await downloadStarted
  expect(download.suggestedFilename()).toMatch(/^co-trace_synthetic-job_all_.*\.csv$/)

  expect(fixture.unexpected).toEqual([])
  expect(pageErrors).toEqual([])
})

test('rejects requests that are absent from the fixture contract', async ({ page }) => {
  const fixture = await installApiFixture(page)
  await page.goto('/')

  const status = await page.evaluate(async () => {
    const response = await fetch('/api/not-in-the-fixture')
    return response.status
  })

  expect(status).toBe(599)
  expect(fixture.unexpected).toEqual(['GET /api/not-in-the-fixture'])
})

test('persists an acknowledged running job before polling completes', async ({ page }) => {
  let uploadCount = 0
  let statusCount = 0
  const fixture = await installApiFixture(page, new Map([
    ['POST /api/upload', async (route) => {
      uploadCount += 1
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ job_id: 'running-job' }) })
    }],
    ['GET /api/jobs/running-job/status', async (route) => {
      statusCount += 1
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(statusCount === 1 ? {
          status: 'running',
          progress: { stage: 'analysis', processed: 1, total: 2 },
          message: 'Analyzing',
        } : {
          status: 'done',
          progress: { stage: 'complete', processed: 2, total: 2 },
          message: 'Complete',
          warnings: [],
        }),
      })
    }],
  ]))
  await page.goto('/')

  await page.locator('input[type="file"]').nth(1).setInputFiles({
    name: 'ftrunnerlog01.txt',
    mimeType: 'text/plain',
    buffer: Buffer.from('fixture'),
  })
  await page.getByRole('button', { name: 'Process batch' }).click()
  await expect(page).toHaveURL(/job=running-job/)
  await page.reload()
  await expect.poll(() => statusCount).toBeGreaterThanOrEqual(2)

  expect(uploadCount).toBe(1)
  expect(fixture.unexpected).toEqual([])
})

test('reconstructs a large exact drill-down from its compact link', async ({ page }) => {
  const attemptIds = Array.from({ length: 1205 }, (_, index) => `attempt-${index}`)
  const fixture = await installApiFixture(page, new Map([
    ['GET /api/jobs/synthetic-job/manager', {
      pareto: [{
        signature: 'sig-exact',
        count: 1205,
        attempt_ids: attemptIds,
        unit_ids: ['SN-1'],
      }],
      stations: [],
      lots: [],
    }],
  ]))

  await page.goto('/?job=synthetic-job&tab=engineer&drill_signature=sig-exact')

  await expect(page.getByText(/1205 matching attempts/)).toBeVisible()
  const saved = await page.evaluate(() => sessionStorage.getItem('cotrace-workspace:shared-workspace'))
  expect(saved).not.toContain('attempt-1204')
  expect(fixture.unexpected).toEqual([])
})

test('Back returns from an Engineer drill-down to the prior Manager scope', async ({ page }) => {
  const scopedManager = {
    ...managerView,
    summary: {
      ...managerView.summary,
      total_runs: 1,
      failed_attempts: 1,
      unique_units: 1,
      failed: 1,
      fpy_total: 1,
      latest_yield_total: 1,
      additional_attempt_share: 0,
    },
    pareto: [{
      signature: 'sig-back',
      reason: 'Fixture failure',
      count: 1,
      total: 1,
      cum_count: 1,
      pct: 100,
      cum_pct: 100,
      attempt_ids: ['attempt-1'],
      unit_ids: ['SN-1'],
    }],
  }
  const fixture = await installApiFixture(page, new Map([
    ['GET /api/jobs/synthetic-job/manager', scopedManager],
  ]))
  await page.goto('/')
  await page.getByRole('button', { name: 'Recent batches' }).click()
  await page.getByRole('button', { name: /Synthetic batch/ }).click()
  await page.getByRole('button', { name: 'Manager', exact: true }).click()
  const metric = page.getByText('First observed pass rate', { exact: true }).first()
  const comparisonSummary = page.getByText('Qualified comparison', { exact: true })
  await expect(metric).toBeVisible()
  await expect(comparisonSummary).toBeVisible()
  expect((await metric.boundingBox()).y).toBeLessThan((await comparisonSummary.boundingBox()).y)
  await expect(page.getByLabel('Target metric')).toBeHidden()
  await comparisonSummary.click()
  await expect(page.getByLabel('Target metric')).toBeVisible()
  await page.getByRole('button', { name: 'Fixture failure' }).click()
  await expect(page.getByRole('heading', { name: 'Engineer view' })).toBeVisible()

  await page.goBack()

  await expect(page.getByRole('heading', { name: 'Synthetic batch' })).toBeVisible()
  await expect(page).toHaveURL(/tab=manager/)
  expect(fixture.unexpected).toEqual([])
})