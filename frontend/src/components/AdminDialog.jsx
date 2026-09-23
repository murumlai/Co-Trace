import { useEffect, useRef, useState } from 'react'
import { useAuth } from '../auth'
import { Button, Input } from './ui'

export default function AdminDialog({ onClose }) {
  const { adminLogin } = useAuth()
  const dialog = useRef(null)
  const [username, setUsername] = useState('admin')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    const element = dialog.current
    const previous = document.activeElement
    element.showModal()
    element.querySelector('input[type="password"]')?.focus()
    return () => {
      element.close()
      previous?.focus()
    }
  }, [])

  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await adminLogin(username, password)
      onClose()
    } catch (failure) {
      setPassword('')
      setError(failure.status === 503
        ? 'Admin mode is not configured. Ask the maintainer to set ADMIN_PASSWORD on the backend.'
        : 'Could not enter Admin mode. Check your credentials and connection, then try again.')
    } finally {
      setBusy(false)
    }
  }

  const dismiss = (event) => {
    event.preventDefault()
    event.stopPropagation()
    if (!busy) onClose()
  }

  return (
    <dialog ref={dialog} aria-labelledby="admin-title" onCancel={dismiss} onKeyDown={(event) => { if (event.key === 'Escape') dismiss(event) }} className="w-[calc(100%-2rem)] max-w-sm rounded-lg border border-border bg-surface p-6 text-ink shadow-lg backdrop:bg-black/40">
      <form onSubmit={submit} className="space-y-4">
        <h2 id="admin-title" className="font-display text-lg font-bold">Admin mode</h2>
        <label className="block text-sm">
          Username
          <Input value={username} onChange={(event) => setUsername(event.target.value)} autoComplete="username" required disabled={busy} className="mt-1" />
        </label>
        <label className="block text-sm">
          Password
          <Input type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" required disabled={busy} className="mt-1" />
        </label>
        {error && <p role="alert" className="text-sm text-danger">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button type="button" variant="ghost" disabled={busy} onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" disabled={busy}>{busy ? 'Checking...' : 'Enter Admin'}</Button>
        </div>
      </form>
    </dialog>
  )
}