import { createContext, useContext, useEffect, useState } from 'react'
import { api, getToken, setToken } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setTok] = useState(getToken())
  const [username, setUsername] = useState(null)
  const [sessionExpired, setSessionExpired] = useState(false)

  useEffect(() => {
    const onUnauthorized = () => {
      setTok(null)
      setUsername(null)
      setSessionExpired(true)
    }
    window.addEventListener('cotrace:unauthorized', onUnauthorized)
    return () => window.removeEventListener('cotrace:unauthorized', onUnauthorized)
  }, [])

  const login = async (u, p) => {
    const res = await api.login(u, p)
    setToken(res.token)
    setTok(res.token)
    setUsername(res.username)
    setSessionExpired(false)
  }

  const logout = () => {
    setToken(null)
    setTok(null)
    setUsername(null)
    setSessionExpired(false)
  }

  return (
    <AuthContext.Provider
      value={{ token, username, login, logout, isAuthed: !!token, sessionExpired }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
