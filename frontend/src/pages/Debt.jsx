import { useEffect, useState, useCallback } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'

// ─── Constants ────────────────────────────────────────────────────────────────

const DEBT_TYPES = {
  credit_card:   { label: 'Credit Card',       color: '#FF79C6' },  // pink
  personal_loan: { label: 'Personal Loan',      color: '#FFB86C' },  // orange
  car_loan:      { label: 'Car Loan',           color: '#8BE9FD' },  // cyan
  mortgage:      { label: 'Mortgage',           color: '#6272A4' },  // muted
  bnpl:          { label: 'Buy Now Pay Later',  color: '#50FA7B' },  // green
  other:         { label: 'Other',              color: '#6272A4' },  // muted
}

const STRATEGIES = {
  avalanche: 'Avalanche (highest interest first)',
  snowball:  'Snowball (lowest balance first)',
  fixed:     'Fixed payment',
}

const INTEREST_EXPIRY_WARN_DAYS  = 90   // pink warning
const INTEREST_EXPIRY_CAUTION_DAYS = 180 // orange caution

// ─── Status / colour helpers ──────────────────────────────────────────────────

function daysUntil(dateStr) {
  if (!dateStr) return null
  return Math.floor((new Date(dateStr) - new Date()) / (1000 * 60 * 60 * 24))
}

/**
 * Returns a status key that drives colour + badge logic.
 * Priority: paid_off → expired → expiring → caution → (interest-rate bands)
 */
function debtStatus(debt) {
  if (debt.is_paid_off) return 'paid_off'

  const days = daysUntil(debt.interest_free_end_date)
  if (days !== null) {
    if (days < 0)                           return 'if_expired'
    if (days <= INTEREST_EXPIRY_WARN_DAYS)  return 'if_expiring'
    if (days <= INTEREST_EXPIRY_CAUTION_DAYS) return 'if_caution'
  }

  const rate = debt.interest_rate ?? 0
  if (rate >= 15) return 'high_interest'
  if (rate >= 5)  return 'med_interest'
  return 'low_interest'
}

function statusColor(s) {
  if (s === 'paid_off')      return '#8BE9FD'  // cyan
  if (s === 'if_expired')    return '#FF5555'  // red
  if (s === 'if_expiring')   return '#FF79C6'  // pink
  if (s === 'if_caution')    return '#FFB86C'  // orange
  if (s === 'high_interest') return '#FF79C6'  // pink
  if (s === 'med_interest')  return '#FFB86C'  // orange
  return '#6272A4'                             // muted
}

// ─── Payoff projection ────────────────────────────────────────────────────────

/**
 * Standard amortization. Returns projected payoff Date or null.
 * If an interest-free period is still active, uses 0% until that date
 * then the stated rate thereafter (two-phase calculation).
 */
function projectedPayoff(debt) {
  if (!debt.minimum_payment || debt.minimum_payment <= 0) return null
  if (debt.current_balance <= 0) return null

  const payment = debt.minimum_payment
  let balance   = debt.current_balance
  const today   = new Date()

  // Determine effective rate considering interest-free period
  const days = daysUntil(debt.interest_free_end_date)
  const isInterestFreeNow = days !== null && days >= 0
  const annualRate = debt.interest_rate ?? 0

  if (isInterestFreeNow) {
    // Phase 1: 0% until expiry date
    const monthsFree = days / 30.44
    const balanceAfterFree = Math.max(0, balance - payment * monthsFree)
    if (balanceAfterFree <= 0) {
      // Paid off before expiry
      const monthsNeeded = Math.ceil(balance / payment)
      const d = new Date(today)
      d.setDate(d.getDate() + Math.ceil(monthsNeeded * 30.44))
      return d
    }
    // Phase 2: standard rate on remaining balance
    if (annualRate <= 0) {
      const totalMonths = monthsFree + Math.ceil(balanceAfterFree / payment)
      const d = new Date(today)
      d.setDate(d.getDate() + Math.ceil(totalMonths * 30.44))
      return d
    }
    const r = annualRate / 100 / 12
    if (payment <= r * balanceAfterFree) return null  // interest exceeds payment
    const phase2Months = -Math.log(1 - (r * balanceAfterFree) / payment) / Math.log(1 + r)
    const totalMonths = monthsFree + phase2Months
    const d = new Date(today)
    d.setDate(d.getDate() + Math.ceil(totalMonths * 30.44))
    return d
  }

  // No interest-free period — standard calculation
  if (annualRate <= 0) {
    const months = Math.ceil(balance / payment)
    const d = new Date(today)
    d.setDate(d.getDate() + Math.ceil(months * 30.44))
    return d
  }

  const r = annualRate / 100 / 12
  if (payment <= r * balance) return null  // payment doesn't cover interest
  const months = -Math.log(1 - (r * balance) / payment) / Math.log(1 + r)
  const d = new Date(today)
  d.setDate(d.getDate() + Math.ceil(months * 30.44))
  return d
}

