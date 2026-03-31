import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import client from '../api/client'

export default function Login() {
  const { login, setup } = useAuth()
  const navigate = useNavigate()

  const [mode, setMode] = useState('login')   // 'login' | 'setup'
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  async function handleSubmit(e) {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      if (mode === 'setup') {
        await setup(username, password)
      } else {
        await login(username, password)
      }
      navigate('/')
    } catch (err) {
      const msg = err.response?.data?.detail
      if (mode === 'login' && err.response?.status === 409) {
        setError('Setup already complete — please log in.')
        setMode('login')
      } else {
        setError(typeof msg === 'string' ? msg : 'Something went wrong')
      }
    } finally {
      setLoading(false)
    }
  }

  async function checkFirstRun() {
    try {
      // If /auth/setup returns 409 there are already users → login mode
      // We probe the health endpoint; the actual check happens on form submit
      const res = await client.get('/health')
      return res.status === 200
    } catch {
      return false
    }
  }

  return (
    <div style={styles.page}>
      <div style={styles.card}>
        <div style={styles.header}>
          <span style={styles.logoMark}>$</span>
          <h1 style={styles.title}>Tally</h1>
        </div>
        <p style={styles.subtitle}>
          {mode === 'setup' ? 'Create your owner account' : 'Sign in to your household'}
        </p>

        <form onSubmit={handleSubmit} style={styles.form}>
          <label style={styles.label}>
            Username
            <input
              style={styles.input}
              type="text"
              value={username}
              onChange={(e) => setUsername(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </label>

          <label style={styles.label}>
            Password
            <input
              style={styles.input}
              type="password"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete={mode === 'setup' ? 'new-password' : 'current-password'}
              required
            />
          </label>

          {error && <p style={styles.error}>{error}</p>}

          <button style={styles.btn} type="submit" disabled={loading}>
            {loading ? 'Please wait…' : mode === 'setup' ? 'Create account' : 'Sign in'}
          </button>
        </form>

        <div style={styles.switchRow}>
          {mode === 'login' ? (
            <button style={styles.switchBtn} onClick={() => { setMode('setup'); setError('') }}>
              First time? Set up owner account
            </button>
          ) : (
            <button style={styles.switchBtn} onClick={() => { setMode('login'); setError('') }}>
              Already have an account? Sign in
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

const styles = {
  page: {
    minHeight: '100vh',
    background: 'var(--bg)',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 16,
  },
  card: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: '40px 36px',
    width: '100%',
    maxWidth: 400,
  },
  header: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginBottom: 6,
  },
  logoMark: {
    color: 'var(--green)',
    fontSize: 32,
    fontWeight: 700,
    lineHeight: 1,
  },
  title: {
    fontSize: 28,
    fontWeight: 700,
    color: 'var(--white)',
  },
  subtitle: {
    color: 'var(--muted)',
    fontSize: 14,
    marginBottom: 28,
  },
  form: {
    display: 'flex',
    flexDirection: 'column',
    gap: 18,
  },
  label: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    fontSize: 13,
    fontWeight: 500,
    color: 'var(--muted)',
  },
  input: {
    background: 'var(--bg-input)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    color: 'var(--white)',
    padding: '10px 14px',
    fontSize: 15,
    outline: 'none',
    transition: 'border-color 0.15s',
  },
  error: {
    color: 'var(--red)',
    fontSize: 13,
    marginTop: -6,
  },
  btn: {
    background: 'var(--green)',
    color: '#282A36',
    border: 'none',
    borderRadius: 'var(--radius)',
    padding: '12px',
    fontSize: 15,
    fontWeight: 700,
    marginTop: 4,
    transition: 'opacity 0.15s',
  },
  switchRow: {
    marginTop: 20,
    textAlign: 'center',
  },
  switchBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--cyan)',
    fontSize: 13,
    cursor: 'pointer',
  },
}
