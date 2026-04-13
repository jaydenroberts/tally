import { useEffect, useState, useCallback } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useCurrency } from '../context/CurrencyContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'

const ACCOUNT_TYPES = ['checking', 'savings', 'credit', 'investment', 'loan', 'other']

const CURRENCIES = ['USD', 'EUR', 'GBP', 'CAD', 'AUD', 'JPY', 'CHF', 'NZD']

const TYPE_COLORS = {
  checking:   'var(--cyan)',
  savings:    'var(--green)',
  credit:     'var(--pink)',
  investment: 'var(--orange)',
  loan:       'var(--red)',
  other:      'var(--muted)',
}

function AccountForm({ initial, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    name: initial?.name ?? '',
    account_type: initial?.account_type ?? 'checking',
    institution: initial?.institution ?? '',
    balance: initial?.balance ?? 0,
    currency: initial?.currency ?? 'USD',
    notes: initial?.notes ?? '',
  })

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    onSave({ ...form, balance: parseFloat(form.balance) || 0 })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Account name *">
        <input style={inputStyle} value={form.name} onChange={set('name')} required autoFocus />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Type">
          <select style={selectStyle} value={form.account_type} onChange={set('account_type')}>
            {ACCOUNT_TYPES.map((t) => (
              <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>
            ))}
          </select>
        </FormField>

        <FormField label="Currency">
          <select style={selectStyle} value={form.currency} onChange={set('currency')}>
            {CURRENCIES.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </FormField>
      </div>

      <FormField label="Institution">
        <input style={inputStyle} value={form.institution} onChange={set('institution')} placeholder="e.g. Chase, Vanguard" />
      </FormField>

      <FormField label="Current balance" hint="Use negative values for credit/loan accounts">
        <input style={inputStyle} type="number" step="0.01" value={form.balance} onChange={set('balance')} />
      </FormField>

      <FormField label="Notes">
        <textarea
          style={{ ...inputStyle, resize: 'vertical', minHeight: 70 }}
          value={form.notes}
          onChange={set('notes')}
        />
      </FormField>

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>
          {saving ? 'Saving…' : initial ? 'Save changes' : 'Add account'}
        </Button>
      </div>
    </form>
  )
}