// ─── Formatters ───────────────────────────────────────────────────────────────

function formatCurrency(n) {
  return new Intl.NumberFormat('en-US', {
    style: 'currency', currency: 'USD', minimumFractionDigits: 2,
  }).format(n ?? 0)
}

function formatDate(d) {
  if (!d) return null
  return new Date(d).toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

function ordinal(n) {
  if (!n) return null
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] || s[v] || s[0])
}

// ─── Interest-free warning badge ─────────────────────────────────────────────

function InterestFreeWarning({ debt }) {
  const days = daysUntil(debt.interest_free_end_date)
  if (days === null) return null

  if (days < 0) {
    return (
      <span style={{ ...badgeStyle, color: 'var(--red)', background: '#FF555518' }}>
        ⚠ Interest-free expired {formatDate(debt.interest_free_end_date)}
      </span>
    )
  }
  if (days <= INTEREST_EXPIRY_WARN_DAYS) {
    return (
      <span style={{ ...badgeStyle, color: 'var(--pink)', background: '#FF79C618' }}>
        ⚠ 0% expires in {days}d · {formatDate(debt.interest_free_end_date)}
      </span>
    )
  }
  if (days <= INTEREST_EXPIRY_CAUTION_DAYS) {
    return (
      <span style={{ ...badgeStyle, color: 'var(--orange)', background: '#FFB86C18' }}>
        ⏳ 0% until {formatDate(debt.interest_free_end_date)}
      </span>
    )
  }
  // Still comfortably far away — show quietly
  return (
    <span style={{ ...badgeStyle, color: 'var(--muted)', background: 'var(--border)' }}>
      0% until {formatDate(debt.interest_free_end_date)}
    </span>
  )
}

const badgeStyle = {
  fontSize: 11, fontWeight: 600, padding: '2px 8px',
  borderRadius: 99, whiteSpace: 'nowrap',
}

// ─── Progress bar ─────────────────────────────────────────────────────────────

function DebtProgressBar({ debt, status }) {
  const paidOff = debt.original_amount > 0
    ? Math.min(100, Math.max(0, ((debt.original_amount - debt.current_balance) / debt.original_amount) * 100))
    : 0
  const barColor = debt.is_paid_off ? 'var(--cyan)' : statusColor(status)

  return (
    <div style={bar.track}>
      {/* Remaining balance — fills from right, shown as background */}
      {/* Paid portion — fills from left */}
      <div style={{ ...bar.paid, width: paidOff + '%', background: debt.is_paid_off ? 'var(--cyan)' : 'var(--green)' }} />
    </div>
  )
}

const bar = {
  track: {
    position: 'relative', height: 8, borderRadius: 4,
    background: 'var(--border)', overflow: 'hidden', margin: '14px 0 10px',
  },
  paid: {
    position: 'absolute', top: 0, left: 0, height: '100%',
    borderRadius: 4, transition: 'width 0.4s ease',
  },
}

