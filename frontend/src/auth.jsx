import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { api } from './api'

const AuthContext = createContext(null)
const SHARED_USER = Object.freeze({ workspace_id: 'shared-workspace', username: 'shared-workspace', is_admin: false })

export function AuthProvider({ children }) {
  const [user, setUser] = useState(SHARED_USER)
  const [checking, setChecking] = useState(true)
  const [notice, setNotice] = useState('')
  const generation = useRef(0)

  useEffect(() => {
    let active = true
    const current = generation.current
    api.me({ authOptional: true })
      .then((me) => {
        if (!active || current !== generation.current) return
        setUser(me)
      })
      .catch(() => {
        if (!active || current !== generation.current) return
        setUser(SHARED_USER)
      })
      .finally(() => {
        if (active) setChecking(false)
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    const onUnauthorized = () => {
      generation.current += 1
      setUser(SHARED_USER)
      setNotice('Admin access is no longer available. Open Admin to sign in again; your workspace is unchanged.')
    }
    window.addEventListener('cotrace:unauthorized', onUnauthorized)
    return () => window.removeEventListener('cotrace:unauthorized', onUnauthorized)
  }, [])

  const adminLogin = async (username, password) => {
    const current = ++generation.current
    const res = await api.adminLogin({ username, password })
    if (current !== generation.current) return
    setUser(res.user)
    setNotice('')
    return res.user
  }

  const logout = async () => {
    generation.current += 1
    await api.logout()
    setUser(SHARED_USER)
    setNotice('')
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        workspaceId: SHARED_USER.workspace_id,
        adminLogin,
        logout,
        checking,
        isAuthed: true,
        isAdmin: !!user?.is_admin,
        notice,
        clearNotice: () => setNotice(''),
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
