import { useEffect, useState } from 'react'
import useBreakpoint from '../hooks/useBreakpoint'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useCurrency } from '../context/CurrencyContext'
import { formatDate } from '../utils/dateFormat'
import Icon from '../components/Icon'
import Pill from '../components/Pill'
import Sparkline from '../components/Sparkline'
import Button from '../components/Button'

const USE_MOCK_DATA = import.meta.env.VITE_MOCK_DASHBOARD === 'true'

const MOCK = {
  netWorth: 51248.92,
  netWorthChange: 4120,
  netWorthHistory: [12, 14, 15, 14, 17, 18, 20, 22, 21, 24, 26, 28, 31, 32, 35, 38, 42, 45, 47, 51],
  monthIncome: 6840,
  monthSpent: 2872,
  monthBudget: 6800,
  daysLeft: 17,
  attention: [
    { tone: 'warning', icon: 'warn',    title: '4 transactions unverified', sub: 'Imported from CSV on Apr 22', cta: 'Review', href: '/transactions?filter=unverified' },
    { tone: 'info',    icon: 'repeat',  title: 'Netflix charges tomorrow',  sub: '$22.99 from Checking',           cta: 'See details', href: '/recurring' },
    { tone: 'brand',   icon: 'target',  title: 'Dining over budget by $12', sub: '106% of $200 — 6 days left',     cta: 'Adjust', href: '/budgets' },
  ],
  budgetCategories: [
    { name: 'Rent',          spent: 1800, budget: 1800, color: 'var(--chart-4)' },
    { name: 'Groceries',     spent: 412,  budget: 600,  color: 'var(--chart-1)' },
    { name: 'Dining',        spent: 186,  budget: 200,  color: 'var(--chart-5)' },
    { name: 'Transport',     spent: 94,   budget: 150,  color: 'var(--chart-2)' },
    { name: 'Entertainment', spent: 212,  budget: 150,  color: 'var(--chart-3)' },
    { name: 'Utilities',     spent: 168,  budget: 250,  color: 'var(--chart-6)' },
  ],
}

function StatCard({ label, value, accent, sparkline, sparklineColor }) {
  return (
    <div style={dashStyles.card}>
      <div style={dashStyles.cardLabel}>{label}</div>
      <div style={{ ...dashStyles.cardValue, color: accent || 'var(--text)' }}>{value}</div>
      {sparkline && (
        <div style={{ marginTop: 10 }}>
          <Sparkline points={sparkline} width={140} height={28} color={sparklineColor || accent} fill={false}/>
        </div>
      )}
    </div>
  )
}

function SectionHeader({ title, subtitle, action }) {
  return (
    <div style={dashStyles.sectionHeader}>
      <div>
        <div style={dashStyles.sectionTitle}>{title}</div>
        {subtitle && <div style={dashStyles.sectionSub}>{subtitle}</div>}
      </div>
      {action}
    </div>
  )
}