// ─── Debt card ────────────────────────────────────────────────────────────────

function DebtCard({ debt, isOwner, onEdit, onDelete, onPayment }) {
  const status    = debtStatus(debt)
  const color     = statusColor(status)
  const payoff    = projectedPayoff(debt)
  const typeInfo  = DEBT_TYPES[debt.debt_type] ?? { label: debt.debt_type ?? 'Debt', color: 'var(--muted)' }
  const paidPct   = debt.original_amount > 0
    ? Math.min(100, ((debt.original_amount - debt.current_balance) / debt.original_amount) * 100)
    : 0

  return (
    <div style={{ ...styles.card, borderTop: `3px solid ${color}` }}>
      {/* Header */}
      <div style={styles.cardHeader}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={styles.cardName}>{debt.name}</p>
          <div style={styles.cardMeta}>
            {debt.debt_type && (
              <span style={{ ...badgeStyle, color: typeInfo.color, background: typeInfo.color + '18' }}>
                {typeInfo.label}
              </span>
            )}
            {debt.creditor && (
              <span style={{ fontSize: 12, color: 'var(--muted)' }}>{debt.creditor}</span>
            )}
            {debt.paydown_strategy && (
              <span style={{ ...badgeStyle, color: '#8BE9FD', background: '#8BE9FD12' }}>
                {STRATEGIES[debt.paydown_strategy] ?? debt.paydown_strategy}
              </span>
            )}
          </div>
          {debt.interest_free_end_date && (
            <div style={{ marginTop: 4 }}>
              <InterestFreeWarning debt={debt} />
            </div>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4, flexShrink: 0 }}>
          {isOwner && !debt.is_paid_off && (
            <button style={styles.iconBtn} onClick={onEdit} title="Edit">✎</button>
          )}
          {isOwner && (
            <button style={{ ...styles.iconBtn, color: 'var(--red)' }} onClick={onDelete} title="Delete">✕</button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <DebtProgressBar debt={debt} status={status} />
      <div style={styles.pctRow}>
        <span style={{ fontSize: 11, color: 'var(--green)' }}>{paidPct.toFixed(1)}% paid off</span>
        <span style={{ fontSize: 11, color: 'var(--muted)' }}>{formatCurrency(debt.original_amount)} original</span>
      </div>

      {/* Stats grid */}
      <div style={styles.statsGrid}>
        <StatCell label="Current balance" value={formatCurrency(debt.current_balance)} color={color} large />
        <StatCell label="Interest rate"
          value={
            debt.interest_free_end_date && (daysUntil(debt.interest_free_end_date) ?? -1) >= 0
              ? `0% (${debt.interest_rate ?? 0}% after)`
              : `${debt.interest_rate ?? 0}%`
          }
          color={debt.interest_rate > 0 ? color : 'var(--green)'}
        />
        <StatCell label="Min. payment"
          value={debt.minimum_payment ? formatCurrency(debt.minimum_payment) + '/mo' : '—'}
        />
        <StatCell label="Due day"
          value={debt.due_day ? `${ordinal(debt.due_day)} of month` : '—'}
        />
      </div>

      {/* Projection row */}
      <div style={styles.projRow}>
        {debt.linked_account && (
          <div style={styles.projCell}>
            <span style={styles.projLabel}>Linked account</span>
            <span style={{ ...styles.projValue, color: 'var(--cyan)' }}>
              ⬡ {debt.linked_account.name}
            </span>
          </div>
        )}
        <div style={styles.projCell}>
          <span style={styles.projLabel}>Projected payoff</span>
          <span style={{ ...styles.projValue, color: payoff ? 'var(--white)' : 'var(--muted)' }}>
            {debt.is_paid_off
              ? <span style={{ color: 'var(--cyan)' }}>✓ Paid off</span>
              : payoff
                ? formatDate(payoff)
                : debt.minimum_payment
                  ? <span style={{ color: 'var(--pink)' }}>Payment covers interest only</span>
                  : 'Set min. payment to project'}
          </span>
        </div>
        {debt.notes && (
          <div style={{ ...styles.projCell, gridColumn: '1 / -1' }}>
            <span style={styles.projLabel}>Notes</span>
            <span style={{ fontSize: 12, color: 'var(--muted)' }}>{debt.notes}</span>
          </div>
        )}
      </div>

      {/* Log payment button */}
      {isOwner && !debt.is_paid_off && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
          <Button
            variant="secondary" size="sm" onClick={onPayment}
            style={{ width: '100%', justifyContent: 'center' }}
          >
            + Log payment
          </Button>
        </div>
      )}
    </div>
  )
}

function StatCell({ label, value, color, large }) {
  return (
    <div style={styles.statCell}>
      <span style={styles.statLabel}>{label}</span>
      <span style={{ fontSize: large ? 17 : 13, fontWeight: 700, color: color ?? 'var(--white)' }}>{value}</span>
    </div>
  )
}

// ─── Debt form ────────────────────────────────────────────────────────────────

function DebtForm({ initial, accounts, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    name:                   initial?.name                   ?? '',
    creditor:               initial?.creditor               ?? '',
    debt_type:              initial?.debt_type              ?? '',
    original_amount:        initial?.original_amount        ?? '',
    current_balance:        initial?.current_balance        ?? '',
    interest_rate:          initial?.interest_rate          ?? '',
    interest_free_end_date: initial?.interest_free_end_date ?? '',
    minimum_payment:        initial?.minimum_payment        ?? '',
    due_day:                initial?.due_day                ?? '',
    paydown_strategy:       initial?.paydown_strategy       ?? '',
    linked_account_id:      initial?.linked_account_id      ?? '',
    notes:                  initial?.notes                  ?? '',
  })
  const [error, setError] = useState('')

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    const original = parseFloat(form.original_amount)
    const current  = parseFloat(form.current_balance)
    if (isNaN(original) || original <= 0) { setError('Enter a positive original amount'); return }
    if (isNaN(current)  || current  < 0)  { setError('Current balance cannot be negative'); return }
    setError('')
    onSave({
      name:                   form.name,
      creditor:               form.creditor               || null,
      debt_type:              form.debt_type              || null,
      original_amount:        original,
      current_balance:        current,
      interest_rate:          form.interest_rate          ? parseFloat(form.interest_rate) : null,
      interest_free_end_date: form.interest_free_end_date || null,
      minimum_payment:        form.minimum_payment        ? parseFloat(form.minimum_payment) : null,
      due_day:                form.due_day                ? parseInt(form.due_day) : null,
      paydown_strategy:       form.paydown_strategy       || null,
      linked_account_id:      form.linked_account_id      ? parseInt(form.linked_account_id) : null,
      notes:                  form.notes                  || null,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Debt name *" style={{ gridColumn: '1 / -1' }}>
          <input style={inputStyle} value={form.name} onChange={set('name')} required autoFocus placeholder="e.g. Virgin Money BT" />
        </FormField>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Type">
          <select style={selectStyle} value={form.debt_type} onChange={set('debt_type')}>
            <option value="">Select type…</option>
            {Object.entries(DEBT_TYPES).map(([k, v]) => (
              <option key={k} value={k}>{v.label}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Lender / Creditor">
          <input style={inputStyle} value={form.creditor} onChange={set('creditor')} placeholder="e.g. Virgin Money" />
        </FormField>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Original amount *">
          <input style={inputStyle} type="number" step="0.01" min="0.01" value={form.original_amount} onChange={set('original_amount')} required inputMode="decimal" />
        </FormField>
        <FormField label="Current balance *">
          <input style={inputStyle} type="number" step="0.01" min="0" value={form.current_balance} onChange={set('current_balance')} required inputMode="decimal" />
        </FormField>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Interest rate (%)" hint="Annual rate. 0 for interest-free.">
          <input style={inputStyle} type="number" step="0.01" min="0" max="100" value={form.interest_rate} onChange={set('interest_rate')} inputMode="decimal" placeholder="e.g. 19.99" />
        </FormField>
        <FormField label="Interest-free end date" hint="For 0% BT cards and BNPL">
          <input style={inputStyle} type="date" value={form.interest_free_end_date} onChange={set('interest_free_end_date')} />
        </FormField>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Minimum payment ($/mo)">
          <input style={inputStyle} type="number" step="0.01" min="0" value={form.minimum_payment} onChange={set('minimum_payment')} inputMode="decimal" />
        </FormField>
        <FormField label="Payment due day" hint="Day of month (1–31)">
          <input style={inputStyle} type="number" min="1" max="31" value={form.due_day} onChange={set('due_day')} inputMode="numeric" placeholder="e.g. 15" />
        </FormField>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Paydown strategy">
          <select style={selectStyle} value={form.paydown_strategy} onChange={set('paydown_strategy')}>
            <option value="">None / unset</option>
            {Object.entries(STRATEGIES).map(([k, v]) => (
              <option key={k} value={k}>{v}</option>
            ))}
          </select>
        </FormField>
        <FormField label="Link to account">
          <select style={selectStyle} value={form.linked_account_id} onChange={set('linked_account_id')}>
            <option value="">No linked account</option>
            {accounts.map((a) => (
              <option key={a.id} value={a.id}>{a.name}{a.institution ? ` · ${a.institution}` : ''}</option>
            ))}
          </select>
        </FormField>
      </div>

      <FormField label="Notes">
        <textarea style={{ ...inputStyle, resize: 'vertical', minHeight: 60 }} value={form.notes} onChange={set('notes')} />
      </FormField>

      {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : initial ? 'Save changes' : 'Add debt'}</Button>
      </div>
    </form>
  )
}

// ─── Payment form ─────────────────────────────────────────────────────────────

function PaymentForm({ debt, onSave, onCancel, saving }) {
  const [amount, setAmount] = useState(debt.minimum_payment ? String(debt.minimum_payment) : '')
  const [error, setError]   = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    const val = parseFloat(amount)
    if (isNaN(val) || val <= 0) { setError('Enter a positive amount'); return }
    setError('')
    onSave(val)
  }

  return (
    <form onSubmit={handleSubmit}>
      <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 16 }}>
        Payment toward <strong style={{ color: 'var(--white)' }}>{debt.name}</strong>
        <br />
        Current balance: <strong style={{ color: 'var(--pink)' }}>{formatCurrency(debt.current_balance)}</strong>
        {debt.minimum_payment && (
          <> · Minimum: <strong style={{ color: 'var(--white)' }}>{formatCurrency(debt.minimum_payment)}</strong></>
        )}
      </p>

      <FormField label="Payment amount *">
        <input
          style={inputStyle} type="number" step="0.01" min="0.01"
          value={amount} onChange={(e) => setAmount(e.target.value)}
          required autoFocus inputMode="decimal"
        />
      </FormField>

      {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Log payment'}</Button>
      </div>
    </form>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Debt() {
  const { isOwner } = useAuth()

  const [debts, setDebts]       = useState([])
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')

  const [showAdd, setShowAdd]     = useState(false)
  const [editing, setEditing]     = useState(null)
  const [deleting, setDeleting]   = useState(null)
  const [paying, setPaying]       = useState(null)
  const [saving, setSaving]       = useState(false)
  const [actionError, setActionError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    client.get('/debt')
      .then((r) => setDebts(r.data))
      .catch(() => setError('Failed to load debts'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    client.get('/accounts').then((r) => setAccounts(r.data))
  }, [load])

  const activeDebts    = debts.filter((d) => !d.is_paid_off)
  const paidOffDebts   = debts.filter((d) => d.is_paid_off)
  const totalDebt      = activeDebts.reduce((s, d) => s + d.current_balance, 0)
  const totalMinimums  = activeDebts.reduce((s, d) => s + (d.minimum_payment ?? 0), 0)
  const expiringCount  = activeDebts.filter((d) => {
    const days = daysUntil(d.interest_free_end_date)
    return days !== null && days >= 0 && days <= INTEREST_EXPIRY_WARN_DAYS
  }).length

  // Weighted average interest rate (only debts with a stated rate)
  const ratedDebts = activeDebts.filter((d) => d.interest_rate != null && d.current_balance > 0)
  const weightedRate = ratedDebts.length > 0
    ? ratedDebts.reduce((s, d) => s + d.interest_rate * d.current_balance, 0) /
      ratedDebts.reduce((s, d) => s + d.current_balance, 0)
    : 0

  async function handleAdd(form) {
    setSaving(true); setActionError('')
    try {
      await client.post('/debt', form)
      setShowAdd(false); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to add debt')
    } finally { setSaving(false) }
  }

  async function handleEdit(form) {
    setSaving(true); setActionError('')
    try {
      await client.patch(`/debt/${editing.id}`, form)
      setEditing(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to update debt')
    } finally { setSaving(false) }
  }

  async function handleDelete() {
    setSaving(true)
    try {
      await client.delete(`/debt/${deleting.id}`)
      setDeleting(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to delete debt')
    } finally { setSaving(false) }
  }

  async function handlePayment(amount) {
    setSaving(true); setActionError('')
    try {
      await client.post(`/debt/${paying.id}/payment`, { amount })
      setPaying(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to log payment')
    } finally { setSaving(false) }
  }

  return (
    <div>
      {/* Header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.pageTitle}>Debt Tracker</h1>
          {debts.length > 0 && (
            <p style={styles.pageSubtitle}>
              {activeDebts.length} active · {paidOffDebts.length} paid off
              {expiringCount > 0 && (
                <span style={{ color: 'var(--pink)', marginLeft: 12 }}>
                  ⚠ {expiringCount} interest-free period{expiringCount !== 1 ? 's' : ''} expiring soon
                </span>
              )}
            </p>
          )}
        </div>
        {isOwner && (
          <Button onClick={() => { setShowAdd(true); setActionError('') }}>
            + Add debt
          </Button>
        )}
      </div>

      {/* Summary strip */}
      {activeDebts.length > 0 && (
        <div style={styles.totalsBar}>
          <TotalChip label="Total debt"     value={formatCurrency(totalDebt)}                      color="var(--pink)"   />
          <TotalChip label="Min. payments"  value={formatCurrency(totalMinimums) + '/mo'}           color="var(--orange)" />
          <TotalChip label="Avg. rate"      value={`${weightedRate.toFixed(2)}% p.a.`}             color={weightedRate >= 10 ? 'var(--pink)' : weightedRate > 0 ? 'var(--orange)' : 'var(--green)'} />
          <TotalChip label="Active debts"   value={activeDebts.length}                              color="var(--muted)"  />
        </div>
      )}

      {error && <p style={{ color: 'var(--red)', marginBottom: 16 }}>{error}</p>}

      {loading ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : debts.length === 0 ? (
        <div style={styles.empty}>
          <p style={styles.emptyTitle}>No debts tracked</p>
          {isOwner && (
            <>
              <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 20 }}>
                Add credit cards, loans, or BNPL balances to track paydown progress.
              </p>
              <Button onClick={() => { setShowAdd(true); setActionError('') }}>+ Add first debt</Button>
            </>
          )}
        </div>
      ) : (
        <>
          {activeDebts.length > 0 && (
            <div style={styles.grid}>
              {activeDebts.map((d) => (
                <DebtCard
                  key={d.id}
                  debt={d}
                  isOwner={isOwner}
                  onEdit={() => { setEditing(d); setActionError('') }}
                  onDelete={() => { setDeleting(d); setActionError('') }}
                  onPayment={() => { setPaying(d); setActionError('') }}
                />
              ))}
            </div>
          )}

          {paidOffDebts.length > 0 && (
            <>
              <h2 style={styles.sectionHeader}>Paid off</h2>
              <div style={styles.grid}>
                {paidOffDebts.map((d) => (
                  <DebtCard
                    key={d.id}
                    debt={d}
                    isOwner={isOwner}
                    onEdit={() => {}}
                    onDelete={() => { setDeleting(d); setActionError('') }}
                    onPayment={() => {}}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* Modals */}
      {showAdd && (
        <Modal title="Add debt" onClose={() => setShowAdd(false)} width={560}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <DebtForm accounts={accounts} onSave={handleAdd} onCancel={() => setShowAdd(false)} saving={saving} />
        </Modal>
      )}

      {editing && (
        <Modal title={`Edit — ${editing.name}`} onClose={() => setEditing(null)} width={560}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <DebtForm initial={editing} accounts={accounts} onSave={handleEdit} onCancel={() => setEditing(null)} saving={saving} />
        </Modal>
      )}

      {paying && (
        <Modal title="Log payment" onClose={() => setPaying(null)} width={400}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <PaymentForm debt={paying} onSave={handlePayment} onCancel={() => setPaying(null)} saving={saving} />
        </Modal>
      )}

      {deleting && (
        <Modal title="Delete debt?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            <strong>{deleting.name}</strong> will be permanently removed.
          </p>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Deleting…' : 'Delete debt'}
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

const styles = {
  pageHeader: {
    display: 'flex', alignItems: 'flex-start',
    justifyContent: 'space-between', marginBottom: 20,
    flexWrap: 'wrap', gap: 12,
  },
  pageTitle:    { fontSize: 24, fontWeight: 700, color: 'var(--white)' },
  pageSubtitle: { color: 'var(--muted)', fontSize: 14, marginTop: 4 },
  totalsBar: {
    display: 'flex', flexWrap: 'wrap', gap: 2, marginBottom: 24,
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', overflow: 'hidden',
  },
  chip: {
    flex: '1 1 120px', display: 'flex', flexDirection: 'column',
    gap: 3, padding: '12px 16px', borderRight: '1px solid var(--border)',
  },
  chipLabel: {
    fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
    letterSpacing: '0.05em', color: 'var(--muted)',
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))',
    gap: 16, marginBottom: 24,
  },
  card: {
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', padding: '18px 20px',
  },
  cardHeader: {
    display: 'flex', justifyContent: 'space-between',
    alignItems: 'flex-start', gap: 8,
  },
  cardName: { fontSize: 16, fontWeight: 600, color: 'var(--white)', marginBottom: 4 },
  cardMeta: { display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center' },
  statsGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 8, marginBottom: 12,
  },
  statCell:  { display: 'flex', flexDirection: 'column', gap: 3 },
  statLabel: { fontSize: 11, color: 'var(--muted)', fontWeight: 500 },
  pctRow: {
    display: 'flex', justifyContent: 'space-between',
    marginBottom: 12, marginTop: -6,
  },
  projRow: {
    display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))',
    gap: 8, paddingTop: 10, borderTop: '1px solid var(--border)',
  },
  projCell:  { display: 'flex', flexDirection: 'column', gap: 3 },
  projLabel: { fontSize: 11, color: 'var(--muted)', fontWeight: 500 },
  projValue: { fontSize: 13, fontWeight: 600, color: 'var(--white)' },
  iconBtn: {
    background: 'none', border: 'none', color: 'var(--muted)',
    fontSize: 15, padding: '3px 5px', borderRadius: 'var(--radius)', cursor: 'pointer',
  },
  sectionHeader: {
    fontSize: 14, fontWeight: 600, color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid var(--border)',
  },
  empty: { textAlign: 'center', padding: '60px 0' },
  emptyTitle: { fontSize: 18, fontWeight: 600, color: 'var(--white)', marginBottom: 8 },
  modalError: { color: 'var(--red)', fontSize: 13, marginBottom: 12 },
}
