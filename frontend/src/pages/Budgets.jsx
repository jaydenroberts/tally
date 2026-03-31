import { useEffect, useState, useCallback } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'

const MONTH_NAMES = [
  'January','February','March','April','May','June',
  'July','August','September','October','November','December',
]

// ─── Colour helpers ───────────────────────────────────────────────────────────

function statusColor(status) {
  if (status === 'over')    return '#FF79C6'  // pink
  if (status === 'warning') return '#FFB86C'  // orange
  return '#50FA7B'                            // green
}

function StatusBadge({ status, pct }) {
  const label = status === 'over' ? 'Over budget' : status === 'warning' ? 'Warning' : 'Healthy'
  return (
    <span style={{
      fontSize: 11,
      fontWeight: 600,
      padding: '2px 8px',
      borderRadius: 99,
      background: statusColor(status) + '20',
      color: statusColor(status),
      whiteSpace: 'nowrap',
    }}>
      {label} · {pct}%
    </span>
  )
}

// ─── Dual-segment progress bar ────────────────────────────────────────────────
// Left segment  = verified spend (solid)
// Right segment = estimated spend (40% opacity)
// Together they represent total spend; colour determined by total %

function ProgressBar({ pctVerified, pctEstimated, status }) {
  const color   = statusColor(status)
  const vWidth  = Math.min(pctVerified, 100)
  const eWidth  = Math.min(pctEstimated, Math.max(0, 100 - vWidth))
  const hasEst  = eWidth > 0.2

  return (
    <div style={bar.track}>
      {vWidth > 0 && (
        <div style={{
          ...bar.segment,
          width: vWidth + '%',
          background: color,
          borderRadius: hasEst ? '4px 0 0 4px' : '4px',
        }} />
      )}
      {hasEst && (
        <div style={{
          ...bar.segment,
          left: vWidth + '%',
          width: eWidth + '%',
          background: color,
          opacity: 0.38,
          borderRadius: vWidth > 0 ? '0 4px 4px 0' : '4px',
        }} />
      )}
    </div>
  )
}

const bar = {
  track: {
    position: 'relative',
    height: 8,
    borderRadius: 4,
    background: 'var(--border)',
    overflow: 'hidden',
    margin: '12px 0',
  },
  segment: {
    position: 'absolute',
    top: 0,
    height: '100%',
  },
}

// ─── Budget card ─────────────────────────────────────────────────────────────

function BudgetCard({ item, isOwner, onEdit, onDelete }) {
  const { budget, verified_spend, estimated_spend, total_spend, remaining, pct_total, pct_verified, pct_estimated, status } = item
  const color = statusColor(status)

  return (
    <div style={{ ...styles.card, borderLeft: `4px solid ${color}` }}>
      <div style={styles.cardHeader}>
        <div>
          <p style={styles.cardCategory}>{budget.category?.name ?? 'Uncategorised'}</p>
          <p style={styles.cardBudgetAmount}>{formatCurrency(budget.amount)} / {budget.period}</p>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <StatusBadge status={status} pct={pct_total} />
          {isOwner && (
            <>
              <button style={styles.iconBtn} onClick={onEdit} title="Edit">✎</button>
              <button style={{ ...styles.iconBtn, color: 'var(--red)' }} onClick={onDelete} title="Delete">✕</button>
            </>
          )}
        </div>
      </div>

      <ProgressBar pctVerified={pct_verified} pctEstimated={pct_estimated} status={status} />

      <div style={styles.spendRow}>
        <div style={styles.spendItem}>
          <span style={styles.spendLabel}>✓ Verified</span>
          <span style={{ color: 'var(--green)', fontWeight: 600 }}>{formatCurrency(verified_spend)}</span>
        </div>
        <div style={styles.spendItem}>
          <span style={styles.spendLabel}>~ Estimated</span>
          <span style={{ color: 'var(--pink)', fontWeight: 600 }}>{formatCurrency(estimated_spend)}</span>
        </div>
        <div style={styles.spendItem}>
          <span style={styles.spendLabel}>Total spent</span>
          <span style={{ color, fontWeight: 700 }}>{formatCurrency(total_spend)}</span>
        </div>
        <div style={styles.spendItem}>
          <span style={styles.spendLabel}>{remaining >= 0 ? 'Remaining' : 'Over by'}</span>
          <span style={{ color: remaining >= 0 ? 'var(--white)' : 'var(--pink)', fontWeight: 600 }}>
            {formatCurrency(Math.abs(remaining))}
          </span>
        </div>
      </div>

      {estimated_spend > 0 && (
        <p style={styles.estimateNote}>
          ~ {formatCurrency(estimated_spend)} of spend is unverified estimates and may change on import.
        </p>
      )}
    </div>
  )
}

