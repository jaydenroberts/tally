import { useEffect, useState, useCallback } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useCurrency } from '../context/CurrencyContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'

// ─── Status helpers ───────────────────────────────────────────────────────────

/**
 * Determine colour-coded status for a goal.
 *
 * With a deadline   → compare projected completion to deadline
 * Without deadline  → use raw percentage bands
 */
function goalStatus(goal) {
  if (goal.is_completed) return 'completed'

  const pct = goal.target_amount > 0
    ? (goal.current_amount / goal.target_amount) * 100
    : 0

  if (goal.deadline) {
    const today    = new Date()
    const deadline = new Date(goal.deadline)

    // Already past deadline and not done
    if (today > deadline) return 'overdue'

    // Project completion from monthly contribution
    const projected = projectedDate(goal)
    if (projected) {
      const diffMonths = (projected - deadline) / (1000 * 60 * 60 * 24 * 30.44)
      if (diffMonths <= 0)  return 'healthy'   // on time or ahead
      if (diffMonths <= 3)  return 'warning'   // up to 3 months late
      return 'behind'                          // more than 3 months late
    }

    // No monthly rate — fall back to time-elapsed vs progress comparison
    const created  = new Date(goal.created_at)
    const totalMs  = deadline - created
    const elapsedMs = today - created
    const expectedPct = totalMs > 0 ? Math.min(100, (elapsedMs / totalMs) * 100) : 0

    if (pct >= expectedPct - 5)  return 'healthy'
    if (pct >= expectedPct - 20) return 'warning'
    return 'behind'
  }

  // No deadline — pure percentage bands
  if (pct >= 75) return 'healthy'
  if (pct >= 25) return 'warning'
  return 'behind'
}

function statusColor(s) {
  if (s === 'completed') return '#8BE9FD'  // cyan
  if (s === 'healthy')   return '#50FA7B'  // green
  if (s === 'warning')   return '#FFB86C'  // orange
  return '#FF79C6'                         // pink — behind | overdue
}

function statusLabel(s) {
  if (s === 'completed') return '✓ Complete'
  if (s === 'healthy')   return '● On track'
  if (s === 'warning')   return '● Behind'
  if (s === 'overdue')   return '● Overdue'
  return '● Off track'
}

// ─── Projection math ─────────────────────────────────────────────────────────

/** Returns a projected completion Date, or null if not enough data. */
function projectedDate(goal) {
  if (!goal.monthly_contribution || goal.monthly_contribution <= 0) return null
  if (goal.current_amount >= goal.target_amount) return null
  const remaining    = goal.target_amount - goal.current_amount
  const monthsNeeded = remaining / goal.monthly_contribution
  const d = new Date()
  // Add fractional months precisely
  d.setDate(d.getDate() + Math.ceil(monthsNeeded * 30.44))
  return d
}

function formatDate(d) {
  if (!d) return null
  const date = typeof d === 'string' ? new Date(d) : d
  return date.toLocaleDateString('en-US', { month: 'short', year: 'numeric' })
}

// ─── Progress bar ─────────────────────────────────────────────────────────────

function GoalProgressBar({ pct, status }) {
  const color = statusColor(status)
  const width = Math.min(100, Math.max(0, pct))
  return (
    <div style={bar.track}>
      <div style={{ ...bar.fill, width: width + '%', background: color }} />
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
    margin: '14px 0 10px',
  },
  fill: {
    position: 'absolute',
    top: 0, left: 0,
    height: '100%',
    borderRadius: 4,
    transition: 'width 0.4s ease',
  },
}

// ─── Goal card ────────────────────────────────────────────────────────────────

