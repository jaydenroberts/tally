import { useEffect, useState } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useCurrency } from '../context/CurrencyContext'
import { formatDate } from '../utils/dateFormat'

function StatCard({ label, value, accent }) {
  return (
    <div style={{ ...styles.card, borderTop: `3px solid ${accent}` }}>
      <p style={styles.cardLabel}>{label}</p>
      <p style={{ ...styles.cardValue, color: accent }}>{value}</p>
    </div>
  )
}

function SectionHeader({ title }) {
  return <h2 style={styles.sectionHeader}>{title}</h2>
}

export default function Dashboard() {
  const { user } = useAuth()
  const { formatCurrency } = useCurrency()
  const [accounts, setAccounts] = useState([])
  const [recentTx, setRecentTx] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    Promise.all([
      client.get('/accounts'),
      client.get('/transactions?limit=5'),
    ])
      .then(([accRes, txRes]) => {
        setAccounts(accRes.data)
        setRecentTx(txRes.data)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [])

  const totalBalance = accounts.reduce((sum, a) => sum + a.balance, 0)
  const unverified = recentTx.filter((t) => !t.is_verified).length

  if (loading) {
    return <p style={{ color: 'var(--muted)' }}>Loading…</p>
  }

  return (
    <div>
      <div style={styles.pageHeader}>
        <h1 style={styles.pageTitle}>Dashboard</h1>
        <p style={styles.welcome}>Welcome back, {user?.username}</p>
      </div>

      <div style={styles.statsRow}>
        <StatCard
          label="Total Balance"
          value={formatCurrency(totalBalance)}
          accent="var(--green)"
        />
        <StatCard
          label="Accounts"
          value={accounts.length}
          accent="var(--cyan)"
        />
        <StatCard
          label="Unverified Transactions"
          value={unverified}
          accent={unverified > 0 ? 'var(--orange)' : 'var(--muted)'}
        />
      </div>

      <SectionHeader title="Accounts" />
      {accounts.length === 0 ? (
        <p style={styles.empty}>No accounts yet. Add one to get started.</p>
      ) : (
        <div style={styles.table}>
          <div style={styles.tableHeader}>
            <span>Name</span>
            <span>Type</span>
            <span>Institution</span>
            <span style={{ textAlign: 'right' }}>Balance</span>
          </div>
          {accounts.map((a) => (
            <div key={a.id} style={styles.tableRow}>
              <span>{a.name}</span>
              <span style={{ color: 'var(--muted)', textTransform: 'capitalize' }}>
                {a.account_type ?? '—'}
              </span>
              <span style={{ color: 'var(--muted)' }}>{a.institution ?? '—'}</span>
              <span style={{ textAlign: 'right', color: a.balance >= 0 ? 'var(--green)' : 'var(--red)' }}>
                {formatCurrency(a.balance)}
              </span>
            </div>
          ))}
        </div>
      )}

      <SectionHeader title="Recent Transactions" />
      {recentTx.length === 0 ? (
        <p style={styles.empty}>No transactions yet.</p>
      ) : (
        <div style={styles.table}>
          <div style={styles.tableHeader}>
            <span>Date</span>
            <span>Description</span>
            <span>Category</span>
            <span style={{ textAlign: 'right' }}>Amount</span>
            <span style={{ textAlign: 'center' }}>Status</span>
          </div>
          {recentTx.map((tx) => (
            <div key={tx.id} style={styles.tableRow}>
              <span style={{ color: 'var(--muted)' }}>{formatDate(tx.date)}</span>
              <span>{tx.description ?? '—'}</span>
              <span style={{ color: 'var(--muted)' }}>{tx.category?.name ?? '—'}</span>
              <span style={{ textAlign: 'right', color: tx.amount >= 0 ? 'var(--green)' : 'var(--pink)' }}>
                {formatCurrency(tx.amount)}
              </span>
              <span style={{ textAlign: 'center' }}>
                <span style={{
                  fontSize: 11,
                  padding: '2px 8px',
                  borderRadius: 99,
                  background: tx.is_verified ? '#50FA7B20' : '#FF79C620',
                  color: tx.is_verified ? 'var(--green)' : 'var(--pink)',
                }}>
                  {tx.is_verified ? 'Verified' : 'Unverified'}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  pageHeader: {
    marginBottom: 28,
  },
  pageTitle: {
    fontSize: 24,
    fontWeight: 700,
    color: 'var(--white)',
  },
  welcome: {
    color: 'var(--muted)',
    fontSize: 14,
    marginTop: 4,
  },
  statsRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
    gap: 16,
    marginBottom: 36,
  },
  card: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: '20px 24px',
  },
  cardLabel: {
    fontSize: 12,
    fontWeight: 500,
    color: 'var(--muted)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    marginBottom: 8,
  },
  cardValue: {
    fontSize: 26,
    fontWeight: 700,
  },
  sectionHeader: {
    fontSize: 16,
    fontWeight: 600,
    color: 'var(--white)',
    marginBottom: 12,
    paddingBottom: 8,
    borderBottom: '1px solid var(--border)',
  },
  table: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    overflow: 'hidden',
    marginBottom: 32,
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '120px 1fr 1fr 120px 100px',
    padding: '10px 20px',
    background: 'var(--bg)',
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: 'var(--muted)',
    borderBottom: '1px solid var(--border)',
  },
  tableRow: {
    display: 'grid',
    gridTemplateColumns: '120px 1fr 1fr 120px 100px',
    padding: '12px 20px',
    fontSize: 14,
    borderBottom: '1px solid var(--border)',
    alignItems: 'center',
  },
  empty: {
    color: 'var(--muted)',
    fontSize: 14,
    padding: '20px 0',
  },
}