// ─── Add / Edit form ─────────────────────────────────────────────────────────

function BudgetForm({ initial, categories, viewDate, onSave, onCancel, saving }) {
  const defaultStart = `${viewDate.year}-${String(viewDate.month).padStart(2, '0')}-01`
  const [form, setForm] = useState({
    category_id: initial?.category_id ?? '',
    amount: initial?.budget?.amount ?? initial?.amount ?? '',
    period: initial?.budget?.period ?? initial?.period ?? 'monthly',
    start_date: initial?.budget?.start_date ?? initial?.start_date ?? defaultStart,
    end_date: initial?.budget?.end_date ?? initial?.end_date ?? '',
  })
  const [error, setError] = useState('')

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!form.category_id) { setError('Select a category'); return }
    const amount = parseFloat(form.amount)
    if (isNaN(amount) || amount <= 0) { setError('Enter a positive budget amount'); return }
    setError('')
    onSave({
      category_id: parseInt(form.category_id),
      amount,
      period: form.period,
      start_date: form.start_date,
      end_date: form.end_date || null,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Category *">
        <select style={selectStyle} value={form.category_id} onChange={set('category_id')} required autoFocus>
          <option value="">Select category…</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Budget amount *">
          <input style={inputStyle} type="number" step="0.01" min="0.01" value={form.amount} onChange={set('amount')} required inputMode="decimal" />
        </FormField>
        <FormField label="Period">
          <select style={selectStyle} value={form.period} onChange={set('period')}>
            <option value="monthly">Monthly</option>
            <option value="weekly">Weekly</option>
            <option value="yearly">Yearly</option>
          </select>
        </FormField>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Start date">
          <input style={inputStyle} type="date" value={form.start_date} onChange={set('start_date')} />
        </FormField>
        <FormField label="End date" hint="Leave blank for ongoing">
          <input style={inputStyle} type="date" value={form.end_date} onChange={set('end_date')} />
        </FormField>
      </div>

      {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : initial ? 'Save changes' : 'Add budget'}</Button>
      </div>
    </form>
  )
}

// ─── Month navigator ─────────────────────────────────────────────────────────

