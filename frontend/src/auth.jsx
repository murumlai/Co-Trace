import { createContext, useContext, useEffect, useState } from 'react'
import { api } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null)
  const [checking, setChecking] = useState(true)
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    let active = true
    api.me({ authOptional: true })
      .then((me) => {
        if (!active) return
        setUser(me)
        setSessionExpired(false)
      })
      .catch(() => {
        if (!active) return
        setUser(null)
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
      setUser(null)
      setSessionExpired(true)
    }
    window.addEventListener('cotrace:unauthorized', onUnauthorized)
    return () => window.removeEventListener('cotrace:unauthorized', onUnauthorized)
  }, [])

  const login = () => {
    window.location.assign('/api/auth/github')
  }

  const adminLogin = async (username, password) => {
    const res = await api.adminLogin({ username, password })
    setUser(res.user)
    setSessionExpired(false)
    return res.user
  }

  const logout = async () => {
    try {
      await api.logout()
    } finally {
      setUser(null)
      setSessionExpired(false)
    }
  }

  const clearSessionNotice = () => {
    setSessionExpired(false)
  }

  return (
    <AuthContext.Provider
      value={{
        user,
        username: user?.username || user?.login || null,
        login,
        adminLogin,
        logout,
        checking,
        isAuthed: !!user,
        isAdmin: !!user?.is_admin,
        sessionExpired,
        clearSessionNotice,
      }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
