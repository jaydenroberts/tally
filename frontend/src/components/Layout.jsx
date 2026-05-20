import { useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Icon from './Icon'

const mainNav = [
  { to: '/',             label: 'Dashboard',    icon: 'dashboard' },
  { to: '/accounts',     label: 'Accounts',     icon: 'wallet' },
  { to: '/transactions', label: 'Transactions', icon: 'list' },
  { to: '/recurring',    label: 'Recurring',    icon: 'repeat' },
  { to: '/budgets',      label: 'Budgets',      icon: 'target' },
  { to: '/savings',      label: 'Savings',      icon: 'piggy' },
  { to: '/debt',         label: 'Debt',         icon: 'coins' },
]

export default function Layout({ children }) {
  const { user, logout, isOwner } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)

  function handleLogout() {
    logout()
    navigate('/login')
  }

  function handleNavClick() {
    setMenuOpen(false)
  }

  function NavItem({ to, label, icon, end }) {
    return (
      <NavLink
        to={to}
        end={end}
        onClick={handleNavClick}
        style={({ isActive }) => ({
          ...layoutStyles.navLink,
          ...(isActive ? layoutStyles.navLinkActive : {}),
          position: 'relative',
        })}
      >
        {({ isActive }) => (
          <>
            {isActive && <span style={layoutStyles.navLinkRail}/>}
            <Icon name={icon} size={17} stroke={isActive ? 2 : 1.6}/>
            <span style={{ flex: 1 }}>{label}</span>
          </>
        )}
      </NavLink>
    )
  }

  function SectionLabel({ children }) {
    return <div style={layoutStyles.sectionLabel}>{children}</div>
  }

  function SidebarContent() {
    const initial = (user?.username || '?').charAt(0).toUpperCase()
    return (
      <>
        <div style={layoutStyles.brand}>
          <div style={layoutStyles.brandMark}>T</div>
          <div style={layoutStyles.brandText}>
            <span style={layoutStyles.brandName}>Tally</span>
            <span style={layoutStyles.brandSub}>Household</span>
          </div>
        </div>

        <SectionLabel>Main</SectionLabel>
        <nav style={layoutStyles.nav}>
          {mainNav.map(item => (
            <NavItem key={item.to} {...item} end={item.to === '/'}/>
          ))}
        </nav>

        <SectionLabel>Tools</SectionLabel>
        <nav style={layoutStyles.nav}>
          <NavItem to="/chat" label="AI Coach" icon="chat"/>
          {isOwner && <NavItem to="/imports" label="Import history" icon="upload"/>}
          {isOwner && <NavItem to="/settings" label="Settings" icon="settings"/>}
        </nav>

        <div style={{ flex: 1 }}/>

        <div style={layoutStyles.userCard}>
          <div style={layoutStyles.userAvatar}>{initial}</div>
          <div style={layoutStyles.userInfo}>
            <span style={layoutStyles.username}>{user?.username}</span>
            <span style={layoutStyles.userRole}>{user?.role?.display_name}</span>
          </div>
          <button
            style={layoutStyles.logoutBtn}
            onClick={handleLogout}
            aria-label="Sign out"
          >
            <Icon name="logout" size={15}/>
          </button>
        </div>
      </>
    )
  }

  return (
    <div style={layoutStyles.shell} data-app-shell>
      <style>{`
        @media (max-width: 768px) {
          .app-sidebar  { display: none !important; }
          .app-topbar   { display: flex !important; }
          .app-main     { padding: 72px 16px 16px !important; overflow-x: hidden !important; }
        }
        @media (min-width: 769px) {
          .app-topbar              { display: none !important; }
          .app-drawer-backdrop     { display: none !important; }
          .app-drawer              { display: none !important; }
        }
      `}</style>

      <aside style={layoutStyles.sidebar} className="app-sidebar">
        <SidebarContent/>
      </aside>

      <div style={layoutStyles.topBar} className="app-topbar">
        <div style={layoutStyles.topBarBrand}>
          <div style={layoutStyles.brandMark}>T</div>
          <span style={layoutStyles.brandName}>Tally</span>
        </div>
        <button
          style={layoutStyles.burgerBtn}
          onClick={() => setMenuOpen(p => !p)}
          aria-label={menuOpen ? 'Close menu' : 'Open menu'}
        >
          <Icon name={menuOpen ? 'plus' : 'menu'} size={20}/>
        </button>
      </div>

      {menuOpen && (
        <div
          style={layoutStyles.backdrop}
          className="app-drawer-backdrop"
          onClick={() => setMenuOpen(false)}
          aria-hidden="true"
        />
      )}

      <aside
        style={{
          ...layoutStyles.drawer,
          transform: menuOpen ? 'translateX(0)' : 'translateX(-100%)',
        }}
        className="app-drawer"
        aria-hidden={!menuOpen}
      >
        <SidebarContent/>
      </aside>

      <main style={layoutStyles.main} className="app-main">
        {children}
      </main>
    </div>
  )
}