function MonthNav({ viewDate, onChange }) {
  function prev() {
    onChange(viewDate.month === 1
      ? { year: viewDate.year - 1, month: 12 }
      : { year: viewDate.year, month: viewDate.month - 1 }
    )
  }
  function next() {
    const now = new Date()
    const isCurrentMonth = viewDate.year === now.getFullYear() && viewDate.month === now.getMonth() + 1
    if (isCurrentMonth) return   // don't navigate into the future
    onChange(viewDate.month === 12
      ? { year: viewDate.year + 1, month: 1 }
      : { year: viewDate.year, month: viewDate.month + 1 }
    )
  }
  const now = new Date()
  const isCurrent = viewDate.year === now.getFullYear() && viewDate.month === now.getMonth() + 1

  return (
    <div style={styles.monthNav}>
      <button style={styles.navArrow} onClick={prev} title="Previous month">←</button>
      <span style={styles.monthLabel}>
        {MONTH_NAMES[viewDate.month - 1]} {viewDate.year}
        {isCurrent && <span style={styles.currentDot} title="Current month" />}
      </span>
      <button style={{ ...styles.navArrow, opacity: isCurrent ? 0.3 : 1 }} onClick={next} disabled={isCurrent} title="Next month">→</button>
    </div>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Budgets() {
  const { isOwner } = useAuth()
  const now = new Date()

  const [viewDate, setViewDate] = useState({ year: now.getFullYear(), month: now.getMonth() + 1 })
  const [summary, setSummary] = useState([])
  const [categories, setCategories] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState(null)    // BudgetStatus item
  const [deleting, setDeleting] = useState(null)  // BudgetStatus item
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState('')

  const loadSummary = useCallback((vd) => {
    setLoading(true)
    client.get(`/budgets/summary?year=${vd.year}&month=${vd.month}`)
      .then((r) => setSummary(r.data))
      .catch(() => setError('Failed to load budgets'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    client.get('/categories').then((r) => setCategories(r.data))
  }, [])

  useEffect(() => {
    loadSummary(viewDate)
  }, [viewDate, loadSummary])

  // Categories not yet budgeted this month (for add form)
  const budgetedCategoryIds = new Set(summary.map((s) => s.budget.category_id))
  const availableCategories = categories.filter((c) => !budgetedCategoryIds.has(c.id))

  // Totals across all budgets
  const totalBudgeted = summary.reduce((s, i) => s + i.budget.amount, 0)
  const totalSpent    = summary.reduce((s, i) => s + i.total_spend, 0)
  const totalVerified = summary.reduce((s, i) => s + i.verified_spend, 0)
  const totalEstimated = summary.reduce((s, i) => s + i.estimated_spend, 0)

  async function handleAdd(form) {
    setSaving(true)
    setActionError('')
    try {
      await client.post('/budgets', form)
      setShowAdd(false)
      loadSummary(viewDate)
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to create budget')
    } finally {
      setSaving(false)
    }
  }

  async function handleEdit(form) {
    setSaving(true)
    setActionError('')
    try {
      await client.patch(`/budgets/${editing.budget.id}`, form)
      setEditing(null)
      loadSummary(viewDate)
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to update budget')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setSaving(true)
    try {
      await client.delete(`/budgets/${deleting.budget.id}`)
      setDeleting(null)
      loadSummary(viewDate)
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to delete budget')
    } finally {
      setSaving(false)
    }
  }

  const overCount    = summary.filter((s) => s.status === 'over').length
  const warningCount = summary.filter((s) => s.status === 'warning').length

  return (
    <div>
      {/* Header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.pageTitle}>Budgets</h1>
          {summary.length > 0 && (
            <p style={styles.pageSubtitle}>
              {summary.length} budget{summary.length !== 1 ? 's' : ''}
              {overCount > 0 && <span style={{ color: 'var(--pink)', marginLeft: 12 }}>● {overCount} over</span>}
              {warningCount > 0 && <span style={{ color: 'var(--orange)', marginLeft: 8 }}>● {warningCount} warning</span>}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
          <MonthNav viewDate={viewDate} onChange={setViewDate} />
          {isOwner && (
            <Button onClick={() => { setShowAdd(true); setActionError('') }}>
              + Add budget
            </Button>
          )}
        </div>
      </div>

      {/* Summary totals strip */}
      {summary.length > 0 && (
        <div style={styles.totalsBar}>
          <TotalChip label="Total budgeted" value={formatCurrency(totalBudgeted)} color="var(--muted)" />
          <TotalChip label="✓ Verified" value={formatCurrency(totalVerified)} color="var(--green)" />
          <TotalChip label="~ Estimated" value={formatCurrency(totalEstimated)} color="var(--pink)" />
          <TotalChip label="Total spent" value={formatCurrency(totalSpent)} color={totalSpent > totalBudgeted ? 'var(--pink)' : 'var(--white)'} />
          <TotalChip label="Remaining" value={formatCurrency(Math.max(0, totalBudgeted - totalSpent))} color="var(--cyan)" />
        </div>
      )}

      {error && <p style={{ color: 'var(--red)', marginBottom: 16 }}>{error}</p>}

      {loading ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : summary.length === 0 ? (
        <div style={styles.empty}>
          <p style={styles.emptyTitle}>No budgets for {MONTH_NAMES[viewDate.month - 1]}</p>
          {isOwner && (
            <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 20 }}>
              Create a budget to start tracking spending against your plan.
            </p>
          )}
          {isOwner && (
            <Button onClick={() => { setShowAdd(true); setActionError('') }}>+ Add first budget</Button>
          )}
        </div>
      ) : (
        <div style={styles.grid}>
          {summary.map((item) => (
            <BudgetCard
              key={item.budget.id}
              item={item}
              isOwner={isOwner}
              onEdit={() => { setEditing(item); setActionError('') }}
              onDelete={() => { setDeleting(item); setActionError('') }}
            />
          ))}
        </div>
      )}

      {/* Add modal */}
      {showAdd && (
        <Modal title="Add budget" onClose={() => setShowAdd(false)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          {availableCategories.length === 0 ? (
            <p style={{ color: 'var(--muted)' }}>All categories already have a budget for this month.</p>
          ) : (
            <BudgetForm
              categories={availableCategories}
              viewDate={viewDate}
              onSave={handleAdd}
              onCancel={() => setShowAdd(false)}
              saving={saving}
            />
          )}
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title={`Edit — ${editing.budget.category?.name}`} onClose={() => setEditing(null)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <BudgetForm
            initial={editing}
            categories={categories}
            viewDate={viewDate}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={saving}
          />
        </Modal>
      )}

      {/* Delete confirmation */}
      {deleting && (
        <Modal title="Remove budget?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            The <strong>{deleting.budget.category?.name}</strong> budget will be deactivated.
            Transactions are not affected.
          </p>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Removing…' : 'Remove budget'}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function TotalChip({ label, value, color }) {
  return (
    <div style={styles.chip}>
      <span style={styles.chipLabel}>{label}</span>
      <span style={{ fontSize: 15, fontWeight: 700, color }}>{value}</span>
    </div>
  )
}

function formatCurrency(n, currency = 'USD') {
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency, minimumFractionDigits: 2,
  }).format(n)
}

const styles = {
  pageHeader: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 20,
    flexWrap: 'wrap',
    gap: 12,
  },
  pageTitle: { fontSize: 24, fontWeight: 700, color: 'var(--white)' },
  pageSubtitle: { color: 'var(--muted)', fontSize: 14, marginTop: 4 },
  totalsBar: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 2,
    marginBottom: 24,
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    overflow: 'hidden',
  },
  chip: {
    flex: '1 1 120px',
    display: 'flex',
    flexDirection: 'column',
    gap: 3,
    padding: '12px 16px',
    borderRight: '1px solid var(--border)',
  },
  chipLabel: { fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--muted)' },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
    gap: 16,
  },
  card: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: '18px 20px',
  },
  cardHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: 8,
    flexWrap: 'wrap',
  },
  cardCategory: { fontSize: 16, fontWeight: 600, color: 'var(--white)', marginBottom: 2 },
  cardBudgetAmount: { fontSize: 13, color: 'var(--muted)' },
  spendRow: {
    display: 'grid',
    gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 8,
    marginTop: 4,
  },
  spendItem: { display: 'flex', flexDirection: 'column', gap: 3 },
  spendLabel: { fontSize: 11, color: 'var(--muted)', fontWeight: 500 },
  estimateNote: {
    fontSize: 12,
    color: 'var(--muted)',
    marginTop: 10,
    paddingTop: 10,
    borderTop: '1px solid var(--border)',
  },
  iconBtn: {
    background: 'none', border: 'none', color: 'var(--muted)',
    fontSize: 15, padding: '3px 5px', borderRadius: 'var(--radius)', cursor: 'pointer',
  },
  monthNav: {
    display: 'flex',
    alignItems: 'center',
    gap: 10,
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius)',
    padding: '6px 12px',
  },
  navArrow: {
    background: 'none', border: 'none', color: 'var(--cyan)',
    fontSize: 16, cursor: 'pointer', padding: '0 2px', lineHeight: 1,
  },
  monthLabel: {
    fontSize: 14, fontWeight: 600, color: 'var(--white)',
    minWidth: 130, textAlign: 'center',
    display: 'flex', alignItems: 'center', gap: 6, justifyContent: 'center',
  },
  currentDot: {
    display: 'inline-block', width: 6, height: 6,
    borderRadius: '50%', background: 'var(--green)',
  },
  empty: { textAlign: 'center', padding: '60px 0' },
  emptyTitle: { fontSize: 18, fontWeight: 600, color: 'var(--white)', marginBottom: 8 },
  modalError: { color: 'var(--red)', fontSize: 13, marginBottom: 12 },
}