function GoalCard({ goal, isOwner, onEdit, onDelete, onContribute, onHistory }) {
  const { formatCurrency } = useCurrency()
  const pct      = goal.target_amount > 0
    ? Math.min(100, (goal.current_amount / goal.target_amount) * 100)
    : 0
  const status   = goalStatus(goal)
  const color    = statusColor(status)
  const projected = projectedDate(goal)

  const projectedOnTime = projected && goal.deadline
    ? new Date(projected) <= new Date(goal.deadline)
    : null

  return (
    <div style={{ ...styles.card, borderTop: `3px solid ${color}` }}>
      {/* Header */}
      <div style={styles.cardHeader}>
        <div style={{ flex: 1, minWidth: 0 }}>
          <p style={styles.cardName}>{goal.name}</p>
          {goal.linked_account && (
            <p style={styles.accountBadge}>
              ⬡ {goal.linked_account.name}
            </p>
          )}
        </div>
        <div style={{ display: 'flex', gap: 4, alignItems: 'center', flexShrink: 0 }}>
          <span style={{ ...styles.statusBadge, color, background: color + '18' }}>
            {statusLabel(status)}
          </span>
          <button style={{ ...styles.iconBtn, color: 'var(--cyan)' }} onClick={onHistory} title="Contribution history">⏱</button>
          {isOwner && !goal.is_completed && (
            <button style={styles.iconBtn} onClick={onEdit} title="Edit">✎</button>
          )}
          {isOwner && (
            <button style={{ ...styles.iconBtn, color: 'var(--red)' }} onClick={onDelete} title="Delete">✕</button>
          )}
        </div>
      </div>

      {/* Progress bar */}
      <GoalProgressBar pct={pct} status={status} />

      {/* Stats grid */}
      <div style={styles.statsGrid}>
        <StatCell label="Saved"    value={formatCurrency(goal.current_amount)} color={color} />
        <StatCell label="Target"   value={formatCurrency(goal.target_amount)} />
        <StatCell label="Progress" value={`${pct.toFixed(1)}%`} color={color} />
        <StatCell label="Remaining" value={formatCurrency(Math.max(0, goal.target_amount - goal.current_amount))} />
      </div>

      {/* Contribution + projection row */}
      <div style={styles.projectionRow}>
        <div style={styles.projCell}>
          <span style={styles.projLabel}>Monthly contribution</span>
          <span style={styles.projValue}>
            {goal.monthly_contribution
              ? formatCurrency(goal.monthly_contribution)
              : <span style={{ color: 'var(--border)' }}>—</span>}
          </span>
        </div>

        <div style={styles.projCell}>
          <span style={styles.projLabel}>Deadline</span>
          <span style={styles.projValue}>
            {goal.deadline
              ? formatDate(goal.deadline)
              : <span style={{ color: 'var(--border)' }}>—</span>}
          </span>
        </div>

        <div style={styles.projCell}>
          <span style={styles.projLabel}>Projected completion</span>
          <span style={{ ...styles.projValue, color: projected ? (projectedOnTime === false ? 'var(--pink)' : 'var(--green)') : 'var(--muted)' }}>
            {projected
              ? <>
                  {formatDate(projected)}
                  {projectedOnTime !== null && (
                    <span style={{ marginLeft: 4 }}>{projectedOnTime ? '✓' : '✗'}</span>
                  )}
                </>
              : goal.monthly_contribution
                ? 'Goal reached!'
                : <span style={{ color: 'var(--muted)', fontSize: 11 }}>set monthly contribution</span>}
          </span>
        </div>
      </div>

      {/* Contribute button */}
      {isOwner && !goal.is_completed && (
        <div style={{ marginTop: 14, paddingTop: 12, borderTop: '1px solid var(--border)' }}>
          <Button
            variant="secondary"
            size="sm"
            onClick={onContribute}
            style={{ width: '100%', justifyContent: 'center' }}
          >
            + Log contribution
          </Button>
        </div>
      )}

      {goal.notes && (
        <p style={styles.notes}>{goal.notes}</p>
      )}
    </div>
  )
}

