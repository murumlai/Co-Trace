// @vitest-environment jsdom

import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, test, vi } from 'vitest'
import App from './App'
import { saveWorkspaceState } from './workspaceState'

const apiMocks = vi.hoisted(() => ({
  me: vi.fn(), adminLogin: vi.fn(), logout: vi.fn(), jobs: vi.fn(),
}))

vi.mock('./api', () => ({ api: apiMocks }))
vi.mock('./logger', () => ({ log: vi.fn(), debugLog: vi.fn() }))

const sharedUser = { workspace_id: 'shared-workspace', username: 'shared-workspace', is_admin: false }
const adminUser = { ...sharedUser, username: 'admin', is_admin: true }

async function openAdmin() {
  const button = screen.getByRole('button', { name: 'Admin', exact: true })
  await waitFor(() => expect(button.disabled).toBe(false))
  fireEvent.click(button)
  expect(screen.getByRole('dialog', { name: 'Admin mode' })).toBeTruthy()
  fireEvent.change(screen.getByLabelText('Password'), { target: { value: 'test-password' } })
  fireEvent.click(screen.getByRole('button', { name: 'Enter Admin' }))
}

describe('Shared workspace shell', () => {
  beforeEach(() => {
    localStorage.clear()
    sessionStorage.clear()
    window.history.replaceState(null, '', '/')
    vi.resetAllMocks()
    apiMocks.me.mockResolvedValue(sharedUser)
    apiMocks.jobs.mockResolvedValue({ items: [], next_cursor: null })
    apiMocks.adminLogin.mockResolvedValue({ user: adminUser })
    apiMocks.logout.mockResolvedValue({ ok: true })
    HTMLDialogElement.prototype.showModal = function () { this.setAttribute('open', '') }
    HTMLDialogElement.prototype.close = function () { this.removeAttribute('open') }
  })

  afterEach(cleanup)

  test('opens Home without waiting for a session or showing a login screen', () => {
    apiMocks.me.mockReturnValue(new Promise(() => {}))
    render(<App />)
    expect(screen.getByRole('heading', { name: 'Upload test logs' })).toBeTruthy()
    expect(screen.queryByText('Sign in with GitHub')).toBeNull()
    expect(screen.queryByText('Checking session')).toBeNull()
  })

  test('a bare URL opens Home instead of the previous saved tab', async () => {
    saveWorkspaceState(sessionStorage, 'shared-workspace', { tab: 'engineer', jobId: 'old-job' })
    render(<App />)
    await waitFor(() => expect(apiMocks.jobs).toHaveBeenCalled())
    expect(screen.getByRole('heading', { name: 'Upload test logs' })).toBeTruthy()
    expect(window.location.search).not.toContain('old-job')
  })

  test('Admin entry and exit retain navigation and never persist the password', async () => {
    render(<App />)
    await waitFor(() => expect(apiMocks.jobs).toHaveBeenCalled())
    fireEvent.click(screen.getByRole('button', { name: 'About', exact: true }))
    await openAdmin()
    await screen.findByRole('button', { name: 'Exit Admin' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(screen.getByRole('button', { name: 'About', exact: true }).getAttribute('aria-current')).toBe('page')
    fireEvent.click(screen.getByRole('button', { name: 'Exit Admin' }))
    await screen.findByRole('button', { name: 'Admin', exact: true })
    expect(screen.getByRole('button', { name: 'About', exact: true }).getAttribute('aria-current')).toBe('page')
    expect(apiMocks.adminLogin).toHaveBeenCalledWith({ username: 'admin', password: 'test-password' })
    expect(JSON.stringify({ ...localStorage, ...sessionStorage })).not.toContain('test-password')
    expect(apiMocks.jobs).toHaveBeenCalledTimes(1)
  })

  test('failed Admin credentials leave regular mode and clear the password', async () => {
    apiMocks.adminLogin.mockRejectedValue(Object.assign(new Error('Invalid credentials'), { status: 401 }))
    render(<App />)
    await openAdmin()
    await screen.findByRole('alert')
    expect(screen.getByLabelText('Password').value).toBe('')
    expect(screen.queryByRole('button', { name: 'Exit Admin' })).toBeNull()
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(screen.queryByRole('dialog')).toBeNull()
  })

  test('failed logout reports the failure without claiming Admin ended', async () => {
    apiMocks.me.mockResolvedValue(adminUser)
    apiMocks.logout.mockRejectedValue(new Error('Offline'))
    render(<App />)
    fireEvent.click(await screen.findByRole('button', { name: 'Exit Admin' }))
    await screen.findByText(/Could not exit Admin mode/)
    expect(screen.getByRole('button', { name: 'Exit Admin' })).toBeTruthy()
  })

  test('expired Admin privileges leave the shared tab available', async () => {
    apiMocks.me.mockResolvedValue(adminUser)
    render(<App />)
    await screen.findByRole('button', { name: 'Exit Admin' })
    fireEvent.click(screen.getByRole('button', { name: 'About', exact: true }))
    act(() => window.dispatchEvent(new Event('cotrace:unauthorized')))
    expect(screen.getByRole('button', { name: 'Admin', exact: true })).toBeTruthy()
    expect(screen.getByRole('button', { name: 'About', exact: true }).getAttribute('aria-current')).toBe('page')
    expect(screen.queryByText('Sign in with GitHub')).toBeNull()
    expect(screen.getByText(/Admin access is no longer available/)).toBeTruthy()
  })

  test('Escape in Admin dialog preserves the mobile menu and returns focus', async () => {
    render(<App />)
    await waitFor(() => expect(apiMocks.jobs).toHaveBeenCalled())
    const toggle = screen.getByRole('button', { name: 'Toggle menu' })
    fireEvent.click(toggle)
    const trigger = screen.getAllByRole('button', { name: 'Admin', exact: true }).at(-1)
    trigger.focus()
    fireEvent.click(trigger)
    const dialog = screen.getByRole('dialog')
    fireEvent.keyDown(dialog, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
    expect(toggle.getAttribute('aria-expanded')).toBe('true')
    expect(document.activeElement).toBe(trigger)
  })
})