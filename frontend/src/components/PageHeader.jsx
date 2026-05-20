// PageHeader — the shared "TopBar" treatment (FE-004).
//
// Visual contract (Family A — current Transactions / Budgets header):
//   • elevated bar background     var(--bg-elevated)
//   • bottom divider              1px solid var(--border)
//   • padding                     20px 32px (desktop) · 16px (mobile)
//   • title                       fontSize 22, weight 700, letterSpacing -0.01em
//   • subtitle                    fontSize 13, var(--text-faint)
//
// The bar bleeds to the page edges via negative margins that cancel the
// Layout <main> padding (22px 32px desktop · 16px sides mobile), matching how
// Transactions/Budgets already do it. Pass `actions` for the right-hand button
// cluster (+ Add, Import, month nav, etc.) and `isMobile` from useBreakpoint.

export default function PageHeader({ title, subtitle, actions = null, isMobile = false }) {
  return (
    <div style={{
      display: 'flex',
      alignItems: isMobile ? 'flex-start' : 'center',
      justifyContent: 'space-between',
      flexWrap: isMobile ? 'wrap' : 'nowrap',
      gap: isMobile ? 12 : 0,
      padding: isMobile ? '16px' : '20px 32px',
      borderBottom: '1px solid var(--border)',
      background: 'var(--bg-elevated)',
      margin: isMobile ? '0 -16px 16px' : '-22px -32px 22px',
    }}>
      <div style={{ minWidth: 0 }}>
        <h1 style={{
          margin: 0, fontSize: 22, fontWeight: 700,
          color: 'var(--text)', letterSpacing: '-0.01em',
        }}>{title}</h1>
        {subtitle != null && subtitle !== false && (
          <div style={{ fontSize: 13, color: 'var(--text-faint)', marginTop: 2 }}>
            {subtitle}
          </div>
        )}
      </div>
      {actions && (
        <div style={{ display: 'flex', gap: 10, flexShrink: 0 }}>
          {actions}
        </div>
      )}
    </div>
  )
}
