import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Dracula purple — matches Chat.jsx accent
const PURPLE = '#BD93F9'

const navItems = [
  { to: '/',             label: 'Dashboard' },
  { to: '/accounts',     label: 'Accounts'  },
  { to: '/transactions', label: 'Transactions' },
  { to: '/recurring',    label: 'Recurring' },
  { to: '/budgets',      label: 'Budgets'   },
  { to: '/savings',      label: 'Savings'   },
  { to: '/debt',         label: 'Debt'      },
]

export default function Layout({ children }) {
  const { user, logout, isOwner } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  function handleLogout() {
    logout()
    navigate('/login')
  }

  // Shared nav link style factory — used in both desktop sidebar and mobile drawer
  function navLinkStyle({ isActive }) {
    return {
      ...styles.navLink,
      ...(isActive ? styles.navLinkActive : {}),
    }
  }

  // Closes the drawer when a nav link is clicked on mobile
  function handleNavClick() {
    setMenuOpen(false)
  }

  // The sidebar content is shared between desktop (always visible) and mobile (drawer)
  function SidebarContent() {
    return (
      <>
        <div style={styles.logo}>
          <img src="/android-chrome-512x512.png" alt="" style={styles.logoMark} />
          <span style={styles.logoText}>Tally</span>
        </div>

        <nav style={styles.nav}>
          {navItems.map(({ to, label }) => (
            <NavLink
              key={to}
              to={to}
              end={to === '/'}
              style={navLinkStyle}
              onClick={handleNavClick}
            >
              {label}
            </NavLink>
          ))}

          {/* Chat — purple accent to signal AI feature */}
          <NavLink
            to="/chat"
            style={({ isActive }) => ({
              ...styles.navLink,
              color: isActive ? PURPLE : 'var(--muted)',
              background: isActive ? `${PURPLE}18` : 'transparent',
            })}
            onClick={handleNavClick}
          >
            Chat
          </NavLink>

          {isOwner && (
            <NavLink
              to="/imports"
              style={navLinkStyle}
              onClick={handleNavClick}
            >
              Import History
            </NavLink>
          )}
          {isOwner && (
            <NavLink
              to="/settings"
              style={navLinkStyle}
              onClick={handleNavClick}
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
      </>
    )
  }

  return (
    <div style={styles.shell}>
      {/*
        Inject a single <style> block to handle the media query breakpoint.
        This avoids any new CSS file or package dependency.
        - .app-sidebar is hidden on mobile; shown on desktop.
        - .app-topbar is shown on mobile; hidden on desktop.
        - .app-main padding is reduced on mobile.
      */}
      <style>{`
        @media (max-width: 768px) {
          .app-sidebar  { display: none !important; }
          .app-topbar   { display: flex !important; }
          /* Reduce side padding and push content below the fixed 56px top bar */
          .app-main     { padding: 72px 16px 16px !important; }
        }
        @media (min-width: 769px) {
          .app-topbar              { display: none !important; }
          .app-drawer-backdrop     { display: none !important; }
          .app-drawer              { display: none !important; }
        }
      `}</style>

      {/* ── Desktop sidebar (hidden on mobile via media query above) ── */}
      <aside style={styles.sidebar} className="app-sidebar">
        <SidebarContent />
      </aside>

      {/* ── Mobile top bar (hidden on desktop via media query above) ── */}
      <div style={styles.topBar} className="app-topbar">
        <div style={styles.topBarLogo}>
          <img src="/android-chrome-512x512.png" alt="" style={styles.logoMark} />
          <span style={styles.logoText}>Tally</span>
        </div>
        <button
          style={styles.burgerBtn}
          onClick={() => setMenuOpen(prev => !prev)}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
        >
          {menuOpen ? '✕' : '☰'}
        </button>
      </div>

      {/* ── Mobile drawer backdrop (closes drawer on click) ── */}
      {menuOpen && (
        <div
          style={styles.backdrop}
          className="app-drawer-backdrop"
          onClick={() => setMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      {/* ── Mobile drawer (slides in from left when menuOpen) ── */}
      <aside
        style={{
          ...styles.drawer,
          transform: menuOpen ? 'translateX(0)' : 'translateX(-100%)',
        }}
        className="app-drawer"
        aria-hidden={!menuOpen}
      >
        <SidebarContent />
      </aside>

      {/* ── Main content area ── */}
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

  // ── Desktop sidebar ──────────────────────────────────────────────────────────
  sidebar: {
    width: 220,
    minWidth: 220,
    background: 'var(--bg-card)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    padding: '24px 0',
  },

  // ── Mobile top bar ───────────────────────────────────────────────────────────
  topBar: {
    // Always present in the DOM; media query shows/hides it.
    // Default display:none is overridden to flex by the media query on mobile.
    display: 'none',
    alignItems: 'center',
    justifyContent: 'space-between',
    position: 'fixed',
    top: 0,
    left: 0,
    right: 0,
    height: 56,
    padding: '0 16px',
    background: 'var(--bg-card)',
    borderBottom: '1px solid var(--border)',
    zIndex: 200,
  },
  topBarLogo: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  burgerBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--white)',
    fontSize: 22,
    cursor: 'pointer',
    padding: '4px 8px',
    lineHeight: 1,
  },

  // ── Mobile drawer backdrop ───────────────────────────────────────────────────
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.55)',
    zIndex: 300,
  },

  // ── Mobile drawer ────────────────────────────────────────────────────────────
  drawer: {
    position: 'fixed',
    top: 0,
    left: 0,
    bottom: 0,
    width: 260,
    background: 'var(--bg-card)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    padding: '24px 0',
    zIndex: 400,
    transition: 'transform 0.25s ease',
    // Default hidden state; open state applied inline via transform above
    transform: 'translateX(-100%)',
  },

  // ── Shared sidebar / drawer internals ────────────────────────────────────────
  logo: {
    display: 'flex',
    alignItems: 'center',
    gap: 12,
    padding: '0 20px 24px',
    borderBottom: '1px solid var(--border)',
    marginBottom: 16,
  },
  logoMark: {
    width: 83,
    height: 83,
    objectFit: 'contain',
    display: 'block',
    flexShrink: 0,
  },
  logoText: {
    color: 'var(--white)',
    fontSize: 28,
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

  // ── Main content ─────────────────────────────────────────────────────────────
  main: {
    flex: 1,
    overflow: 'auto',
    padding: 32,
    // On mobile the top bar is 56px fixed; push content down to avoid overlap.
    // The media query class override handles the padding reduction,
    // but paddingTop must account for the fixed topbar on mobile.
    // This is handled via the injected <style> block below the shell.
  },
}
