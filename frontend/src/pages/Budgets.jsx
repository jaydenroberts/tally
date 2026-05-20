import { useEffect, useMemo, useState } from 'react'
import client from '../api/client'
import { useCurrency } from '../context/CurrencyContext'
import useBreakpoint from '../hooks/useBreakpoint'
import Button from '../components/Button'
import Icon from '../components/Icon'
import Modal from '../components/Modal'
import PageHeader from '../components/PageHeader'
import BudgetForm from './Budgets.legacy/BudgetForm'

const MONTH_NAMES = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
]

// Transform List[BudgetStatus] from /budgets/summary into the shape
// the redesigned components expect.
function transformSummary(period, statusList) {
  const categories = statusList.map(item => ({
    id:             item.budget.id,
    category_id:    item.budget.category_id,
    name:           item.budget.category?.name  ?? 'Other',
    color:          item.budget.category?.color ?? 'var(--chart-1)',
    budget:         item.budget.amount,
    period:         item.budget.period,
    start_date:     item.budget.start_date,
    end_date:       item.budget.end_date,
    spent_verified: item.verified_spend,
    spent_estimated: item.estimated_spend,
    transactions_count: 0,
  }))
  return { period, categories, insights: [] }
}

function parsePeriod(period) {
  const [y, m] = period.split('-').map(Number)
  return { year: y, month: m }
}