function StatCell({ label, value, color }) {
  return (
    <div style={styles.statCell}>
      <span style={styles.statLabel}>{label}</span>
      <span style={{ fontSize: 15, fontWeight: 700, color: color ?? 'var(--white)' }}>{value}</span>
    </div>
  )
}

// ─── Goal form ────────────────────────────────────────────────────────────────

function GoalForm({ initial, accounts, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    name:                 initial?.name                 ?? '',
    target_amount:        initial?.target_amount        ?? '',
    current_amount:       initial?.current_amount       ?? 0,
    monthly_contribution: initial?.monthly_contribution ?? '',
    deadline:             initial?.deadline             ?? '',
    linked_account_id:    initial?.linked_account_id    ?? '',
    notes:                initial?.notes                ?? '',
  })
  const [error, setError] = useState('')

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    const target = parseFloat(form.target_amount)
    if (isNaN(target) || target <= 0) { setError('Enter a positive target amount'); return }
    setError('')
    onSave({
      name:                 form.name,
      target_amount:        target,
      current_amount:       parseFloat(form.current_amount) || 0,
      monthly_contribution: form.monthly_contribution ? parseFloat(form.monthly_contribution) : null,
      deadline:             form.deadline || null,
      linked_account_id:    form.linked_account_id ? parseInt(form.linked_account_id) : null,
      notes:                form.notes || null,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Goal name *">
        <input style={inputStyle} value={form.name} onChange={set('name')} required autoFocus />
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Target amount *">
          <input style={inputStyle} type="number" step="0.01" min="0.01" value={form.target_amount} onChange={set('target_amount')} required inputMode="decimal" />
        </FormField>
        <FormField label="Already saved">
          <input style={inputStyle} type="number" step="0.01" min="0" value={form.current_amount} onChange={set('current_amount')} inputMode="decimal" />
        </FormField>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Monthly contribution" hint="Used to project completion date">
          <input style={inputStyle} type="number" step="0.01" min="0" value={form.monthly_contribution} onChange={set('monthly_contribution')} inputMode="decimal" placeholder="e.g. 500" />
        </FormField>
        <FormField label="Target deadline">
          <input style={inputStyle} type="date" value={form.deadline} onChange={set('deadline')} />
        </FormField>
      </div>

      <FormField label="Link to account" hint="e.g. your savings account for this goal">
        <select style={selectStyle} value={form.linked_account_id} onChange={set('linked_account_id')}>
          <option value="">No linked account</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.name}{a.institution ? ` · ${a.institution}` : ''}</option>
          ))}
        </select>
      </FormField>

      <FormField label="Notes">
        <textarea style={{ ...inputStyle, resize: 'vertical', minHeight: 60 }} value={form.notes} onChange={set('notes')} />
      </FormField>

      {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : initial ? 'Save changes' : 'Create goal'}</Button>
      </div>
    </form>
  )
}

// ─── Contribute form ──────────────────────────────────────────────────────────

function ContributeForm({ goal, onSave, onCancel, saving }) {
  const { formatCurrency } = useCurrency()
  const [amount, setAmount] = useState('')
  const [notes, setNotes]   = useState('')
  const [error, setError]   = useState('')

  function handleSubmit(e) {
    e.preventDefault()
    const val = parseFloat(amount)
    if (isNaN(val) || val <= 0) { setError('Enter a positive amount'); return }
    const remaining = goal.target_amount - goal.current_amount
    if (val > remaining * 2) {
      setError(`That would significantly overshoot the target (${formatCurrency(remaining)} remaining). Adjust if intentional.`)
      // not blocking — just a warning. Let it through on second submit.
    }
    setError('')
    onSave({ amount: val, notes: notes.trim() || null })
  }

  const remaining = goal.target_amount - goal.current_amount

  return (
    <form onSubmit={handleSubmit}>
      <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 16 }}>
        Adding to <strong style={{ color: 'var(--white)' }}>{goal.name}</strong>
        <br />
        Currently <strong style={{ color: 'var(--green)' }}>{formatCurrency(goal.current_amount)}</strong> of {formatCurrency(goal.target_amount)} · {formatCurrency(remaining)} remaining
      </p>

      <FormField label="Amount *">
        <input
          style={inputStyle}
          type="number"
          step="0.01"
          min="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          required
          autoFocus
          inputMode="decimal"
          placeholder={goal.monthly_contribution ? formatCurrency(goal.monthly_contribution).replace(/[^0-9.]/g, '') : ''}
        />
      </FormField>

      <FormField label="Notes" hint="Optional — e.g. 'Monthly transfer' or 'Birthday money'">
        <input
          style={inputStyle}
          value={notes}
          onChange={(e) => setNotes(e.target.value)}
          placeholder="Optional note"
        />
      </FormField>

      {error && <p style={{ color: 'var(--orange)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Log contribution'}</Button>
      </div>
    </form>
  )
}

