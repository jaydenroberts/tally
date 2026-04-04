import { useEffect, useState, useCallback } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useCurrency } from '../context/CurrencyContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'

// ─── Constants ────────────────────────────────────────────────────────────────

const FREQUENCIES = [
  { value: 'daily',       label: 'Daily' },
  { value: 'weekly',      label: 'Weekly' },
  { value: 'fortnightly', label: 'Fortnightly' },
  { value: 'monthly',     label: 'Monthly' },
  { value: 'yearly',      label: 'Yearly' },
]

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ rec }) {
  const today = new Date()
  today.setHours(0, 0, 0, 0)
  const nextDue = new Date(rec.next_due)
  const overdue = !rec.is_active ? false : nextDue < today
  const dueToday = !rec.is_active ? false : nextDue.getTime() === today.getTime()

  if (!rec.is_active) {
    return <span style={badge('var(--muted)')}>Inactive</span>
  }
  if (overdue) {
    return <span style={badge('var(--orange)')}>Overdue</span>
  }
  if (dueToday) {
    return <span style={badge('var(--yellow)')}>Due today</span>
  }
  return <span style={badge('var(--green)')}>Active</span>
}

function badge(color) {
  return {
    fontSize: 11, fontWeight: 600, padding: '2px 8px',
    borderRadius: 99, color, background: color + '20',
    whiteSpace: 'nowrap',
  }
}

// ─── Recurring card ───────────────────────────────────────────────────────────

function RecurringCard({ rec, isOwner, onEdit, onDelete }) {
  const { formatCurrency } = useCurrency()
  const amountColor = rec.amount >= 0 ? 'var(--green)' : 'var(--white)'

  return (
    <div style={{ ...styles.card, opacity: rec.is_active ? 1 : 0.6 }}>
      <div style={styles.cardHeader}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={styles.cardName}>{rec.description}</p>
          <p style={styles.cardMeta}>
            {rec.account?.name ?? '—'}
            {rec.category && (
              <span style={{ marginLeft: 8, color: 'var(--cyan)' }}>{rec.category.name}</span>
            )}
          </p>
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'flex-start', flexShrink: 0 }}>
          <StatusBadge rec={rec} />
          {isOwner && (
            <>
              <button style={styles.iconBtn} onClick={onEdit} title="Edit">✎</button>
              <button style={{ ...styles.iconBtn, color: 'var(--red)' }} onClick={onDelete} title="Delete">✕</button>
            </>
          )}
        </div>
      </div>

      <div style={styles.statsRow}>
        <div style={styles.stat}>
          <span style={styles.statLabel}>Amount</span>
          <span style={{ fontSize: 16, fontWeight: 700, color: amountColor }}>
            {formatCurrency(rec.amount)}
          </span>
        </div>
        <div style={styles.stat}>
          <span style={styles.statLabel}>Frequency</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--white)' }}>
            {FREQUENCIES.find((f) => f.value === rec.frequency)?.label ?? rec.frequency}
          </span>
        </div>
        <div style={styles.stat}>
          <span style={styles.statLabel}>Next due</span>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--white)' }}>
            {new Date(rec.next_due).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
          </span>
        </div>
        {rec.end_date && (
          <div style={styles.stat}>
            <span style={styles.statLabel}>Ends</span>
            <span style={{ fontSize: 13, color: 'var(--muted)' }}>
              {new Date(rec.end_date).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
            </span>
          </div>
        )}
      </div>

      {rec.notes && (
        <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 10, borderTop: '1px solid var(--border)', paddingTop: 8 }}>
          {rec.notes}
        </p>
      )}
    </div>
  )
}

// ─── Form ─────────────────────────────────────────────────────────────────────

