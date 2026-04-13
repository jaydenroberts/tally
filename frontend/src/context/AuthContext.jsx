import React, { createContext, useContext, useState, useCallback } from 'react'
import client from '../api/client'

const AuthContext = createContext(null)

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('tally_user'))
    } catch {
      return null
    }
  })

  const login = useCallback(async (username, password) => {
    const { data } = await client.post('/auth/login', { username, password })
    localStorage.setItem('tally_token', data.access_token)
    localStorage.setItem('tally_user', JSON.stringify(data.user))
    setUser(data.user)
    return data.user
  }, [])

  const setup = useCallback(async (username, password) => {
    const { data } = await client.post('/auth/setup', {
      username,
      password,
      role_id: 1, // owner — setup endpoint overrides this anyway
    })
    localStorage.setItem('tally_token', data.access_token)
    localStorage.setItem('tally_user', JSON.stringify(data.user))
    setUser(data.user)
    return data.user
  }, [])

  const logout = useCallback(() => {
    localStorage.removeItem('tally_token')
    localStorage.removeItem('tally_user')
    setUser(null)
  }, [])

  // Fetch the latest user object from the server and sync it to state +
  // localStorage. Call this whenever stale persona/role data is a concern
  // (e.g. on Chat mount, or after a user is edited in Settings).
  const refreshUser = useCallback(async () => {
    try {
      const { data } = await client.get('/users/me')
      localStorage.setItem('tally_user', JSON.stringify(data))
      setUser(data)
    } catch {
      // Silently ignore — if the token is invalid the auth interceptor will
      // handle logout; we don't want a refresh failure to break the UI.
    }
  }, [])

  const isOwner = user?.role?.name === 'owner'

  return (
    <AuthContext.Provider value={{ user, login, setup, logout, isOwner, refreshUser }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
