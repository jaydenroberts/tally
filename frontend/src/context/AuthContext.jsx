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

  const isOwner = user?.role?.name === 'owner'

  return (
    <AuthContext.Provider value={{ user, login, setup, logout, isOwner }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