export default function Accounts() {
  const { isOwner } = useAuth()
  const { formatCurrency } = useCurrency()
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [showAdd, setShowAdd] = useState(false)
  const [editing, setEditing] = useState(null)       // account object
  const [deleting, setDeleting] = useState(null)     // account object
  const [saving, setSaving] = useState(false)
  const [actionError, setActionError] = useState('')
  const [closedAccounts, setClosedAccounts] = useState([])
  const [showClosed, setShowClosed] = useState(false)
  const [closing, setClosing] = useState(null)          // account to mark as closed

  const load = useCallback(() => {
    setLoading(true)
    Promise.all([
      client.get('/accounts'),
      client.get('/accounts?include_closed=true'),
    ])
      .then(([activeRes, allRes]) => {
        const activeIds = new Set(activeRes.data.map(a => a.id))
        setAccounts(activeRes.data)
        setClosedAccounts(allRes.data.filter(a => !activeIds.has(a.id)))
      })
      .catch(() => setError('Failed to load accounts'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { load() }, [load])

  async function handleAdd(form) {
    setSaving(true)
    setActionError('')
    try {
      await client.post('/accounts', form)
      setShowAdd(false)
      load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to create account')
    } finally {
      setSaving(false)
    }
  }

  async function handleEdit(form) {
    setSaving(true)
    setActionError('')
    try {
      await client.patch(`/accounts/${editing.id}`, form)
      setEditing(null)
      load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to update account')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setSaving(true)
    try {
      await client.delete(`/accounts/${deleting.id}`)
      setDeleting(null)
      load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to delete account')
    } finally {
      setSaving(false)
    }
  }

  async function handleClose() {
    setSaving(true)
    try {
      await client.patch(`/accounts/${closing.id}`, { status: 'closed' })
      setClosing(null)
      load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to close account')
    } finally {
      setSaving(false)
    }
  }

  async function handleReopen(account) {
    try {
      await client.patch(`/accounts/${account.id}`, { status: 'active' })
      load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to reopen account')
    }
  }

  const totalByCurrency = accounts.reduce((acc, a) => {
    acc[a.currency] = (acc[a.currency] ?? 0) + a.balance
    return acc
  }, {})

  return (
    <div>
      {/* Page header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.pageTitle}>Accounts</h1>
          <p style={styles.pageSubtitle}>
            {accounts.length} account{accounts.length !== 1 ? 's' : ''}
            {Object.entries(totalByCurrency).map(([cur, total]) => (
              <span key={cur} style={{ marginLeft: 16, color: total >= 0 ? 'var(--green)' : 'var(--red)' }}>
                {formatCurrency(total, cur)}
              </span>
            ))}
          </p>
        </div>
        {isOwner && (
          <Button onClick={() => { setShowAdd(true); setActionError('') }}>
            + Add account
          </Button>
        )}
      </div>

      {error && <p style={styles.errorMsg}>{error}</p>}

      {loading ? (
        <p style={styles.muted}>Loading…</p>
      ) : accounts.length === 0 ? (
        <div style={styles.empty}>
          <p style={styles.emptyTitle}>No accounts yet</p>
          {isOwner && (
            <p style={styles.muted}>Add your first account to start tracking your finances.</p>
          )}
        </div>
      ) : (
        <div style={styles.grid}>
          {accounts.map((account) => (
            <AccountCard
              key={account.id}
              account={account}
              isOwner={isOwner}
              onEdit={() => { setEditing(account); setActionError('') }}
              onDelete={() => { setDeleting(account); setActionError('') }}
              onClose={() => { setClosing(account); setActionError('') }}
            />
          ))}
        </div>
      )}

      {/* Closed accounts */}
      {closedAccounts.length > 0 && (
        <div style={{ marginTop: 32 }}>
          <button
            style={styles.closedToggle}
            onClick={() => setShowClosed(s => !s)}
          >
            {showClosed ? '▾' : '▸'} Closed accounts ({closedAccounts.length})
          </button>
          {showClosed && (
            <div style={{ ...styles.grid, marginTop: 12, opacity: 0.7 }}>
              {closedAccounts.map(account => (
                <AccountCard
                  key={account.id}
                  account={account}
                  isOwner={isOwner}
                  closed
                  onReopen={() => handleReopen(account)}
                />
              ))}
            </div>
          )}
        </div>
      )}

      {/* Close confirmation */}
      {closing && (
        <Modal title="Close account?" onClose={() => setClosing(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            <strong>{closing.name}</strong> will be moved to "Closed accounts".
            Transactions are preserved and the account remains visible for historical reports.
          </p>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Button variant="secondary" onClick={() => setClosing(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleClose} disabled={saving}>
              {saving ? 'Closing…' : 'Close account'}
            </Button>
          </div>
        </Modal>
      )}

      {/* Add modal */}
      {showAdd && (
        <Modal title="Add account" onClose={() => setShowAdd(false)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <AccountForm onSave={handleAdd} onCancel={() => setShowAdd(false)} saving={saving} />
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title="Edit account" onClose={() => setEditing(null)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <AccountForm
            initial={editing}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={saving}
          />
        </Modal>
      )}

      {/* Delete confirmation */}
      {deleting && (
        <Modal title="Delete account?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            <strong>{deleting.name}</strong> will be hidden from all views.
            Transactions will be preserved.
          </p>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Deleting…' : 'Delete account'}
            </Button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function AccountCard({ account, isOwner, onEdit, onDelete, onClose, closed, onReopen }) {
  const { formatCurrency } = useCurrency()
  const typeColor = TYPE_COLORS[account.account_type] ?? 'var(--muted)'
  return (
    <div style={{ ...styles.card, borderTop: `3px solid ${typeColor}` }}>
      <div style={styles.cardTop}>
        <div>
          <p style={styles.cardName}>
            {account.name}
            {closed && <span style={styles.closedBadge}>Closed</span>}
          </p>
          <p style={styles.cardMeta}>
            <span style={{ color: typeColor, textTransform: 'capitalize' }}>
              {account.account_type ?? 'Account'}
            </span>
            {account.institution && (
              <span style={{ color: 'var(--muted)' }}> · {account.institution}</span>
            )}
          </p>
        </div>
        {isOwner && !closed && (
          <div style={styles.cardActions}>
            <button style={styles.iconBtn} onClick={onEdit} title="Edit">✎</button>
            <button style={styles.iconBtn} onClick={onClose} title="Close account">⏻</button>
            <button style={{ ...styles.iconBtn, color: 'var(--red)' }} onClick={onDelete} title="Delete">✕</button>
          </div>
        )}
        {isOwner && closed && (
          <div style={styles.cardActions}>
            <button style={{ ...styles.iconBtn, color: 'var(--green)' }} onClick={onReopen} title="Reopen account">↺</button>
          </div>
        )}
      </div>
      <p style={{
        ...styles.cardBalance,
        color: account.balance >= 0 ? 'var(--green)' : 'var(--red)',
      }}>
        {formatCurrency(account.balance, account.currency)}
      </p>
      {account.notes && (
        <p style={styles.cardNotes}>{account.notes}</p>
      )}
    </div>
  )
}

const styles = {
  pageHeader: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 28,
    gap: 16,
  },
  pageTitle: {
    fontSize: 24,
    fontWeight: 700,
    color: 'var(--white)',
  },
  pageSubtitle: {
    color: 'var(--muted)',
    fontSize: 14,
    marginTop: 4,
  },
  errorMsg: {
    color: 'var(--red)',
    marginBottom: 16,
    fontSize: 14,
  },
  muted: {
    color: 'var(--muted)',
    fontSize: 14,
  },
  empty: {
    textAlign: 'center',
    padding: '60px 0',
  },
  emptyTitle: {
    fontSize: 18,
    fontWeight: 600,
    color: 'var(--white)',
    marginBottom: 8,
  },
  grid: {
    display: 'grid',
    gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))',
    gap: 16,
  },
  card: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    padding: '20px 22px',
  },
  cardTop: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    marginBottom: 14,
  },
  cardName: {
    fontSize: 16,
    fontWeight: 600,
    color: 'var(--white)',
    marginBottom: 4,
  },
  cardMeta: {
    fontSize: 13,
  },
  cardActions: {
    display: 'flex',
    gap: 4,
  },
  iconBtn: {
    background: 'none',
    border: 'none',
    color: 'var(--muted)',
    fontSize: 15,
    padding: '4px 6px',
    borderRadius: 'var(--radius)',
    cursor: 'pointer',
  },
  cardBalance: {
    fontSize: 24,
    fontWeight: 700,
    marginBottom: 8,
  },
  cardNotes: {
    fontSize: 12,
    color: 'var(--muted)',
    marginTop: 8,
    paddingTop: 8,
    borderTop: '1px solid var(--border)',
  },
  modalError: {
    color: 'var(--red)',
    fontSize: 13,
    marginBottom: 12,
  },
  closedToggle: {
    background: 'none',
    border: 'none',
    color: 'var(--muted)',
    fontSize: 14,
    cursor: 'pointer',
    padding: '4px 0',
    fontWeight: 600,
  },
  closedBadge: {
    display: 'inline-block',
    fontSize: 10,
    fontWeight: 600,
    padding: '2px 8px',
    borderRadius: 99,
    background: 'var(--border)',
    color: 'var(--muted)',
    marginLeft: 8,
    verticalAlign: 'middle',
  },
}