function currentPeriod() {
  const d = new Date()
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`
}

// ─── Primitive components ────────────────────────────────────────────────────

function Pill({ children, tone = 'neutral' }) {
  const tones = {
    neutral:  { bg: 'var(--bg-hover)',                                          fg: 'var(--text-muted)', ring: 'var(--border)' },
    positive: { bg: 'color-mix(in oklab, var(--positive) 15%, transparent)',    fg: 'var(--positive)',   ring: 'color-mix(in oklab, var(--positive) 35%, transparent)' },
    negative: { bg: 'color-mix(in oklab, var(--negative) 15%, transparent)',    fg: 'var(--negative)',   ring: 'color-mix(in oklab, var(--negative) 35%, transparent)' },
    warning:  { bg: 'color-mix(in oklab, var(--warning) 15%, transparent)',     fg: 'var(--warning)',    ring: 'color-mix(in oklab, var(--warning) 35%, transparent)' },
  }
  const t = tones[tone] || tones.neutral
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 9px', borderRadius: 999,
      background: t.bg, color: t.fg, fontSize: 11, fontWeight: 600,
      border: `1px solid ${t.ring}`, whiteSpace: 'nowrap',
    }}>{children}</span>
  )
}

function Card({ children, padding = 18 }) {
  return (
    <div style={{
      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
      borderRadius: 10, padding,
    }}>{children}</div>
  )
}

// ─── Month picker ────────────────────────────────────────────────────────────

function MonthPicker({ period, onChange }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const { year, month } = parsePeriod(period)
  const label = `${MONTH_NAMES[month - 1]} ${year}`
  const isCurrent = period === currentPeriod()

  const menuOptions = useMemo(() => {
    const opts = []
    const cur = parsePeriod(currentPeriod())
    for (let i = 24; i >= -12; i--) {
      let y = cur.year, m = cur.month - i
      while (m <= 0) { y--; m += 12 }
      while (m > 12) { y++; m -= 12 }
      const p = `${y}-${String(m).padStart(2, '0')}`
      opts.push({ period: p, label: `${MONTH_NAMES[m - 1]} ${y}` })
    }
    return opts
  }, [])

  return (
    <div style={{ display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 4, position: 'relative' }}>
      <Button variant="secondary" size="sm" onClick={() => onChange(prevPeriod(period))}>
        <Icon name="chevronRight" size={14} style={{ transform: 'scaleX(-1)' }}/>
      </Button>
      <button
        onClick={() => setMenuOpen(o => !o)}
        style={{ background: 'none', border: 'none', color: 'var(--text)',
                 fontSize: 14, fontWeight: 600, cursor: 'pointer',
                 padding: '6px 10px', borderRadius: 6,
                 whiteSpace: 'nowrap', minWidth: 'max-content' }}
      >
        {label}
      </button>
      <Button variant="secondary" size="sm"
              disabled={isCurrent}
              onClick={() => onChange(nextPeriod(period))}>
        <Icon name="chevronRight" size={14}/>
      </Button>
      {!isCurrent && (
        <Button variant="ghost" size="sm" onClick={() => onChange(currentPeriod())}>
          Today
        </Button>
      )}
      {menuOpen && (
        <div style={{ position: 'absolute', top: '100%', right: 0, marginTop: 6,
                      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
                      borderRadius: 8, maxHeight: 280, overflow: 'auto',
                      minWidth: 160, zIndex: 50, boxShadow: '0 6px 24px rgba(0,0,0,0.4)' }}>
          {menuOptions.map(opt => (
            <button key={opt.period}
                    onClick={() => { onChange(opt.period); setMenuOpen(false) }}
                    style={{ display: 'block', width: '100%', textAlign: 'left',
                             padding: '8px 12px', background: opt.period === period ? 'var(--bg-hover)' : 'transparent',
                             border: 'none', color: 'var(--text)', cursor: 'pointer', fontSize: 13 }}>
              {opt.label}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── Page header ─────────────────────────────────────────────────────────────

// ─── Summary card ────────────────────────────────────────────────────────────

function SummaryCard({ totals, insight, onApplyInsight }) {
  const { formatCurrency } = useCurrency()
  const { spent, budget, dailyAvg, safeToSpend, projected } = totals
  const pct      = budget > 0 ? Math.min(spent / budget, 1.5) : 0
  const pctLabel = budget > 0 ? Math.round((spent / budget) * 100) : 0
  const over     = spent > budget

  const C    = 2 * Math.PI * 72
  const dash = Math.min(pct, 1) * C

  return (
    <Card>
      <div
        className="chart-row"
        data-chart-row
        style={{
          display: 'grid',
          gridTemplateColumns: insight ? '180px 1fr 240px' : '180px 1fr',
          gap: 28, alignItems: 'center',
        }}
      >
        <div className="chart-donut" data-chart="donut" style={{ position: 'relative', width: 180, height: 180 }}>
          <svg viewBox="0 0 180 180">
            <circle cx="90" cy="90" r="72" fill="none" stroke="var(--bg-input)" strokeWidth="14"/>
            <circle
              cx="90" cy="90" r="72" fill="none"
              stroke={over ? 'var(--negative)' : 'var(--brand)'}
              strokeWidth="14" strokeLinecap="round"
              strokeDasharray={`${dash} ${C}`}
              transform="rotate(-90 90 90)"
            />
          </svg>
          <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', textAlign: 'center' }}>
            <div>
              <div style={{ fontSize: 28, fontWeight: 700, color: 'var(--text)', letterSpacing: '-0.02em', fontVariantNumeric: 'tabular-nums' }}>
                {pctLabel}%
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
                of budget
              </div>
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gap: 14 }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.08em', fontWeight: 600 }}>
              Spent so far
            </div>
            <div style={{ fontSize: 32, fontWeight: 700, color: 'var(--text)', fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.02em' }}>
              {formatCurrency(spent)}{' '}
              <span style={{ color: 'var(--text-faint)', fontWeight: 500, fontSize: 18 }}>
                / {formatCurrency(budget)}
              </span>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 16 }}>
            <Stat label="Daily avg"         value={formatCurrency(dailyAvg)}    tone="var(--text)"/>
            <Stat label="Safe to spend/day" value={formatCurrency(safeToSpend)} tone="var(--positive)"/>
            <Stat label="Projected"         value={formatCurrency(projected)}   tone={projected > budget ? 'var(--warning)' : 'var(--text)'}/>
          </div>
        </div>

        {insight && <InsightCallout insight={insight} onApply={onApplyInsight}/>}
      </div>
    </Card>
  )
}

function Stat({ label, value, tone }) {
  return (
    <div>
      <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{label}</div>
      <div style={{ fontSize: 15, fontWeight: 600, color: tone, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

function InsightCallout({ insight, onApply }) {
  return (
    <div style={{
      padding: 16, borderRadius: 10,
      background: 'color-mix(in oklab, var(--warning) 10%, var(--bg))',
      border: '1px solid color-mix(in oklab, var(--warning) 30%, transparent)',
    }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, color: 'var(--warning)', fontSize: 12, fontWeight: 600 }}>
        ⚠ {insight.title}
      </div>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 6, lineHeight: 1.4 }}>
        {insight.message}
      </div>
      {insight.suggested_action && (
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginTop: 10 }}>
          <button
            onClick={() => onApply(insight)}
            style={{
              fontSize: 12, color: 'var(--brand-ink)', fontWeight: 600,
              background: 'var(--brand)', border: 'none',
              padding: '6px 12px', borderRadius: 6, cursor: 'pointer',
            }}>
            {insight.suggested_action.label}
          </button>
          <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>or adjust manually →</span>
        </div>
      )}
    </div>
  )
}

// ─── Category card ───────────────────────────────────────────────────────────

function CategoryCard({ cat, daysLeft, onClick }) {
  const { formatCurrency } = useCurrency()
  const totalSpent  = cat.spent_verified + cat.spent_estimated
  const pct         = cat.budget > 0 ? (totalSpent / cat.budget) * 100 : 0
  const pctVerified = cat.budget > 0 ? Math.min((cat.spent_verified / cat.budget) * 100, 100) : 0
  const pctEst      = cat.budget > 0 ? Math.min((cat.spent_estimated / cat.budget) * 100, Math.max(0, 100 - pctVerified)) : 0
  const over        = pct > 100
  const ok          = pct < 80

  return (
    <div
      onClick={onClick}
      style={{
        background: 'var(--bg-elevated)', border: '1px solid var(--border)',
        borderRadius: 10, cursor: 'pointer', transition: 'border-color 120ms',
      }}
      onMouseEnter={e => e.currentTarget.style.borderColor = 'var(--border-strong)'}
      onMouseLeave={e => e.currentTarget.style.borderColor = 'var(--border)'}
    >
      <div style={{ padding: '14px 18px', display: 'grid', gap: 9 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 9 }}>
            <span style={{ width: 10, height: 10, borderRadius: 3, background: cat.color }}/>
            <span style={{ fontWeight: 600, color: 'var(--text)' }}>{cat.name}</span>
          </div>
          {over ? <Pill tone="negative">Over by {formatCurrency(totalSpent - cat.budget)}</Pill>
            : ok  ? <Pill tone="positive">On track</Pill>
            : <Pill tone="warning">{Math.round(pct)}% used</Pill>}
        </div>

        <div style={{ display: 'flex', alignItems: 'baseline', gap: 6 }}>
          <span style={{ fontSize: 22, fontWeight: 700, color: 'var(--text)', fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.01em' }}>
            {formatCurrency(totalSpent)}
          </span>
          <span style={{ color: 'var(--text-faint)', fontSize: 13 }}>of {formatCurrency(cat.budget)}</span>
        </div>

        <div style={{ height: 6, borderRadius: 3, background: 'var(--bg-input)', overflow: 'hidden', position: 'relative', display: 'flex' }}>
          {pctVerified > 0 && (
            <div style={{ width: `${pctVerified}%`, height: '100%', background: over ? 'var(--negative)' : cat.color }}/>
          )}
          {pctEst > 0 && (
            <div style={{ width: `${pctEst}%`, height: '100%', background: over ? 'var(--negative)' : cat.color, opacity: 0.4 }}/>
          )}
          {over && (
            <div style={{
              position: 'absolute', right: 0, top: 0, bottom: 0,
              width: `${Math.min(pct - 100, 30)}%`,
              background: 'var(--negative)', opacity: 0.4,
            }}/>
          )}
        </div>

        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-faint)' }}>
          <span>{Math.round(pct)}% used · {daysLeft} days left</span>
          <span style={{ fontVariantNumeric: 'tabular-nums' }}>{formatCurrency(Math.max(cat.budget - totalSpent, 0))} remaining</span>
        </div>
      </div>
    </div>
  )
}

// ─── Page shell ──────────────────────────────────────────────────────────────

export default function Budgets() {
  const { formatCurrency } = useCurrency()
  const { isMobile } = useBreakpoint()

  const [period, setPeriod] = useState(currentPeriod)

  const [data,    setData]    = useState(null)
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [editing, setEditing] = useState(null)

  async function fetchBudgets(p) {
    const { year, month } = parsePeriod(p)
    const r = await client.get('/budgets/summary', { params: { year, month } })
    return transformSummary(p, r.data)
  }

  useEffect(() => {
    let ignore = false
    setLoading(true)
    fetchBudgets(period)
      .then(d => { if (!ignore) setData(d) })
      .catch(e => { if (!ignore) setError(e.message) })
      .finally(() => { if (!ignore) setLoading(false) })
    return () => { ignore = true }
  }, [period])

  const totals = useMemo(() => {
    if (!data) return null
    const cats        = data.categories
    const spent       = cats.reduce((a, c) => a + c.spent_verified + c.spent_estimated, 0)
    const budget      = cats.reduce((a, c) => a + c.budget, 0)
    const { daysElapsed, daysLeft, daysInMonth } = periodDays(period)
    const dailyAvg    = daysElapsed > 0 ? spent / daysElapsed : 0
    const remaining   = Math.max(budget - spent, 0)
    const safeToSpend = daysLeft > 0 ? remaining / daysLeft : 0
    const projected   = daysElapsed > 0 ? (spent / daysElapsed) * daysInMonth : 0
    return { spent, budget, dailyAvg, safeToSpend, projected, daysLeft }
  }, [data, period])

  const primaryInsight = useMemo(() => pickInsight(data), [data])

  if (loading) return <div style={{ padding: 32, color: 'var(--text-faint)' }}>Loading…</div>
  if (error)   return <div style={{ padding: 32, color: 'var(--negative)' }}>Error: {error}</div>
  if (!data)   return null

  return (
    <>
      <PageHeader
        title="Budgets"
        subtitle={<>
          {(() => { const { year, month } = parsePeriod(period); return `${MONTH_NAMES[month - 1]} ${year}` })()}
          {totals.daysLeft != null && <> · {totals.daysLeft} days left</>}
        </>}
        isMobile={isMobile}
        actions={<>
          <MonthPicker period={period} onChange={setPeriod}/>
          <Button variant="primary" onClick={() => setEditing('new')}>+ New budget</Button>
        </>}
      />

      <div style={isMobile
        ? { display: 'grid', gap: 22, padding: '0 0 24px', minWidth: 0 }
        : { display: 'grid', gap: 22 }
      }>
        <SummaryCard
          totals={totals}
          insight={primaryInsight}
          onApplyInsight={() => {}}
        />

        <div style={{ display: 'grid', gridTemplateColumns: isMobile ? '1fr' : 'repeat(2, 1fr)', gap: 14 }}>
          {data.categories.map(cat => (
            <CategoryCard
              key={cat.id}
              cat={cat}
              daysLeft={totals.daysLeft}
              onClick={() => setEditing(cat)}
            />
          ))}
        </div>
      </div>

      {editing && (
        <Modal
          title={editing === 'new' ? 'New budget' : `Edit · ${editing.name}`}
          onClose={() => setEditing(null)}
        >
          <BudgetForm
            initial={editing === 'new' ? null : editing}
            period={period}
            onSave={async (payload) => {
              if (editing === 'new') await client.post('/budgets', { ...payload, start_date: payload.start_date || `${period}-01` })
              else                   await client.patch(`/budgets/${editing.id}`, payload)
              const d = await fetchBudgets(period)
              setData(d)
              setEditing(null)
            }}
            onCancel={() => setEditing(null)}
          />
        </Modal>
      )}
    </>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function prevPeriod(period) {
  const { year: y, month: m } = parsePeriod(period)
  if (m === 1) return `${y - 1}-12`
  return `${y}-${String(m - 1).padStart(2, '0')}`
}

function nextPeriod(period) {
  const { year: y, month: m } = parsePeriod(period)
  if (m === 12) return `${y + 1}-01`
  return `${y}-${String(m + 1).padStart(2, '0')}`
}

function periodDays(period) {
  const { year: y, month: m } = parsePeriod(period)
  const daysInMonth  = new Date(y, m, 0).getDate()
  const now          = new Date()
  const isCurrent    = now.getFullYear() === y && now.getMonth() === m - 1
  const daysElapsed  = isCurrent ? now.getDate() : daysInMonth
  const daysLeft     = isCurrent ? Math.max(daysInMonth - daysElapsed, 0) : 0
  return { daysInMonth, daysElapsed, daysLeft }
}

function pickInsight(data) {
  if (!data?.insights?.length) return null
  return [...data.insights].sort((a, b) => (b.priority ?? 0) - (a.priority ?? 0))[0]
}
