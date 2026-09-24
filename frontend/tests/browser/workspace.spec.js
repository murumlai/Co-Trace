import { expect, test } from '@playwright/test'
import { installApiFixture } from './apiFixture'

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