// ─── Contribution history modal ───────────────────────────────────────────────

function ContributionHistoryModal({ goal, onClose }) {
  const { formatCurrency } = useCurrency()
  const [contributions, setContributions] = useState([])
  const [loading, setLoading]             = useState(true)
  const [error, setError]                 = useState('')

  useEffect(() => {
    client.get(`/savings/${goal.id}/contributions`)
      .then((r) => setContributions(r.data))
      .catch(() => setError('Failed to load contribution history'))
      .finally(() => setLoading(false))
  }, [goal.id])

  const total = contributions.reduce((s, c) => s + c.amount, 0)

  return (
    <Modal title={`Contribution history — ${goal.name}`} onClose={onClose} width={520}>
      {loading ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : error ? (
        <p style={{ color: 'var(--red)' }}>{error}</p>
      ) : contributions.length === 0 ? (
        <p style={{ color: 'var(--muted)', textAlign: 'center', padding: '24px 0' }}>
          No contributions recorded yet.
        </p>
      ) : (
        <>
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: 'var(--muted)' }}>
              {contributions.length} contribution{contributions.length !== 1 ? 's' : ''}
            </span>
            <span style={{ fontSize: 13, color: 'var(--green)', fontWeight: 600 }}>
              {formatCurrency(total)} total contributed
            </span>
          </div>

          <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
            <div style={savingsHistoryStyles.header}>
              <span>Date</span>
              <span>Amount</span>
              <span>Balance after</span>
              <span>Notes</span>
            </div>
            {contributions.map((c) => (
              <div key={c.id} style={savingsHistoryStyles.row}>
                <span style={{ fontSize: 13, color: 'var(--muted)' }}>
                  {new Date(c.contributed_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                </span>
                <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--green)' }}>
                  {formatCurrency(c.amount)}
                </span>
                <span style={{ fontSize: 13, color: 'var(--white)' }}>
                  {formatCurrency(c.balance_after)}
                </span>
                <span style={{ fontSize: 12, color: 'var(--muted)', fontStyle: c.notes ? 'normal' : 'italic' }}>
                  {c.notes ?? '—'}
                </span>
              </div>
            ))}
          </div>
        </>
      )}
    </Modal>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Savings() {
  const { isOwner } = useAuth()
  const { formatCurrency } = useCurrency()

  const [goals, setGoals]       = useState([])
  const [accounts, setAccounts] = useState([])
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState('')

  const [showAdd, setShowAdd]           = useState(false)
  const [editing, setEditing]           = useState(null)
  const [deleting, setDeleting]         = useState(null)
  const [contributing, setContributing] = useState(null)
  const [viewHistory, setViewHistory]   = useState(null)  // goal whose contribution history to show
  const [saving, setSaving]             = useState(false)
  const [actionError, setActionError]   = useState('')

  const load = useCallback(() => {
    setLoading(true)
    client.get('/savings')
      .then((r) => setGoals(r.data))
      .catch(() => setError('Failed to load savings goals'))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    load()
    client.get('/accounts').then((r) => setAccounts(r.data))
  }, [load])

  // Summary stats
  const activeGoals    = goals.filter((g) => !g.is_completed)
  const completedGoals = goals.filter((g) => g.is_completed)
  const totalSaved     = activeGoals.reduce((s, g) => s + g.current_amount, 0)
  const totalTarget    = activeGoals.reduce((s, g) => s + g.target_amount, 0)
  const totalMonthly   = activeGoals.reduce((s, g) => s + (g.monthly_contribution ?? 0), 0)

  async function handleAdd(form) {
    setSaving(true); setActionError('')
    try {
      await client.post('/savings', form)
      setShowAdd(false); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to create goal')
    } finally { setSaving(false) }
  }

  async function handleEdit(form) {
    setSaving(true); setActionError('')
    try {
      await client.patch(`/savings/${editing.id}`, form)
      setEditing(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to update goal')
    } finally { setSaving(false) }
  }

  async function handleDelete() {
    setSaving(true)
    try {
      await client.delete(`/savings/${deleting.id}`)
      setDeleting(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to delete goal')
    } finally { setSaving(false) }
  }

  async function handleContribute({ amount, notes }) {
    setSaving(true); setActionError('')
    try {
      await client.post(`/savings/${contributing.id}/contribute`, { amount, notes })
      setContributing(null); load()
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to log contribution')
    } finally { setSaving(false) }
  }

  return (
    <div>
      {/* Header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.pageTitle}>Savings Goals</h1>
          {goals.length > 0 && (
            <p style={styles.pageSubtitle}>
              {activeGoals.length} active · {completedGoals.length} completed
            </p>
          )}
        </div>
        {isOwner && (
          <Button onClick={() => { setShowAdd(true); setActionError('') }}>
            + New goal
          </Button>
        )}
      </div>

      {/* Totals strip */}
      {activeGoals.length > 0 && (
        <div style={styles.totalsBar}>
          <TotalChip label="Total saved"    value={formatCurrency(totalSaved)}   color="var(--green)" />
          <TotalChip label="Total target"   value={formatCurrency(totalTarget)}  color="var(--muted)" />
          <TotalChip label="Total monthly"  value={formatCurrency(totalMonthly)} color="var(--cyan)"  />
          <TotalChip label="Still needed"   value={formatCurrency(Math.max(0, totalTarget - totalSaved))} color="var(--white)" />
        </div>
      )}

      {error && <p style={{ color: 'var(--red)', marginBottom: 16 }}>{error}</p>}

      {loading ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : goals.length === 0 ? (
        <div style={styles.empty}>
          <p style={styles.emptyTitle}>No savings goals yet</p>
          {isOwner && (
            <>
              <p style={{ color: 'var(--muted)', fontSize: 14, marginBottom: 20 }}>
                Set a target, link a savings account, and track your progress here.
              </p>
              <Button onClick={() => { setShowAdd(true); setActionError('') }}>+ Create first goal</Button>
            </>
          )}
        </div>
      ) : (
        <>
          {activeGoals.length > 0 && (
            <div style={styles.grid}>
              {activeGoals.map((g) => (
                <GoalCard
                  key={g.id}
                  goal={g}
                  isOwner={isOwner}
                  onEdit={() => { setEditing(g); setActionError('') }}
                  onDelete={() => { setDeleting(g); setActionError('') }}
                  onContribute={() => { setContributing(g); setActionError('') }}
                  onHistory={() => setViewHistory(g)}
                />
              ))}
            </div>
          )}

          {completedGoals.length > 0 && (
            <>
              <h2 style={styles.sectionHeader}>Completed</h2>
              <div style={styles.grid}>
                {completedGoals.map((g) => (
                  <GoalCard
                    key={g.id}
                    goal={g}
                    isOwner={isOwner}
                    onEdit={() => { setEditing(g); setActionError('') }}
                    onDelete={() => { setDeleting(g); setActionError('') }}
                    onContribute={() => {}}
                    onHistory={() => setViewHistory(g)}
                  />
                ))}
              </div>
            </>
          )}
        </>
      )}

      {/* Add modal */}
      {showAdd && (
        <Modal title="New savings goal" onClose={() => setShowAdd(false)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <GoalForm accounts={accounts} onSave={handleAdd} onCancel={() => setShowAdd(false)} saving={saving} />
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title={`Edit — ${editing.name}`} onClose={() => setEditing(null)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <GoalForm initial={editing} accounts={accounts} onSave={handleEdit} onCancel={() => setEditing(null)} saving={saving} />
        </Modal>
      )}

      {/* Contribute modal */}
      {contributing && (
        <Modal title="Log contribution" onClose={() => setContributing(null)} width={400}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <ContributeForm goal={contributing} onSave={handleContribute} onCancel={() => setContributing(null)} saving={saving} />
        </Modal>
      )}

      {/* Delete confirmation */}
      {deleting && (
        <Modal title="Delete goal?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            <strong>{deleting.name}</strong> and all its progress will be permanently deleted.
          </p>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Deleting…' : 'Delete goal'}
            </Button>
          </div>
        </Modal>
      )}

      {viewHistory && (
        <ContributionHistoryModal goal={viewHistory} onClose={() => setViewHistory(null)} />
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
    gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))',
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
  cardName: { fontSize: 16, fontWeight: 600, color: 'var(--white)', marginBottom: 3 },
  accountBadge: { fontSize: 12, color: 'var(--cyan)' },
  statusBadge: {
    fontSize: 11, fontWeight: 600, padding: '2px 8px',
    borderRadius: 99, whiteSpace: 'nowrap',
  },
  iconBtn: {
    background: 'none', border: 'none', color: 'var(--muted)',
    fontSize: 15, padding: '3px 5px', borderRadius: 'var(--radius)', cursor: 'pointer',
  },
  statsGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)',
    gap: 8, marginBottom: 12,
  },
  statCell: { display: 'flex', flexDirection: 'column', gap: 3 },
  statLabel: { fontSize: 11, color: 'var(--muted)', fontWeight: 500 },
  projectionRow: {
    display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)',
    gap: 8, paddingTop: 10, borderTop: '1px solid var(--border)',
  },
  projCell:  { display: 'flex', flexDirection: 'column', gap: 3 },
  projLabel: { fontSize: 11, color: 'var(--muted)', fontWeight: 500 },
  projValue: { fontSize: 13, fontWeight: 600, color: 'var(--white)' },
  sectionHeader: {
    fontSize: 14, fontWeight: 600, color: 'var(--muted)',
    textTransform: 'uppercase', letterSpacing: '0.06em',
    marginBottom: 12, paddingBottom: 8, borderBottom: '1px solid var(--border)',
  },
  notes: {
    fontSize: 12, color: 'var(--muted)', marginTop: 10,
    paddingTop: 10, borderTop: '1px solid var(--border)',
  },
  empty: { textAlign: 'center', padding: '60px 0' },
  emptyTitle: { fontSize: 18, fontWeight: 600, color: 'var(--white)', marginBottom: 8 },
  modalError: { color: 'var(--red)', fontSize: 13, marginBottom: 12 },
}

const savingsHistoryStyles = {
  header: {
    display: 'grid', gridTemplateColumns: '120px 100px 120px 1fr',
    padding: '8px 12px', background: 'var(--bg)',
    fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
    letterSpacing: '0.06em', color: 'var(--muted)',
    borderBottom: '1px solid var(--border)',
  },
  row: {
    display: 'grid', gridTemplateColumns: '120px 100px 120px 1fr',
    padding: '10px 12px', alignItems: 'center',
    borderBottom: '1px solid var(--border)',
  },
}