export default function Dashboard() {
  const navigate = useNavigate()
  const { user } = useAuth()
  const { formatCurrency } = useCurrency()
  const { isMobile } = useBreakpoint()
  const [accounts, setAccounts] = useState([])
  const [recentTx, setRecentTx] = useState([])
  const [summary, setSummary] = useState(USE_MOCK_DATA ? MOCK : null)
  const [loading, setLoading] = useState(true)
  const [range, setRange] = useState('12M')
  const [loadError, setLoadError] = useState(null)

  useEffect(() => {
    const calls = [
      client.get('/accounts'),
      client.get('/transactions?limit=6'),
    ]
    if (!USE_MOCK_DATA) {
      calls.push(client.get('/dashboard/summary'))
    }
    Promise.all(calls)
      .then(results => {
        setAccounts(results[0].data)
        setRecentTx(results[1].data)
        if (!USE_MOCK_DATA) setSummary(results[2].data)
      })
      .catch(err => {
        // Surface load failures instead of hanging on "Loading…" forever (AUDIT-25).
        setLoadError(err?.response?.data?.detail || err?.message || 'Could not load your dashboard. Please refresh.')
      })
      .finally(() => setLoading(false))
  }, [])

  if (loading) {
    return <div style={{ padding: 32, color: 'var(--text-muted)' }}>Loading…</div>
  }
  if (loadError) {
    return <div style={{ padding: 32, color: 'var(--negative)' }}>{loadError}</div>
  }
  if (!summary) {
    return <div style={{ padding: 32, color: 'var(--text-muted)' }}>No dashboard data available.</div>
  }

  const totalBalance = accounts.reduce((sum, a) => sum + a.balance, 0)
  // Guard divide-by-zero: no budget set -> show 0% rather than NaN%/Infinity%.
  const budgetPct = summary.monthBudget > 0
    ? Math.round((summary.monthSpent / summary.monthBudget) * 100)
    : 0
  const monthNet = summary.monthIncome - summary.monthSpent

  // BACKLOG-034a — the backend returns a fixed 12-month series of monthly net
  // cash-flow (income - expenses per month), NOT a net-worth trend. The range
  // selector slices this returned window client-side; a real net-worth trend and
  // a backend range param are a separate v1.5 item.
  // 1M slices the last 2 points (not 1): the Sparkline needs ≥2 points to draw,
  // so "1M" shows the month-over-month step into the current month rather than a
  // blank chart. The 1M/3M/6M/12M button labels are unchanged (BACKLOG-034a).
  const CASHFLOW_RANGES = { '1M': 2, '3M': 3, '6M': 6, '12M': 12 }
  const fullSeries = summary.netWorthHistory || []
  const cashflowSeries = fullSeries.slice(-CASHFLOW_RANGES[range])
  const greeting = greetingFor(new Date())

  return (
    <div>
<div className="page-header" data-page-header style={{ ...dashStyles.topbar, position: isMobile ? 'relative' : 'sticky' }}>
        <div>
          <h1 style={dashStyles.title}>{greeting}, {user?.username}</h1>
          <p style={dashStyles.subtitle}>Here's where your household sits today</p>
        </div>
        <div className="actions" data-actions style={{ display: 'flex', gap: 10 }}>
          <Button variant="secondary" onClick={() => navigate('/import')}><Icon name="upload" size={14}/>Import</Button>
          <Button variant="primary" onClick={() => navigate('/transactions?action=add')}><Icon name="plus" size={14}/>Add transaction</Button>
        </div>
      </div>

      <div style={dashStyles.body}>
        {/* Hero row */}
        <div style={{ ...dashStyles.heroRow, gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(280px, 1fr))' }}>
          <div style={{ ...dashStyles.card, padding: 0 }}>
            <div style={{ ...dashStyles.heroHeader, ...(isMobile && { flexDirection: 'column', gap: 10 }) }}>
              <div>
                <div style={dashStyles.cardLabel}>Net worth</div>
                <div style={dashStyles.heroValue}>{formatCurrency(summary.netWorth)}</div>
                <div style={dashStyles.heroChange}>
                  <Pill tone={summary.netWorthChange >= 0 ? 'positive' : 'negative'}>
                    <Icon name={summary.netWorthChange >= 0 ? 'arrowUp' : 'arrowDown'} size={10} stroke={2.5}/>
                    {summary.netWorthChange >= 0 ? '+' : ''}{formatCurrency(summary.netWorthChange)}
                  </Pill>
                  <span style={dashStyles.heroChangeNote}>vs. last month</span>
                </div>
              </div>
              <div style={dashStyles.rangeSelector}>
                {Object.keys(CASHFLOW_RANGES).map(r => (
                  <button
                    key={r}
                    onClick={() => setRange(r)}
                    style={{
                      ...dashStyles.rangeButton,
                      ...(range === r ? dashStyles.rangeButtonActive : {}),
                    }}
                  >{r}</button>
                ))}
              </div>
            </div>
            <div style={{ padding: '0 16px 16px' }}>
              <div style={{ fontSize: 11, color: 'var(--text-faint)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>
                Monthly net cash flow
              </div>
              <Sparkline
                points={cashflowSeries}
                width={560}
                height={130}
                color="var(--brand)"
                fill={true}
              />
            </div>
          </div>

          <div style={dashStyles.card}>
            <div style={dashStyles.cardLabel}>This month</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 12, marginTop: 12 }}>
              <div>
                <div style={dashStyles.miniLabel}>
                  <span style={{ ...dashStyles.dot, background: 'var(--positive)' }}/>Income
                </div>
                <div style={dashStyles.miniValue}>{formatCurrency(summary.monthIncome)}</div>
              </div>
              <div>
                <div style={dashStyles.miniLabel}>
                  <span style={{ ...dashStyles.dot, background: 'var(--negative)' }}/>Spent
                </div>
                <div style={dashStyles.miniValue}>{formatCurrency(summary.monthSpent)}</div>
              </div>
            </div>

            <div style={{ marginTop: 16 }}>
              <div style={dashStyles.budgetRow}>
                <span>Budget used</span>
                <span style={{ color: 'var(--text)', fontWeight: 600 }}>{budgetPct}%</span>
              </div>
              <div style={dashStyles.budgetTrack}>
                <div style={{
                  width: `${Math.min(budgetPct, 100)}%`,
                  height: '100%',
                  background: 'linear-gradient(90deg, var(--positive), var(--warning))',
                }}/>
              </div>
              <div style={dashStyles.budgetMeta}>
                <span>{formatCurrency(summary.monthSpent)} of {formatCurrency(summary.monthBudget)}</span>
                <span>{summary.daysLeft} days left</span>
              </div>
            </div>

            <div style={dashStyles.divider}/>
            <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
              <div style={{ flex: 1 }}>
                <div style={dashStyles.smallLabel}>Net this month</div>
                <div style={{ ...dashStyles.netValue, color: monthNet >= 0 ? 'var(--positive)' : 'var(--negative)' }}>
                  {monthNet >= 0 ? '+' : ''}{formatCurrency(monthNet)}
                </div>
              </div>
            </div>
          </div>
        </div>

        {/* Needs attention */}
        {summary.attention?.length > 0 && (
          <div style={{ ...dashStyles.card, padding: 0 }}>
            <SectionHeader
              title="Needs your attention"
              subtitle={`${summary.attention.length} items across transactions and bills`}
              action={<Button variant="ghost" size="sm">View all</Button>}
            />
            <div style={dashStyles.divider}/>
            <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : `repeat(${summary.attention.length}, 1fr)` }}>
              {summary.attention.map((it, i) => (
                <div key={i} style={{
                  ...dashStyles.attentionCard,
                  borderRight: i < summary.attention.length - 1 ? '1px solid var(--border)' : 'none',
                }}>
                  <div style={{
                    ...dashStyles.attentionIcon,
                    background: `color-mix(in oklab, var(--${it.tone}) 18%, transparent)`,
                    color: `var(--${it.tone})`,
                  }}>
                    <Icon name={it.icon} size={16}/>
                  </div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={dashStyles.attentionTitle}>{it.title}</div>
                    <div style={dashStyles.attentionSub}>{it.sub}</div>
                    <a href={it.href} style={dashStyles.attentionCta}>{it.cta} →</a>
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Accounts + budgets */}
        <div style={{ ...dashStyles.twoCol, gridTemplateColumns: isMobile ? '1fr' : 'repeat(auto-fit, minmax(220px, 1fr))' }}>
          <div style={{ ...dashStyles.card, padding: 0, minWidth: 0 }}>
            <SectionHeader
              title="Accounts"
              action={<Button variant="ghost" size="sm"><Icon name="plus" size={12}/>Add</Button>}
            />
            <div style={dashStyles.divider}/>
            {accounts.length === 0 ? (
              <div style={dashStyles.empty}>No accounts yet.</div>
            ) : accounts.slice(0, 5).map((a, i) => (
              <div key={a.id} style={{
                ...dashStyles.accountRow,
                borderBottom: i < Math.min(accounts.length, 5) - 1 ? '1px solid var(--border)' : 'none',
              }}>
                <div>
                  <div style={dashStyles.accountName}>{a.name}</div>
                  <div style={dashStyles.accountMeta}>
                    {a.institution ?? '—'} · <span style={{ textTransform: 'capitalize' }}>{a.account_type ?? 'account'}</span>
                  </div>
                </div>
                <div style={{
                  fontWeight: 700,
                  fontVariantNumeric: 'tabular-nums',
                  textAlign: 'right',
                  color: a.balance >= 0 ? 'var(--text)' : 'var(--negative)',
                }}>
                  {formatCurrency(a.balance)}
                </div>
              </div>
            ))}
            {accounts.length > 0 && (
              <div style={{ ...dashStyles.totalRow, borderTop: '1px solid var(--border)' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>Total</span>
                <span style={{
                  fontWeight: 700,
                  fontVariantNumeric: 'tabular-nums',
                  color: totalBalance >= 0 ? 'var(--positive)' : 'var(--negative)',
                }}>
                  {formatCurrency(totalBalance)}
                </span>
              </div>
            )}
          </div>

          <div style={{ ...dashStyles.card, padding: 0, minWidth: 0 }}>
            <SectionHeader
              title="Budget progress"
              action={<span style={{ fontSize: 11, color: 'var(--text-faint)' }}>{monthName(new Date())}</span>}
            />
            <div style={dashStyles.divider}/>
            <div style={{ padding: '14px 20px', display: 'grid', gap: 12 }}>
              {summary.budgetCategories.map(c => {
                // Guard divide-by-zero: no budget set -> 0% rather than NaN%/Infinity%.
                const pct = c.budget > 0 ? (c.spent / c.budget) * 100 : 0
                const over = pct > 100
                return (
                  <div key={c.name}>
                    <div style={dashStyles.budgetCatRow}>
                      <span style={dashStyles.budgetCatLabel}>
                        <span style={{ ...dashStyles.dot, background: c.color }}/>{c.name}
                      </span>
                      <span style={{ color: 'var(--text-muted)', fontVariantNumeric: 'tabular-nums', fontSize: 12 }}>
                        ${c.spent} <span style={{ color: 'var(--text-faint)' }}>/ ${c.budget}</span>
                      </span>
                    </div>
                    <div style={dashStyles.budgetCatTrack}>
                      <div style={{
                        width: `${Math.min(pct, 100)}%`,
                        height: '100%',
                        background: over ? 'var(--negative)' : c.color,
                      }}/>
                    </div>
                  </div>
                )
              })}
            </div>
          </div>
        </div>

        {/* Recent transactions */}
        <div style={{ ...dashStyles.card, padding: 0, minWidth: 0 }}>
          <SectionHeader
            title="Recent transactions"
            subtitle={`Latest ${recentTx.length} across all accounts`}
            action={<Button variant="ghost" size="sm">See all →</Button>}
          />
          <div style={dashStyles.divider}/>
          {recentTx.length === 0 ? (
            <div style={dashStyles.empty}>No transactions yet.</div>
          ) : recentTx.map((tx, i) => (
            <div key={tx.id} style={{
              ...(isMobile ? dashStyles.txRowMobile : dashStyles.txRow),
              borderBottom: i < recentTx.length - 1 ? '1px solid var(--border)' : 'none',
            }}>
              {isMobile ? (
                <>
                  <div style={{ minWidth: 0, display: 'grid', gap: 2 }}>
                    <span style={dashStyles.txDesc}>{tx.description ?? '—'}</span>
                    <span style={{ color: 'var(--text-faint)', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {formatDate(tx.date)} · {tx.category?.name ?? '—'}
                    </span>
                  </div>
                  <span style={{
                    textAlign: 'right',
                    fontWeight: 700,
                    fontVariantNumeric: 'tabular-nums',
                    color: tx.amount >= 0 ? 'var(--positive)' : 'var(--text)',
                    whiteSpace: 'nowrap',
                  }}>
                    {formatCurrency(tx.amount)}
                  </span>
                </>
              ) : (
                <>
                  <span style={{ color: 'var(--text-faint)', fontSize: 12 }}>{formatDate(tx.date)}</span>
                  <span style={dashStyles.txDesc}>{tx.description ?? '—'}</span>
                  <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
                    {tx.category?.name ?? '—'}
                  </span>
                  <span style={{ textAlign: 'center' }}>
                    <Pill tone={tx.is_verified ? 'positive' : 'warning'}>
                      {tx.is_verified ? 'Verified' : 'Review'}
                    </Pill>
                  </span>
                  <span style={{
                    textAlign: 'right',
                    fontWeight: 700,
                    fontVariantNumeric: 'tabular-nums',
                    color: tx.amount >= 0 ? 'var(--positive)' : 'var(--text)',
                  }}>
                    {formatCurrency(tx.amount)}
                  </span>
                </>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function greetingFor(date) {
  const h = date.getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

function monthName(date) {
  return date.toLocaleDateString(undefined, { month: 'long', year: 'numeric' })
}

const dashStyles = {
  topbar: {
    display: 'flex',
    alignItems: 'flex-end',
    justifyContent: 'space-between',
    flexWrap: 'wrap',
    gap: 16,
    padding: '26px 32px 18px',
    background: 'var(--bg)',
  },
  title: {
    fontSize: 22,
    fontWeight: 700,
    color: 'var(--text)',
    letterSpacing: '-0.01em',
    margin: 0,
  },
  subtitle: {
    color: 'var(--text-faint)',
    fontSize: 13,
    marginTop: 3,
  },
  body: {
    display: 'grid',
    gap: 22,
    minWidth: 0,
    overflow: 'hidden',
  },
  card: {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: 20,
  },
  cardLabel: {
    fontSize: 11,
    fontWeight: 600,
    color: 'var(--text-faint)',
    textTransform: 'uppercase',
    letterSpacing: '0.08em',
  },
  cardValue: {
    fontSize: 26,
    fontWeight: 700,
    marginTop: 6,
  },

  heroRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))',
    gap: 22,
  },
  heroHeader: {
    padding: '22px 24px 10px',
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
  },
  heroValue: {
    fontSize: 38,
    fontWeight: 700,
    color: 'var(--text)',
    letterSpacing: '-0.02em',
    marginTop: 4,
    fontVariantNumeric: 'tabular-nums',
  },
  heroChange: {
    display: 'flex',
    alignItems: 'center',
    gap: 8,
    marginTop: 6,
  },
  heroChangeNote: {
    fontSize: 12,
    color: 'var(--text-faint)',
  },
  rangeSelector: {
    display: 'flex',
    gap: 4,
    flexWrap: 'wrap',
    justifyContent: 'flex-end',
    background: 'var(--bg)',
    padding: 3,
    borderRadius: 8,
    border: '1px solid var(--border)',
  },
  rangeButton: {
    padding: '4px 10px',
    borderRadius: 6,
    fontSize: 11,
    fontWeight: 600,
    background: 'transparent',
    color: 'var(--text-faint)',
    border: 'none',
    cursor: 'pointer',
  },
  rangeButtonActive: {
    background: 'var(--bg-hover)',
    color: 'var(--text)',
  },

  miniLabel: {
    display: 'flex',
    alignItems: 'center',
    gap: 6,
    color: 'var(--text-muted)',
    fontSize: 12,
  },
  miniValue: {
    fontSize: 22,
    fontWeight: 700,
    color: 'var(--text)',
    marginTop: 4,
    fontVariantNumeric: 'tabular-nums',
  },
  dot: {
    width: 8,
    height: 8,
    borderRadius: 2,
    display: 'inline-block',
  },
  budgetRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 12,
    color: 'var(--text-muted)',
    marginBottom: 6,
  },
  budgetTrack: {
    height: 6,
    borderRadius: 3,
    background: 'var(--bg-input)',
    overflow: 'hidden',
  },
  budgetMeta: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 11,
    color: 'var(--text-faint)',
    marginTop: 5,
  },
  smallLabel: {
    fontSize: 11,
    color: 'var(--text-faint)',
  },
  netValue: {
    fontSize: 16,
    fontWeight: 700,
    fontVariantNumeric: 'tabular-nums',
    marginTop: 2,
  },
  divider: {
    height: 1,
    background: 'var(--border)',
    width: '100%',
    margin: '14px 0',
  },

  sectionHeader: {
    padding: '16px 20px 12px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'space-between',
  },
  sectionTitle: {
    fontSize: 14,
    fontWeight: 600,
    color: 'var(--text)',
  },
  sectionSub: {
    fontSize: 12,
    color: 'var(--text-faint)',
    marginTop: 2,
  },

  attentionCard: {
    padding: '16px 20px',
    display: 'flex',
    gap: 12,
    alignItems: 'flex-start',
  },
  attentionIcon: {
    width: 32,
    height: 32,
    borderRadius: 8,
    flexShrink: 0,
    display: 'grid',
    placeItems: 'center',
  },
  attentionTitle: {
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text)',
  },
  attentionSub: {
    fontSize: 12,
    color: 'var(--text-faint)',
    marginTop: 2,
  },
  attentionCta: {
    fontSize: 12,
    color: 'var(--brand)',
    fontWeight: 600,
    marginTop: 8,
    cursor: 'pointer',
    display: 'inline-block',
    textDecoration: 'none',
  },

  twoCol: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
    gap: 22,
  },

  accountRow: {
    display: 'grid',
    gridTemplateColumns: '1fr auto',
    alignItems: 'center',
    gap: 14,
    padding: '12px 20px',
  },
  accountName: {
    fontSize: 13,
    fontWeight: 600,
    color: 'var(--text)',
  },
  accountMeta: {
    fontSize: 11,
    color: 'var(--text-faint)',
    marginTop: 1,
  },
  totalRow: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '12px 20px',
    background: 'var(--bg)',
  },

  budgetCatRow: {
    display: 'flex',
    justifyContent: 'space-between',
    fontSize: 12,
    marginBottom: 5,
    alignItems: 'center',
  },
  budgetCatLabel: {
    color: 'var(--text)',
    fontWeight: 500,
    display: 'flex',
    alignItems: 'center',
    gap: 7,
  },
  budgetCatTrack: {
    height: 5,
    borderRadius: 3,
    background: 'var(--bg-input)',
    overflow: 'hidden',
  },

  txRow: {
    display: 'grid',
    gridTemplateColumns: '90px 1fr 140px 100px 110px',
    padding: '11px 20px',
    fontSize: 13,
    alignItems: 'center',
    gap: 14,
  },
  txRowMobile: {
    display: 'grid',
    gridTemplateColumns: '1fr auto',
    padding: '11px 16px',
    fontSize: 13,
    alignItems: 'center',
    gap: 12,
    minWidth: 0,
  },
  txDesc: {
    color: 'var(--text)',
    fontWeight: 500,
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    whiteSpace: 'nowrap',
  },

  empty: {
    color: 'var(--text-muted)',
    fontSize: 14,
    padding: '24px 20px',
    textAlign: 'center',
  },
}
