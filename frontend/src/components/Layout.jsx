import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const navItems = [
  { to: '/',             label: 'Dashboard' },
  { to: '/accounts',     label: 'Accounts'  },
  { to: '/transactions', label: 'Transactions' },
  { to: '/budgets',      label: 'Budgets'   },
  { to: '/savings',      label: 'Savings'   },
  { to: '/debt',         label: 'Debt'      },
]

export default function Layout({ children }) {
  const { user, logout, isOwner } = useAuth()
  const navigate = useNavigate()

  function handleLogout() {
    logout()
    navigate('/login')
  }

  return (
    <div style={styles.shell}>
      <aside style={styles.sidebar} className="app-sidebar">
        <div style={styles.logo}>
          <span style={styles.logoMark}>$</span>
          <span style={styles.logoText}>Tally</span>
        </div>

        <nav style={styles.nav}>
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              style={({ isActive }) => ({
                ...styles.navLink,
                ...(isActive ? styles.navLinkActive : {}),
              })}
            >
              {label}
            </NavLink>
          ))}
          {isOwner && (
            <NavLink
              to="/settings"
              style={({ isActive }) => ({
                ...styles.navLink,
                ...(isActive ? styles.navLinkActive : {}),
              })}
            >
              Settings
            </NavLink>
          )}
        </nav>

        <div style={styles.userBar}>
          <div style={styles.userInfo}>
            <span style={styles.username}>{user?.username}</span>
            <span style={styles.roleBadge}>{user?.role?.display_name}</span>
          </div>
          <button style={styles.logoutBtn} onClick={handleLogout}>
            Sign out
          </button>
        </div>
      </aside>

      <main style={styles.main} className="app-main">
        {children}
      </main>
    </div>
  )
}

const styles = {
  shell: {
    display: 'flex',
    height: '100vh',
    overflow: 'hidden',
  },
  sidebar: {
    width: 220,
    minWidth: 220,
    background: 'var(--bg-card)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    padding: '24px 0',
  },
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    padding: '0 20px 24px',
    borderBottom: '1px solid var(--border)',
    marginBottom: 16,
  },
  logoMark: {
    color: 'var(--green)',
    fontSize: 24,
    fontWeight: 700,
  },
  logoText: {
    color: 'var(--white)',
    fontSize: 20,
    fontWeight: 700,
    letterSpacing: '-0.5px',
  },
  nav: {
    display: 'flex',
    flexDirection: 'column',
    gap: 2,
    padding: '0 10px',
    flex: 1,
  },
  navLink: {
    display: 'block',
    padding: '9px 12px',
    borderRadius: 'var(--radius)',
    color: 'var(--muted)',
    fontSize: 14,
    fontWeight: 500,
    transition: 'color 0.15s, background 0.15s',
    textDecoration: 'none',
  },
  navLinkActive: {
    color: 'var(--white)',
    background: 'var(--bg)',
  },
  userBar: {
    padding: '16px 20px 0',
    borderTop: '1px solid var(--border)',
    marginTop: 16,
  },
  userInfo: {
    display: 'flex',
    flexDirection: 'column',
    marginBottom: 10,
  },
  username: {
    fontWeight: 600,
    fontSize: 14,
    color: 'var(--white)',
  },
  roleBadge: {
    fontSize: 11,
    color: 'var(--cyan)',
    marginTop: 2,
  },
  logoutBtn: {
    background: 'none',
    border: '1px solid var(--border)',
    color: 'var(--muted)',
    padding: '6px 12px',
    borderRadius: 'var(--radius)',
    fontSize: 13,
    width: '100%',
    transition: 'color 0.15s, border-color 0.15s',
  },
  main: {
    flex: 1,
    overflow: 'auto',
    padding: 32,
  },
}
