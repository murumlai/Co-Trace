import { expect, test } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'
import { installApiFixture } from './apiFixture'

const evidenceDirectory = path.resolve('test-results/evidence')
mkdirSync(evidenceDirectory, { recursive: true })

const viewports = [
  ['desktop', { width: 1440, height: 900 }],
  ['compact-desktop', { width: 1280, height: 720 }],
  ['tablet', { width: 768, height: 1024 }],
  ['mobile', { width: 390, height: 844 }],
]

for (const [name, viewport] of viewports) {
  for (const theme of ['light', 'dark']) {
    test(`${name} ${theme} shell has no page-wide overflow`, async ({ page }, testInfo) => {
      await installApiFixture(page)
      await page.setViewportSize(viewport)
      await page.emulateMedia({ reducedMotion: 'reduce' })
      if (theme === 'dark') {
        await page.addInitScript(() => localStorage.setItem('cotrace-theme', 'dark'))
      }
      await page.goto('/')

      await expect(page.getByRole('heading', { name: 'Upload test logs' })).toBeVisible()
      expect(await page.evaluate(() => document.documentElement.dataset.theme)).toBe(theme)
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({
        path: path.join(evidenceDirectory, `${name}-${theme}.png`),
        fullPage: true,
      })
    })
  }
}

test('core workflow remains usable at 200 percent browser scale', async ({ page }, testInfo) => {
  await installApiFixture(page)
  await page.setViewportSize({ width: 1280, height: 720 })
  await page.goto('/')
  const session = await page.context().newCDPSession(page)
  await session.send('Emulation.setPageScaleFactor', { pageScaleFactor: 2 })

  await expect(page.getByRole('heading', { name: 'Upload test logs' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Select folder' })).toBeVisible()
  await page.screenshot({ path: path.join(evidenceDirectory, 'zoom-200.png'), fullPage: true })
})

test('Manager print keeps report definitions and secondary content', async ({ page }, testInfo) => {
  await installApiFixture(page)
  await page.goto('/?job=synthetic-job&tab=manager')
  await expect(page.getByRole('heading', { name: 'Synthetic batch' })).toBeVisible()
  await page.emulateMedia({ media: 'print' })
  await page.evaluate(() => window.dispatchEvent(new Event('beforeprint')))

  await expect(page.getByText('Measures describe the selected attempts', { exact: false })).toBeVisible()
  await expect(page.getByText('Qualified comparison', { exact: true })).toBeHidden()
  await expect(page.locator('.manager-print-details').first().locator('p', { hasText: 'No earlier comparable batch' })).toBeVisible()
  await page.screenshot({ path: path.join(evidenceDirectory, 'manager-print.png'), fullPage: true })
  const pdf = await page.pdf({
    path: path.join(evidenceDirectory, 'manager-report.pdf'),
    format: 'A4',
    printBackground: true,
  })
  expect(pdf.byteLength).toBeGreaterThan(10_000)
})

test('keyboard navigation exposes visible focus and disclosure state', async ({ page }) => {
  await installApiFixture(page)
  await page.goto('/?job=synthetic-job&tab=manager')
  const managerTab = page.getByRole('button', { name: 'Manager', exact: true })
  await managerTab.focus()
  await expect(managerTab).toBeFocused()
  const focusStyle = await managerTab.evaluate((element) => getComputedStyle(element).boxShadow)
  expect(focusStyle).not.toBe('none')

  const comparison = page.locator('summary').filter({ hasText: 'Qualified comparison' })
  await comparison.focus()
  await page.keyboard.press('Enter')
  await expect(page.getByLabel('Target metric')).toBeVisible()
})