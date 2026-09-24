import { createContext, useContext, useEffect, useRef, useState } from 'react'
import { api } from './api'

const AuthContext = createContext(null)
const SHARED_USER = Object.freeze({ workspace_id: 'shared-workspace', username: 'shared-workspace', is_admin: false })

export function AuthProvider({ children }) {
  const [user, setUser] = useState(SHARED_USER)
  const [checking, setChecking] = useState(true)
  const [notice, setNotice] = useState('')
  const generation = useRef(0)
  const userRef = useRef(SHARED_USER)
  const adminGrantedAt = useRef(Number.NEGATIVE_INFINITY)

  const updateUser = (nextUser) => {
    userRef.current = nextUser
    setUser(nextUser)
  }

  useEffect(() => {
    let active = true
    const current = generation.current
    api.me({ authOptional: true })
      .then((me) => {
        if (!active || current !== generation.current) return
        if (me?.is_admin) adminGrantedAt.current = performance.now()
        updateUser(me)
      })
      .catch(() => {
        if (!active || current !== generation.current) return
        updateUser(SHARED_USER)
      })
      .finally(() => {
        if (active) setChecking(false)
      })
    return () => {
      active = false
    }
  }, [])

  useEffect(() => {
    const onUnauthorized = (event) => {
      if (!userRef.current?.is_admin) return
      const requestStartedAt = event.detail?.startedAt
      if (Number.isFinite(requestStartedAt) && requestStartedAt < adminGrantedAt.current) return
      generation.current += 1
      updateUser(SHARED_USER)
      setNotice('Admin access is no longer available. Open Admin to sign in again; your workspace is unchanged.')
    }
    window.addEventListener('cotrace:unauthorized', onUnauthorized)
    return () => window.removeEventListener('cotrace:unauthorized', onUnauthorized)
  }, [])

  const adminLogin = async (username, password) => {
    const current = ++generation.current
    const res = await api.adminLogin({ username, password })
    if (current !== generation.current) return
    adminGrantedAt.current = performance.now()
    updateUser(res.user)
    setNotice('')
    return res.user
  }

  const logout = async () => {
    const current = ++generation.current
    await api.logout()
    if (current !== generation.current) return
    updateUser(SHARED_USER)
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