const layoutStyles = {
  shell: {
    display: 'flex',
    height: '100dvh',
    minHeight: '100vh',          // fallback for browsers without dvh
    overflow: 'hidden',
  },
  sidebar: {
    width: 232,
    minWidth: 232,
    background: 'var(--bg-elevated)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    padding: '18px 14px',
  },

  brand: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '4px 8px 18px',
  },
  brandMark: {
    width: 30,
    height: 30,
    borderRadius: 9,
    background: 'linear-gradient(135deg, var(--brand), var(--accent))',
    display: 'grid',
    placeItems: 'center',
    color: 'var(--brand-ink)',
    fontWeight: 800,
    fontSize: 15,
    boxShadow: '0 2px 10px color-mix(in oklab, var(--brand) 40%, transparent)',
    flexShrink: 0,
  },
  brandText: {
    display: 'flex',
    flexDirection: 'column',
    lineHeight: 1.15,
  },
  brandName: {
    fontWeight: 700,
    fontSize: 15,
    color: 'var(--text)',
  },
  brandSub: {
    fontSize: 11,
    color: 'var(--text-faint)',
  },

  sectionLabel: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: '0.08em',
    color: 'var(--text-faint)',
    padding: '14px 12px 6px',
    textTransform: 'uppercase',
  },

  nav: {
    display: 'flex',
    flexDirection: 'column',
    gap: 1,
  },
  navLink: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    padding: '9px 12px',
    borderRadius: 'var(--radius)',
    color: 'var(--text-muted)',
    fontSize: 13,
    fontWeight: 500,
    textDecoration: 'none',
    transition: 'color 0.15s, background 0.15s',
  },
  navLinkActive: {
    color: 'var(--text)',
    background: 'var(--bg-hover)',
    fontWeight: 600,
  },
  navLinkRail: {
    position: 'absolute',
    left: -10,
    top: 8,
    bottom: 8,
    width: 3,
    borderRadius: 2,
    background: 'var(--brand)',
  },

  userCard: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    marginTop: 12,
    padding: 12,
    borderRadius: 10,
    background: 'var(--bg)',
    border: '1px solid var(--border)',
  },
  userAvatar: {
    width: 30,
    height: 30,
    borderRadius: '50%',
    background: 'color-mix(in oklab, var(--info) 30%, var(--bg-hover))',
    color: 'var(--info)',
    display: 'grid',
    placeItems: 'center',
    fontWeight: 700,
    fontSize: 13,
    flexShrink: 0,
  },
  userInfo: {
    display: 'flex',
    flexDirection: 'column',
    flex: 1,
    minWidth: 0,
    lineHeight: 1.2,
  },
  username: {
    color: 'var(--text)',
    fontWeight: 600,
    fontSize: 13,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },
  userRole: {
    color: 'var(--text-faint)',
    fontSize: 11,
  },
  logoutBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text-faint)',
    cursor: 'pointer',
    padding: 4,
    display: 'grid',
    placeItems: 'center',
  },

  // Mobile chrome
  topBar: {
    display: 'none',
    alignItems: 'center',
    justifyContent: 'space-between',
    position: 'fixed',
    top: 0, left: 0, right: 0,
    height: 56,
    padding: '0 16px',
    background: 'var(--bg-elevated)',
    borderBottom: '1px solid var(--border)',
    zIndex: 200,
  },
  topBarBrand: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
  },
  burgerBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--text)',
    cursor: 'pointer',
    padding: 6,
    display: 'grid',
    placeItems: 'center',
  },
  backdrop: {
    position: 'fixed',
    inset: 0,
    background: 'rgba(0, 0, 0, 0.55)',
    zIndex: 300,
  },
  drawer: {
    position: 'fixed',
    top: 0, left: 0, bottom: 0,
    width: 260,
    background: 'var(--bg-elevated)',
    borderRight: '1px solid var(--border)',
    display: 'flex',
    flexDirection: 'column',
    padding: '18px 14px',
    zIndex: 400,
    transition: 'transform 0.25s ease',
    transform: 'translateX(-100%)',
  },

  main: {
    flex: 1,
    overflow: 'auto',
    background: 'var(--bg)',
    padding: '22px 32px 60px',
  },
}