function RecurringForm({ initial, accounts, categories, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    description:  initial?.description  ?? '',
    amount:       initial?.amount       ?? '',
    account_id:   initial?.account_id   ?? (accounts[0]?.id ?? ''),
    category_id:  initial?.category_id  ?? '',
    frequency:    initial?.frequency    ?? 'monthly',
    start_date:   initial?.start_date   ?? new Date().toISOString().slice(0, 10),
    end_date:     initial?.end_date     ?? '',
    notes:        initial?.notes        ?? '',
  })
  const [error, setError] = useState('')

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    if (!form.description.trim()) { setError('Description is required'); return }
    const amt = parseFloat(form.amount)
    if (isNaN(amt)) { setError('Enter a valid amount'); return }
    if (!form.account_id) { setError('Select an account'); return }
    setError('')

    onSave({
      description:  form.description.trim(),
      amount:       amt,
      account_id:   parseInt(form.account_id),
      category_id:  form.category_id ? parseInt(form.category_id) : null,
      frequency:    form.frequency,
      start_date:   form.start_date,
      end_date:     form.end_date || null,
      notes:        form.notes.trim() || null,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Description *">
        <input style={inputStyle} value={form.description} onChange={set('description')} autoFocus required />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Amount *" hint="Negative = expense, positive = income">
          <input
            style={inputStyle} type="number" step="0.01"
            value={form.amount} onChange={set('amount')}
            required inputMode="decimal"
          />
        </FormField>
        <FormField label="Frequency *">
          <select style={selectStyle} value={form.frequency} onChange={set('frequency')}>
            {FREQUENCIES.map((f) => (
              <option key={f.value} value={f.value}>{f.label}</option>
            ))}
          </select>
        </FormField>
      </div>

      <FormField label="Account *">
        <select style={selectStyle} value={form.account_id} onChange={set('account_id')} required>
          <option value="">Select account…</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.name}{a.institution ? ` · ${a.institution}` : ''}</option>
          ))}
        </select>
      </FormField>

      <FormField label="Category">
        <select style={selectStyle} value={form.category_id} onChange={set('category_id')}>
          <option value="">No category</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Start date *" hint="First transaction generated on this date">
          <input style={inputStyle} type="date" value={form.start_date} onChange={set('start_date')} required />
        </FormField>
        <FormField label="End date" hint="Leave blank to run indefinitely">
          <input style={inputStyle} type="date" value={form.end_date} onChange={set('end_date')} />
        </FormField>
      </div>

      <FormField label="Notes">
        <input style={inputStyle} value={form.notes} onChange={set('notes')} placeholder="Optional note" />
      </FormField>

      {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save changes' : 'Create recurring'}
        </Button>
      </div>
    </form>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Recurring() {
  const { isOwner } = useAuth()
  const { formatCurrency } = useCurrency()

  const [entries, setEntries]     = useState([])
  const [accounts, setAccounts]   = useState([])
  const [categories, setCategories] = useState([])
  const [loading, setLoading]     = useState(true)
  const [error, setError]         = useState('')

  const [showAdd, setShowAdd]   = useState(false)
  const [editing, setEditing]   = useState(null)
  const [deleting, setDeleting] = useState(null)
  const [saving, setSaving]     = useState(false)
  const [actionError, setActionError] = useState('')

  const load = useCallback(() => {
    setLoading(true)
    client.get('/recurring')
      .then((r) => setEntries(r.data))
      .catch(() => setError('Failed to load recurring transactions'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    client.get('/accounts').then((r) => setAccounts(r.data.filter((a) => a.is_active)))
    client.get('/categories').then((r) => setCategories(r.data))
  }, [load])

  async function handleAdd(form) {
    setSaving(true); setActionError('')
    try {
      await client.post('/recurring', form)
      setShowAdd(false); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to create recurring transaction')
    } finally { setSaving(false) }
  }

  async function handleEdit(form) {
    setSaving(true); setActionError('')
    try {
      await client.patch(`/recurring/${editing.id}`, form)
      setEditing(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to update recurring transaction')
    } finally { setSaving(false) }
  }

  async function handleDelete() {
    setSaving(true)
    try {
      await client.delete(`/recurring/${deleting.id}`)
      setDeleting(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to delete recurring transaction')
    } finally { setSaving(false) }
  }

  const active   = entries.filter((r) => r.is_active)
  const inactive = entries.filter((r) => !r.is_active)
  const totalMonthly = active.reduce((s, r) => {
    // Normalise all frequencies to a monthly equivalent
    const multipliers = { daily: 30.44, weekly: 4.33, fortnightly: 2.17, monthly: 1, yearly: 1 / 12 }
    return s + r.amount * (multipliers[r.frequency] ?? 1)
  }, 0)

  return (
    <div>
      {/* Header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.pageTitle}>Recurring Transactions</h1>
          <p style={styles.pageSubtitle}>
            Scheduled entries that auto-generate on each due date.
            {active.length > 0 && ` ${active.length} active · `}
            {active.length > 0 && (
              <span style={{ color: totalMonthly >= 0 ? 'var(--green)' : 'var(--pink)' }}>
                {formatCurrency(totalMonthly)}/mo estimated
              </span>
            )}
          </p>
        </div>
        {isOwner && (
          <Button onClick={() => { setShowAdd(true); setActionError('') }}>
            + Add recurring
          </Button>
        )}
      </div>

      {error && <p style={{ color: 'var(--red)', marginBottom: 16 }}>{error}</p>}

      {loading ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : entries.length === 0 ? (
        <div style={styles.empty}>
          <p style={styles.emptyTitle}>No recurring transactions</p>
          {isOwner && (
            <>
              <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 20 }}>
                Set up rent, subscriptions, or any regular income or expense.
              </p>
              <Button onClick={() => { setShowAdd(true); setActionError('') }}>+ Add first recurring</Button>
            </>
          )}
        </div>
      ) : (
        <>
          {active.length > 0 && (
            <div style={styles.grid}>
              {active.map((r) => (
                <RecurringCard
                  key={r.id}
                  rec={r}
                  isOwner={isOwner}
                  onEdit={() => { setEditing(r); setActionError('') }}
                  onDelete={() => { setDeleting(r); setActionError('') }}
                />
              ))}
            </div>
          )}

          {inactive.length > 0 && (
            <>
              <h2 style={styles.sectionHeader}>Inactive</h2>
              <div style={styles.grid}>
                {inactive.map((r) => (
                  <RecurringCard
                    key={r.id}
                    rec={r}
                    isOwner={isOwner}
                    onEdit={() => { setEditing(r); setActionError('') }}
                    onDelete={() => { setDeleting(r); setActionError('') }}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* Modals */}
      {showAdd && (
        <Modal title="New recurring transaction" onClose={() => setShowAdd(false)} width={520}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <RecurringForm
            accounts={accounts}
            categories={categories}
            onSave={handleAdd}
            onCancel={() => setShowAdd(false)}
            saving={saving}
          />
        </Modal>
      )}

      {editing && (
        <Modal title={`Edit — ${editing.description}`} onClose={() => setEditing(null)} width={520}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <RecurringForm
            initial={editing}
            accounts={accounts}
            categories={categories}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={saving}
          />
        </Modal>
      )}

      {deleting && (
        <Modal title="Delete recurring transaction?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            <strong>{deleting.description}</strong> will be permanently removed.
          </p>
          <p style={{ color: 'var(--muted)', fontSize: 13, marginBottom: 16 }}>
            Already-generated transactions are not affected.
          </p>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Deleting…' : 'Delete'}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

const styles = {
  pageHeader: {
    display: 'flex', alignItems: 'flex-start',
    justifyContent: 'space-between', marginBottom: 24,
    flexWrap: 'wrap', gap: 12,
  },
  pageTitle:    { fontSize: 24, fontWeight: 700, color: 'var(--white)' },
  pageSubtitle: { color: 'var(--muted)', fontSize: 14, marginTop: 4 },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
    gap: 16, marginBottom: 24,
  },
  sectionHeader: {
    fontSize: 14, fontWeight: 600, color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: 12,
  },
  card: {
    background: 'var(--bg-card)', border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)', padding: '16px 18px',
  },
  cardHeader: {
    display: 'flex', gap: 8, justifyContent: 'space-between',
    alignItems: 'flex-start', marginBottom: 12,
  },
  cardName: { fontSize: 15, fontWeight: 600, color: 'var(--white)', marginBottom: 2 },
  cardMeta: { fontSize: 12, color: 'var(--muted)' },
  statsRow: {
    display: 'flex', flexWrap: 'wrap', gap: 16,
  },
  stat: { display: 'flex', flexDirection: 'column', gap: 3 },
  statLabel: { fontSize: 11, color: 'var(--muted)', fontWeight: 500 },
  iconBtn: {
    background: 'none', border: 'none', cursor: 'pointer',
    color: 'var(--muted)', fontSize: 15, padding: '2px 4px',
    borderRadius: 'var(--radius)',
  },
  empty: { textAlign: 'center', padding: '60px 0' },
  emptyTitle: { fontSize: 18, fontWeight: 600, color: 'var(--white)', marginBottom: 8 },
  modalError: { color: 'var(--red)', fontSize: 13, marginBottom: 12 },
}
