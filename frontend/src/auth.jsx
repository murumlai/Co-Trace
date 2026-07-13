import { createContext, useContext, useState } from 'react'
import { api, getToken, setToken } from './api'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [token, setTok] = useState(getToken())
  const [username, setUsername] = useState(null)

  const login = async (u, p) => {
    const res = await api.login(u, p)
    setToken(res.token)
    setTok(res.token)
    setUsername(res.username)
  }

  const logout = () => {
    setToken(null)
    setTok(null)
    setUsername(null)
  }

  return (
    <AuthContext.Provider value={{ token, username, login, logout, isAuthed: !!token }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  return useContext(AuthContext)
}
