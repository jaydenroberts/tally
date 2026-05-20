import { useEffect, useMemo, useState } from 'react'
import { useNavigate, useSearchParams } from 'react-router-dom'
import client from '../api/client'
import { useCurrency } from '../context/CurrencyContext'
import useBreakpoint from '../hooks/useBreakpoint'
import Button from '../components/Button'
import Modal from '../components/Modal'
import PageHeader from '../components/PageHeader'
import { formatDate } from '../utils/dateFormat'

import AddTransactionForm   from './Transactions.legacy/AddTransactionForm'

const PAGE_SIZE = 50

// ─── Category dot colors ─────────────────────────────────────────────────────
const CAT_COLOR = {
  Groceries:     'var(--chart-1)',
  Dining:        'var(--chart-5)',
  Transport:     'var(--chart-2)',
  Rent:          'var(--chart-4)',
  Utilities:     'var(--chart-6)',
  Entertainment: 'var(--chart-3)',
  Salary:        'var(--positive)',
  Transfer:      'var(--text-faint)',
  Health:        'var(--info)',
  Subscriptions: 'var(--accent)',
}

const KIND_COLOR = {
  goal: 'var(--positive)',
  debt: 'var(--warning)',
}

// ─── Pill ────────────────────────────────────────────────────────────────────
function Pill({ children, tone = 'neutral' }) {
  const tones = {
    neutral:  { bg: 'var(--bg-hover)',                                          fg: 'var(--text-muted)', ring: 'var(--border)' },
    positive: { bg: 'color-mix(in oklab, var(--positive) 15%, transparent)',    fg: 'var(--positive)',   ring: 'color-mix(in oklab, var(--positive) 35%, transparent)' },
    negative: { bg: 'color-mix(in oklab, var(--negative) 15%, transparent)',    fg: 'var(--negative)',   ring: 'color-mix(in oklab, var(--negative) 35%, transparent)' },
    warning:  { bg: 'color-mix(in oklab, var(--warning) 15%, transparent)',     fg: 'var(--warning)',    ring: 'color-mix(in oklab, var(--warning) 35%, transparent)' },
    info:     { bg: 'color-mix(in oklab, var(--info) 15%, transparent)',        fg: 'var(--info)',       ring: 'color-mix(in oklab, var(--info) 35%, transparent)' },
  }
  const t = tones[tone]
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 9px', borderRadius: 999,
      background: t.bg, color: t.fg, fontSize: 11, fontWeight: 600,
      border: `1px solid ${t.ring}`, lineHeight: 1.4, whiteSpace: 'nowrap',
    }}>{children}</span>
  )
}

// ─── Page header ─────────────────────────────────────────────────────────────
// ─── Filter bar ──────────────────────────────────────────────────────────────
const SEGMENTS = ['All', 'Unverified', 'Income', 'Expenses', 'Transfers']

function FilterBar({ segment, onSegmentChange, unverifiedCount, selectedSum, selectedCount, onBulkDelete, onClearSelection }) {
  const { formatCurrency } = useCurrency()
  return (
    <div style={{
      display: 'flex', gap: 8, padding: 10, alignItems: 'center', flexWrap: 'wrap',
      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
      borderRadius: 10,
    }}>
      {SEGMENTS.map(s => {
        const active     = s === segment
        const unverified = s === 'Unverified'
        return (
          <button
            key={s}
            onClick={() => onSegmentChange(s)}
            style={{
              padding: '5px 12px', borderRadius: 7, fontSize: 12, fontWeight: 600,
              cursor: 'pointer',
              background:
                active && unverified ? 'color-mix(in oklab, var(--warning) 18%, transparent)' :
                active                ? 'var(--bg-hover)' :
                                        'transparent',
              color:
                active && unverified ? 'var(--warning)' :
                active                ? 'var(--text)' :
                                        'var(--text-muted)',
              border:
                active && unverified
                  ? '1px solid color-mix(in oklab, var(--warning) 35%, transparent)'
                  : '1px solid transparent',
            }}
          >
            {s}{unverified && unverifiedCount > 0 && ` · ${unverifiedCount}`}
          </button>
        )
      })}

      <div style={{ flex: 1 }}/>

      {selectedCount > 0 && (
        <>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{selectedCount} selected</span>
          <button
            onClick={onClearSelection}
            style={{
              padding: '5px 10px', borderRadius: 7, fontSize: 12, fontWeight: 600, cursor: 'pointer',
              background: 'transparent', color: 'var(--text-muted)', border: '1px solid var(--border)',
            }}
          >
            Clear
          </button>
          <button
            onClick={onBulkDelete}
            style={{
              padding: '5px 12px', borderRadius: 7, fontSize: 12, fontWeight: 600, cursor: 'pointer',
              background: 'color-mix(in oklab, var(--negative) 18%, transparent)', color: 'var(--negative)',
              border: '1px solid color-mix(in oklab, var(--negative) 35%, transparent)',
            }}
          >
            Delete {selectedCount}
          </button>
        </>
      )}

      <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>
        Sum selected:&nbsp;
        <span style={{ color: 'var(--text)', fontWeight: 600, fontVariantNumeric: 'tabular-nums' }}>
          {formatCurrency(selectedSum)}
        </span>
      </span>
    </div>
  )
}

// ─── Stats strip ─────────────────────────────────────────────────────────────
function StatsStrip({ stats }) {
  const { formatCurrency } = useCurrency()
  const cards = [
    { label: 'Income (MTD)',   value: formatCurrency(stats.incomeMtd),   tone: 'var(--positive)', signed: true },
    { label: 'Expenses (MTD)', value: formatCurrency(stats.expensesMtd), tone: 'var(--text)' },
    { label: 'Net (MTD)',      value: formatCurrency(stats.netMtd),      tone: stats.netMtd >= 0 ? 'var(--positive)' : 'var(--negative)', signed: true },
    { label: 'Unverified',     value: `${stats.unverifiedCount} items`,  tone: stats.unverifiedCount > 0 ? 'var(--warning)' : 'var(--text-faint)' },
  ]
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12 }}>
      {cards.map(c => (
        <div key={c.label} style={{
          background: 'var(--bg-elevated)', border: '1px solid var(--border)',
          borderRadius: 10, padding: '12px 16px',
        }}>
          <div style={{
            fontSize: 11, color: 'var(--text-faint)', fontWeight: 600,
            textTransform: 'uppercase', letterSpacing: '0.06em',
          }}>{c.label}</div>
          <div style={{
            fontSize: 20, fontWeight: 700, color: c.tone, marginTop: 4,
            fontVariantNumeric: 'tabular-nums', letterSpacing: '-0.01em',
          }}>{c.signed && !c.value.startsWith('-') ? '+' : ''}{c.value}</div>
        </div>
      ))}
    </div>
  )
}

// ─── Single row ──────────────────────────────────────────────────────────────
const ROW_GRID = '34px 80px 1fr 130px 140px 170px 90px 120px'

function TxRow({ tx, isHover, onHover, onSelect, selected, onLink, onOpen, onDelete }) {
  const { formatCurrency } = useCurrency()
  const verified = tx.is_verified
  const transfer = tx.transaction_type === 'transfer'

  return (
    <div
      className="tx-table-row"
      onMouseEnter={() => onHover(tx.id)}
      onMouseLeave={() => onHover(null)}
      onClick={() => onOpen(tx)}
      style={{
        display: 'grid', gridTemplateColumns: ROW_GRID,
        padding: '12px 18px',
        borderBottom: '1px solid var(--border)',
        alignItems: 'center', fontSize: 13, position: 'relative',
        cursor: 'pointer',
        background:
          isHover                ? 'var(--bg-hover)' :
          !verified && !transfer ? 'color-mix(in oklab, var(--warning) 5%, transparent)' :
                                   'transparent',
      }}
    >
      <input
        type="checkbox"
        checked={selected}
        onChange={e => onSelect(tx.id, e.target.checked, e.nativeEvent.shiftKey)}
        onClick={e => e.stopPropagation()}
        style={{ width: 14, height: 14, accentColor: 'var(--brand)' }}
      />

      <span style={{ color: 'var(--text-faint)', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>
        {formatDate(tx.date, 'short')}
      </span>

      <span style={{ color: 'var(--text)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {tx.description}
      </span>

      <CategoryChip category={tx.category_name}/>

      <span style={{ color: 'var(--text-muted)', fontSize: 12, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {tx.account_name}
      </span>

      <LinkedToCell tx={tx} isHover={isHover} onLink={onLink}/>

      <span style={{ textAlign: 'center' }}>
        {transfer ? <Pill tone="neutral">Transfer</Pill>
         : verified ? <Pill tone="positive">✓ Verified</Pill>
         :            <Pill tone="warning">Review</Pill>}
      </span>

      <span style={{
        textAlign: 'right', fontWeight: 700, fontVariantNumeric: 'tabular-nums',
        color: tx.amount >= 0 ? 'var(--positive)' : 'var(--text)',
      }}>{formatCurrency(tx.amount)}</span>

      {isHover && <HoverActionRail tx={tx} onLink={onLink} onDelete={onDelete}/>}
    </div>
  )
}

function CategoryChip({ category }) {
  if (!category) {
    return <span style={{ color: 'var(--text-faint)', fontSize: 11 }}>—</span>
  }
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6,
      padding: '3px 8px', borderRadius: 6, fontSize: 12,
      background: 'var(--bg-hover)', color: 'var(--text-muted)',
      justifySelf: 'start', maxWidth: '100%',
    }}>
      <span style={{
        width: 7, height: 7, borderRadius: 2,
        background: CAT_COLOR[category] || 'var(--text-faint)',
      }}/>
      {category}
    </span>
  )
}

function LinkedToCell({ tx, isHover, onLink }) {
  if (tx.link) {
    const color = KIND_COLOR[tx.link.kind] ?? 'var(--text-faint)'
    return (
      <span style={{
        display: 'inline-flex', alignItems: 'center', gap: 6,
        padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 600,
        background: `color-mix(in oklab, ${color} 14%, transparent)`,
        color,
        border: `1px solid color-mix(in oklab, ${color} 30%, transparent)`,
        maxWidth: '100%',
        overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
      }}>
        {tx.link.kind === 'goal' ? '🎯' : '◎'} {tx.link.name}
      </span>
    )
  }
  if (isHover) {
    return (
      <span
        onClick={e => { e.stopPropagation(); onLink(tx) }}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 5,
          padding: '3px 8px', borderRadius: 6, fontSize: 11, fontWeight: 500,
          border: '1px dashed var(--border)', color: 'var(--text-faint)',
          cursor: 'pointer',
        }}>
        + Link
      </span>
    )
  }
  return <span style={{ color: 'var(--text-faint)', fontSize: 11 }}>—</span>
}

function HoverActionRail({ tx, onLink, onDelete }) {
  const actions = [
    { key: 'goal', icon: '🎯', label: 'Link to goal', tone: 'var(--positive)' },
    { key: 'debt', icon: '◎',  label: 'Link to debt', tone: 'var(--warning)' },
    { key: 'open', icon: '›',  label: 'Open',         tone: 'var(--text-muted)' },
  ]
  return (
    <div
      onClick={e => e.stopPropagation()}
      style={{
        position: 'absolute', right: 12, top: '50%', transform: 'translateY(-50%)',
        display: 'flex', gap: 4, padding: 4,
        background: 'var(--bg-elevated)', border: '1px solid var(--border)',
        borderRadius: 8, boxShadow: '0 4px 14px rgba(0,0,0,0.25)',
      }}>
      {actions.map(a => (
        <button
          key={a.key}
          title={a.label}
          onClick={() => onLink(tx, a.key)}
          style={{
            width: 26, height: 26, borderRadius: 6, border: 'none',
            display: 'grid', placeItems: 'center',
            background: 'var(--bg-hover)', color: a.tone, cursor: 'pointer',
            fontSize: 13,
          }}>
          {a.icon}
        </button>
      ))}
      <button
        title="Delete transaction"
        onClick={() => onDelete(tx)}
        style={{
          width: 26, height: 26, borderRadius: 6, border: 'none',
          display: 'grid', placeItems: 'center',
          background: 'var(--bg-hover)', color: 'var(--negative)', cursor: 'pointer',
          fontSize: 13,
        }}>
        🗑
      </button>
    </div>
  )
}

// ─── Table ───────────────────────────────────────────────────────────────────
function TxTable({ rows, hoverId, onHover, selectedIds, onSelect, onSelectAll, onDelete, onOpen, onLink }) {
  const allSelected  = rows.length > 0 && rows.every(r => selectedIds.has(r.id))
  const someSelected = rows.some(r => selectedIds.has(r.id))
  return (
    <div className="table-scroll" style={{
      background: 'var(--bg-elevated)', border: '1px solid var(--border)',
      borderRadius: 10, overflow: 'hidden',
    }}>
      <div className="tx-table-header" style={{
        display: 'grid', gridTemplateColumns: ROW_GRID,
        padding: '10px 18px', background: 'var(--bg)',
        borderBottom: '1px solid var(--border)',
        fontSize: 10, fontWeight: 700, color: 'var(--text-faint)',
        textTransform: 'uppercase', letterSpacing: '0.08em',
      }}>
        <input
          type="checkbox"
          checked={allSelected}
          ref={el => { if (el) el.indeterminate = someSelected && !allSelected }}
          onChange={e => onSelectAll(e.target.checked)}
          title={allSelected ? 'Deselect all' : 'Select all'}
          style={{ width: 14, height: 14, accentColor: 'var(--brand)', cursor: 'pointer' }}
        />
        <span>Date</span>
        <span>Description</span>
        <span>Category</span>
        <span>Account</span>
        <span>Linked to</span>
        <span style={{ textAlign: 'center' }}>Status</span>
        <span style={{ textAlign: 'right' }}>Amount</span>
      </div>
      {rows.map(tx => (
        <TxRow
          key={tx.id}
          tx={tx}
          isHover={hoverId === tx.id}
          selected={selectedIds.has(tx.id)}
          onHover={onHover}
          onSelect={onSelect}
          onOpen={onOpen}
          onLink={onLink}
          onDelete={onDelete}
        />
      ))}
      {rows.length === 0 && (
        <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-faint)', fontSize: 13 }}>
          No transactions match these filters.
        </div>
      )}
    </div>
  )
}

// ─── Add allocation picker ───────────────────────────────────────────────────
// Lists all available goals + debts that aren't already in the current allocation
// set. Click one to append. Withdrawals (debit tx → goal) are surfaced.
function AddAllocationPicker({ tx, currentRefs, goals, debts, defaultAmount, onAdd, onClose }) {
  const { formatCurrency } = useCurrency()
  const isDebit = tx.amount < 0

  // Withdrawals (debit + goal) ARE allowed against completed goals — the
  // backend handles this by un-completing the goal as the balance drops.
  const availableGoals = goals.filter(g =>
    !currentRefs.has(`goal:${g.id}`) && (isDebit || !g.is_completed)
  )
  // Debt allocations only valid on debit transactions, max one debt per tx
  const hasDebtAlready = [...currentRefs].some(r => r.startsWith('debt:'))
  const availableDebts = isDebit && !hasDebtAlready
    ? debts.filter(d => !d.is_paid_off)
    : []

  const itemRow = (kind, item) => (
    <button
      key={`${kind}:${item.id}`}
      onClick={() => onAdd({
        kind,
        ref_id: item.id,
        name: item.name,
        amount: defaultAmount,
      })}
      style={{
        display: 'flex', alignItems: 'center', gap: 12,
        width: '100%', padding: '10px 12px', marginBottom: 6,
        background: 'var(--bg)', border: '1px solid var(--border)',
        borderRadius: 8, cursor: 'pointer', textAlign: 'left',
      }}
    >
      <span style={{ width: 10, height: 10, borderRadius: 999, background: KIND_COLOR[kind] }}/>
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 13, color: 'var(--text)', fontWeight: 600 }}>{item.name}</div>
        {kind === 'goal' && (
          <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            {formatCurrency(item.current_amount)} of {formatCurrency(item.target_amount)}
          </div>
        )}
        {kind === 'debt' && (
          <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>
            Balance {formatCurrency(item.current_balance)}
          </div>
        )}
      </div>
      <span style={{ fontSize: 11, color: 'var(--text-faint)' }}>+ Add</span>
    </button>
  )

  return (
    <Modal title="Add allocation" onClose={onClose} width={420}>
      {availableGoals.length === 0 && availableDebts.length === 0 && (
        <p style={{ color: 'var(--text-faint)', fontSize: 13 }}>
          No goals or debts available to link. {isDebit
            ? 'A debit can only link to one debt at a time, and goals must not be completed.'
            : 'Goals must not be already linked here or completed.'}
        </p>
      )}

      {availableGoals.length > 0 && (
        <>
          <h4 style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-faint)',
            textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8,
          }}>
            Savings goals {isDebit && <span style={{ textTransform: 'none', color: 'var(--warning)', fontWeight: 500 }}> · linking will withdraw</span>}
          </h4>
          {availableGoals.map(g => itemRow('goal', g))}
        </>
      )}

      {availableDebts.length > 0 && (
        <>
          <h4 style={{
            fontSize: 11, fontWeight: 700, color: 'var(--text-faint)',
            textTransform: 'uppercase', letterSpacing: '0.06em', marginTop: 14, marginBottom: 8,
          }}>Debt accounts</h4>
          {availableDebts.map(d => itemRow('debt', d))}
        </>
      )}
    </Modal>
  )
}

// ─── Link drawer ─────────────────────────────────────────────────────────────
function LinkDrawer({ tx, goals, debts, categories = [], onClose, onSaveAllocations, onUpdateCategory, isMobile = false }) {
  const { formatCurrency } = useCurrency()
  const [catSaving, setCatSaving] = useState(false)
  const [catError, setCatError] = useState(null)
  // Initial allocations come from the API (TransactionResponse.allocations).
  // Magnitude only — the backend infers direction from tx.amount sign.
  const initialAllocations = useMemo(
    () => (tx?.allocations ?? []).map(a => ({
      kind: a.kind,
      ref_id: a.ref_id,
      name: a.name,
      amount: Math.abs(a.amount),
    })),
    [tx],
  )
  const [allocations, setAllocations] = useState(initialAllocations)
  const [showPicker, setShowPicker] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState(null)

  if (!tx) return null

  const allocated = allocations.reduce((a, x) => a + x.amount, 0)
  const total     = Math.abs(tx.amount)
  const remaining = Math.max(0, total - allocated)
  const overSpent = allocated - total > 0.01

  const currentRefs = new Set(allocations.map(a => `${a.kind}:${a.ref_id}`))

  const isDirty = JSON.stringify(initialAllocations) !== JSON.stringify(allocations)
  const canSave = !saving && !overSpent && isDirty

  const handleSave = async () => {
    setSaving(true)
    setSaveError(null)
    try {
      await onSaveAllocations(tx, allocations)
    } catch (e) {
      setSaveError(e?.response?.data?.detail ?? e?.message ?? 'Save failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <aside style={isMobile ? {
      position: 'fixed', inset: 0, zIndex: 300,
      background: 'var(--bg-elevated)',
      display: 'flex', flexDirection: 'column',
      overflowY: 'auto',
    } : {
      position: 'fixed', top: 0, right: 0, bottom: 0, width: 420, zIndex: 300,
      background: 'var(--bg-elevated)', borderLeft: '1px solid var(--border)',
      display: 'flex', flexDirection: 'column', overflowY: 'auto',
    }}>
      <header style={{
        padding: '20px 24px', borderBottom: '1px solid var(--border)',
        display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between',
      }}>
        <div>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            Linking
          </div>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)', marginTop: 4 }}>
            {tx.description}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-faint)', marginTop: 2 }}>
            {formatDate(tx.date)} · {tx.account_name} · {formatCurrency(tx.amount)}
          </div>
          {tx.amount < 0 && (
            <div style={{ fontSize: 11, color: 'var(--warning)', marginTop: 6 }}>
              Debit transaction — goal allocations will count as withdrawals.
            </div>
          )}
        </div>
        <button
          onClick={onClose}
          style={{ background: 'none', border: 'none', color: 'var(--text-faint)', cursor: 'pointer', fontSize: 18 }}>
          ✕
        </button>
      </header>

      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 6 }}>
          Category
        </div>
        <select
          value={tx.category_id ?? ''}
          disabled={catSaving || !onUpdateCategory}
          onChange={async (e) => {
            const next = e.target.value
            setCatSaving(true)
            setCatError(null)
            try {
              await onUpdateCategory(tx, next)
            } catch (err) {
              setCatError(err?.response?.data?.detail ?? err?.message ?? 'Update failed')
            } finally {
              setCatSaving(false)
            }
          }}
          style={{
            width: '100%', padding: '8px 10px', fontSize: 14,
            background: 'var(--bg-input)', color: 'var(--text)',
            border: '1px solid var(--border)', borderRadius: 6,
          }}
        >
          <option value="">Uncategorised</option>
          {categories.map(c => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
        {catError && (
          <div style={{ fontSize: 11, color: 'var(--negative)', marginTop: 6 }}>{catError}</div>
        )}
      </div>

      <div style={{ padding: '16px 24px', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 12, marginBottom: 6 }}>
          <span style={{ color: 'var(--text-faint)' }}>Allocated</span>
          <span style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text)' }}>
            {formatCurrency(allocated)} of {formatCurrency(total)}
          </span>
        </div>
        <div style={{ height: 6, borderRadius: 3, background: 'var(--bg-input)', overflow: 'hidden' }}>
          <div style={{
            height: '100%',
            width: `${Math.min(100, total > 0 ? (allocated / total) * 100 : 0)}%`,
            background: overSpent ? 'var(--negative)' : 'var(--positive)',
          }}/>
        </div>
        {overSpent && (
          <div style={{ fontSize: 11, marginTop: 6, color: 'var(--negative)' }}>
            Over-allocated by {formatCurrency(allocated - total)}
          </div>
        )}
        {!overSpent && remaining > 0.01 && (
          <div style={{ fontSize: 11, marginTop: 6, color: 'var(--text-faint)' }}>
            {formatCurrency(remaining)} unallocated
          </div>
        )}
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '16px 24px' }}>
        {allocations.map((a, i) => (
          <AllocationRow
            key={`${a.kind}:${a.ref_id}`}
            allocation={a}
            onChangeAmount={amt => {
              const next = [...allocations]
              next[i] = { ...a, amount: amt }
              setAllocations(next)
            }}
            onRemove={() => setAllocations(allocations.filter((_, j) => j !== i))}
          />
        ))}
        <button
          onClick={() => setShowPicker(true)}
          style={{
            width: '100%', padding: '10px 12px', marginTop: 8,
            border: '1px dashed var(--border)', background: 'transparent',
            borderRadius: 8, color: 'var(--text-faint)', cursor: 'pointer', fontSize: 13,
          }}>
          + Add allocation
        </button>
      </div>

      {saveError && (
        <div style={{
          padding: '10px 24px', background: 'color-mix(in oklab, var(--negative) 12%, transparent)',
          color: 'var(--negative)', fontSize: 12, borderTop: '1px solid var(--border)',
        }}>{saveError}</div>
      )}

      <footer style={{
        padding: '16px 24px', borderTop: '1px solid var(--border)',
        display: 'flex', gap: 10, justifyContent: 'flex-end',
      }}>
        <Button variant="ghost" onClick={onClose}>Cancel</Button>
        <Button variant="primary" onClick={handleSave} disabled={!canSave}>
          {saving ? 'Saving…' : 'Save'}
        </Button>
      </footer>

      {showPicker && (
        <AddAllocationPicker
          tx={tx}
          currentRefs={currentRefs}
          goals={goals}
          debts={debts}
          defaultAmount={Math.round(remaining * 100) / 100 || 0}
          onAdd={(item) => {
            setAllocations([...allocations, item])
            setShowPicker(false)
          }}
          onClose={() => setShowPicker(false)}
        />
      )}
    </aside>
  )
}

function AllocationRow({ allocation, onChangeAmount, onRemove }) {
  const color = KIND_COLOR[allocation.kind] ?? 'var(--text-faint)'
  return (
    <div style={{
      display: 'grid', gridTemplateColumns: '12px 1fr auto auto', gap: 10,
      padding: '10px 12px', marginBottom: 8,
      background: 'var(--bg)', border: '1px solid var(--border)',
      borderRadius: 8, alignItems: 'center',
    }}>
      <span style={{ width: 10, height: 10, borderRadius: 999, background: color }}/>
      <div>
        <div style={{ fontSize: 13, color: 'var(--text)', fontWeight: 600 }}>{allocation.name}</div>
        <div style={{ fontSize: 11, color: 'var(--text-faint)', textTransform: 'capitalize' }}>{allocation.kind}</div>
      </div>
      <input
        type="number"
        step="0.01"
        min="0"
        value={allocation.amount}
        onChange={e => onChangeAmount(parseFloat(e.target.value) || 0)}
        style={{
          width: 90, textAlign: 'right',
          padding: '6px 8px', borderRadius: 6,
          background: 'var(--bg-input)', border: '1px solid var(--border)',
          color: 'var(--text)', fontVariantNumeric: 'tabular-nums', fontSize: 13,
        }}
      />
      <button
        onClick={onRemove}
        style={{ background: 'none', border: 'none', color: 'var(--text-faint)', cursor: 'pointer', fontSize: 14 }}
        title="Remove">
        ✕
      </button>
    </div>
  )
}

// ─── Helpers ─────────────────────────────────────────────────────────────────
function deriveLink(tx, debtMap) {
  // Surface a single primary link for the row "Linked to" cell. Specific debt
  // name (via debtMap) takes precedence; savings_transfer transactions show a
  // generic label since the list endpoint doesn't return per-row goal detail
  // for performance.
  if (tx.debt_id && debtMap[tx.debt_id]) {
    return { kind: 'debt', name: debtMap[tx.debt_id].name }
  }
  if (tx.transaction_type === 'savings_transfer') {
    return { kind: 'goal', name: 'Savings goal' }
  }
  return null
}

function normalizeTx(tx, accountMap, debtMap) {
  return {
    ...tx,
    account_name:  accountMap[tx.account_id] ?? '—',
    category_name: tx.category?.name ?? null,
    link:          deriveLink(tx, debtMap),
  }
}

// FE-011: a segment now maps to backend filter params so paging, counts and stats
// are computed server-side over the whole dataset (not just the loaded page).
function segmentParams(segment) {
  switch (segment) {
    case 'Unverified': return { is_verified: false, exclude_transfers: true }
    case 'Income':     return { amount_sign: 'positive', exclude_transfers: true }
    case 'Expenses':   return { amount_sign: 'negative', exclude_transfers: true }
    case 'Transfers':  return { transaction_type: 'transfer' }
    default:           return {}
  }
}

// First day of the current month, as a YYYY-MM-DD string for the MTD summary window.
function monthStartISO() {
  const now = new Date()
  const d = new Date(now.getFullYear(), now.getMonth(), 1)
  const mm = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${d.getFullYear()}-${mm}-${dd}`
}

// ─── Page controls ─────────────────────────────────────────────────────────
// Numbered pager: Prev / 1 2 3 / Next, 50 per page. Works on mobile (wraps).
// Cross-page select-all is intentionally OUT OF SCOPE — the header checkbox
// selects only the current page (documented in handleSelectAll).
function Pager({ page, pageCount, onPage }) {
  if (pageCount <= 1) return null

  // Windowed page numbers so a 40-page dataset doesn't render 40 buttons.
  const window = []
  const span = 2
  let lo = Math.max(0, page - span)
  let hi = Math.min(pageCount - 1, page + span)
  if (lo > 0) window.push(0, lo > 1 ? '…l' : null)
  for (let i = lo; i <= hi; i++) window.push(i)
  if (hi < pageCount - 1) window.push(hi < pageCount - 2 ? '…r' : null, pageCount - 1)

  const btn = (label, target, active = false, disabled = false) => (
    <button
      key={label}
      onClick={disabled ? undefined : () => onPage(target)}
      disabled={disabled}
      style={{
        minWidth: 34, padding: '6px 10px', borderRadius: 7, fontSize: 12, fontWeight: 600,
        cursor: disabled ? 'default' : 'pointer',
        background: active ? 'var(--bg-hover)' : 'transparent',
        color: disabled ? 'var(--text-faint)' : active ? 'var(--text)' : 'var(--text-muted)',
        border: `1px solid ${active ? 'var(--border)' : 'transparent'}`,
      }}
    >
      {label}
    </button>
  )

  return (
    <div style={{
      display: 'flex', gap: 4, alignItems: 'center', justifyContent: 'center',
      flexWrap: 'wrap', padding: '4px 0',
    }}>
      {btn('‹ Prev', page - 1, false, page === 0)}
      {window.filter(x => x !== null).map((x, i) =>
        typeof x === 'string'
          ? <span key={`gap${i}`} style={{ color: 'var(--text-faint)', padding: '0 4px' }}>…</span>
          : btn(String(x + 1), x, x === page)
      )}
      {btn('Next ›', page + 1, false, page >= pageCount - 1)}
    </div>
  )
}

// ─── Page shell ──────────────────────────────────────────────────────────────
export default function Transactions() {
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const { isMobile } = useBreakpoint()

  const [transactions, setTransactions] = useState([])
  const [accounts,     setAccounts]     = useState([])
  const [categories,   setCategories]   = useState([])
  const [goals,        setGoals]        = useState([])
  const [debts,        setDebts]        = useState([])
  const [loading,      setLoading]      = useState(true)
  const [pageLoading,  setPageLoading]  = useState(false)
  const [error,        setError]        = useState(null)

  const [segment,        setSegment]        = useState('All')
  const [page,           setPage]           = useState(0)         // 0-based; page 0 = rows 1–50
  const [totalCount,     setTotalCount]     = useState(0)         // count for the active segment
  const [stats,          setStats]          = useState({ incomeMtd: 0, expensesMtd: 0, netMtd: 0, unverifiedCount: 0 })
  const [selectedIds,    setSelectedIds]    = useState(new Set())
  const [hoverId,        setHoverId]        = useState(null)
  const [openTx,         setOpenTx]         = useState(null)
  const [openingTxId,    setOpeningTxId]    = useState(null)
  const [showAdd,        setShowAdd]        = useState(false)
  const [savingAdd,      setSavingAdd]      = useState(false)
  const [lastSelectedId, setLastSelectedId] = useState(null)
  const [confirmDelete,  setConfirmDelete]  = useState(null)
  const [deleting,       setDeleting]       = useState(false)

  const pageCount = Math.max(1, Math.ceil(totalCount / PAGE_SIZE))

  // ?action=add → open the add modal immediately, then scrub the param
  useEffect(() => {
    if (searchParams.get('action') === 'add') {
      setShowAdd(true)
      setSearchParams({}, { replace: true })
    }
  }, [])

  const accountMap = useMemo(
    () => Object.fromEntries(accounts.map(a => [a.id, a])),
    [accounts]
  )
  const accountNameMap = useMemo(
    () => Object.fromEntries(accounts.map(a => [a.id, a.name])),
    [accounts]
  )
  const debtMap = useMemo(
    () => Object.fromEntries(debts.map(d => [d.id, d])),
    [debts]
  )

  // One-time load of reference data (accounts/categories/goals/debts) + MTD summary.
  useEffect(() => {
    let ignore = false
    Promise.all([
      client.get('/accounts'),
      client.get('/categories'),
      client.get('/savings'),
      client.get('/debt'),
    ])
      .then(([acctRes, catRes, savRes, debtRes]) => {
        if (ignore) return
        setAccounts(acctRes.data)
        setCategories(catRes.data)
        setGoals(savRes.data)
        setDebts(debtRes.data)
      })
      .catch(e => { if (!ignore) setError(e.message) })
    return () => { ignore = true }
  }, [])

  // FE-011: MTD stat cards reflect the WHOLE month (transfers excluded), computed
  // server-side so they never depend on which page is loaded. `refreshKey` lets
  // mutations (add/delete/allocate) re-pull the summary.
  const [refreshKey, setRefreshKey] = useState(0)
  useEffect(() => {
    let ignore = false
    client.get('/transactions/summary', { params: { date_from: monthStartISO() } })
      .then(({ data }) => {
        if (ignore) return
        setStats({
          incomeMtd: data.income,
          expensesMtd: data.expenses,
          netMtd: data.net,
          unverifiedCount: data.unverified_count,
        })
      })
      .catch(() => {})
    return () => { ignore = true }
  }, [refreshKey])

  // FE-011: fetch the current page + the segment's total count server-side.
  // Re-runs on page/segment change and after mutations (refreshKey).
  useEffect(() => {
    let ignore = false
    setPageLoading(true)
    const params = segmentParams(segment)
    const acctNameMap = Object.fromEntries(accounts.map(a => [a.id, a.name]))
    const dMap        = Object.fromEntries(debts.map(d => [d.id, d]))
    Promise.all([
      client.get('/transactions', { params: { ...params, skip: page * PAGE_SIZE, limit: PAGE_SIZE } }),
      client.get('/transactions/count', { params }),
    ])
      .then(([txRes, countRes]) => {
        if (ignore) return
        const rows = (txRes.data.items ?? txRes.data).map(tx => normalizeTx(tx, acctNameMap, dMap))
        setTransactions(rows)
        setTotalCount(countRes.data.count ?? 0)
      })
      .catch(e => { if (!ignore) setError(e.message) })
      .finally(() => { if (!ignore) { setLoading(false); setPageLoading(false) } })
    return () => { ignore = true }
  }, [segment, page, refreshKey, accounts, debts])

  // The loaded page IS the visible set — all server-side filtering already applied.
  const filtered    = transactions
  const selectedSum = useMemo(
    () => filtered.filter(t => selectedIds.has(t.id)).reduce((a, t) => a + t.amount, 0),
    [filtered, selectedIds]
  )

  // Reset to the first page whenever the segment changes; clear page selection too.
  const handleSegmentChange = (s) => {
    setSegment(s)
    setPage(0)
    setSelectedIds(new Set())
    setLastSelectedId(null)
  }

  const goToPage = (p) => {
    const clamped = Math.max(0, Math.min(p, pageCount - 1))
    if (clamped === page) return
    setPage(clamped)
    setSelectedIds(new Set())   // selection is per-page (cross-page select-all out of scope)
    setLastSelectedId(null)
  }

  const handleSelect = (id, on, shiftKey = false) => {
    // Shift-click extends a range from the last-clicked row to this one,
    // in the currently-filtered visual order.
    if (shiftKey && lastSelectedId != null && lastSelectedId !== id) {
      const ids = filtered.map(t => t.id)
      const a = ids.indexOf(lastSelectedId)
      const b = ids.indexOf(id)
      if (a !== -1 && b !== -1) {
        const [lo, hi] = a < b ? [a, b] : [b, a]
        const next = new Set(selectedIds)
        ids.slice(lo, hi + 1).forEach(rid => on ? next.add(rid) : next.delete(rid))
        setSelectedIds(next)
        setLastSelectedId(id)
        return
      }
    }
    const next = new Set(selectedIds)
    on ? next.add(id) : next.delete(id)
    setSelectedIds(next)
    setLastSelectedId(id)
  }

  // Cross-page select-all is OUT OF SCOPE (FE-011): the header checkbox selects
  // only the rows on the current page. Selecting across all pages would require a
  // server-side bulk-by-filter delete contract that doesn't exist yet.
  const handleSelectAll = (on) => {
    setSelectedIds(on ? new Set(filtered.map(t => t.id)) : new Set())
    setLastSelectedId(null)
  }

  const handleDeleteConfirmed = async () => {
    const ids = confirmDelete?.ids ?? []
    if (ids.length === 0) return
    setDeleting(true)
    try {
      if (ids.length === 1) {
        await client.delete(`/transactions/${ids[0]}`)
      } else {
        await client.delete('/transactions/bulk', {
          params: { ids },
          paramsSerializer: { indexes: null },   // ids=1&ids=2 (FastAPI repeated query)
        })
      }
      const idSet = new Set(ids)
      setSelectedIds(prev => {
        const n = new Set(prev)
        ids.forEach(i => n.delete(i))
        return n
      })
      if (openTx && idSet.has(openTx.id)) setOpenTx(null)
      setConfirmDelete(null)
      // If we just emptied the last page, step back one. Otherwise re-pull.
      if (transactions.length === ids.length && page > 0) {
        setPage(page - 1)
      }
      setRefreshKey(k => k + 1)
    } catch (e) {
      setError(`Delete failed: ${e.response?.data?.detail || e.message}`)
    } finally {
      setDeleting(false)
    }
  }

  // Row open / link click → fetch the full tx (includes allocations) and then
  // surface it in the drawer. Avoids opening a stale-state drawer.
  const handleOpen = async (tx) => {
    setOpeningTxId(tx.id)
    try {
      const { data } = await client.get(`/transactions/${tx.id}`)
      setOpenTx(normalizeTx(data, accountNameMap, debtMap))
    } catch (e) {
      setError(`Failed to load transaction: ${e.message}`)
    } finally {
      setOpeningTxId(null)
    }
  }

  const handleUpdateCategory = async (tx, categoryId) => {
    const { data } = await client.patch(`/transactions/${tx.id}`, {
      category_id: categoryId === '' ? null : Number(categoryId),
    })
    const updated = normalizeTx(data, accountNameMap, debtMap)
    setTransactions(prev => prev.map(t => t.id === tx.id ? updated : t))
    setOpenTx(updated)
  }

  const handleSaveAllocations = async (tx, allocations) => {
    // Drawer sends magnitudes; backend infers direction from tx.amount sign
    const payload = {
      allocations: allocations.map(a => ({
        kind: a.kind, ref_id: a.ref_id, amount: Math.abs(a.amount),
      })),
    }
    const { data } = await client.patch(`/transactions/${tx.id}/allocations`, payload)
    const updated = normalizeTx(data, accountNameMap, debtMap)
    setTransactions(prev => prev.map(t => t.id === tx.id ? updated : t))
    // Refresh debts/goals so changed balances show on the next picker open. Setting
    // debts also re-pulls the current page; bump refreshKey for the MTD summary
    // (allocation may have re-typed the row, changing the segment totals).
    const [savRes, debtRes] = await Promise.all([client.get('/savings'), client.get('/debt')])
    setGoals(savRes.data)
    setDebts(debtRes.data)
    setRefreshKey(k => k + 1)
    setOpenTx(null)
  }

  const handleAddSave = async (payload) => {
    setSavingAdd(true)
    try {
      if (payload._isTransfer) {
        const { _isTransfer, ...body } = payload
        await client.post('/transactions/transfer', body)
      } else {
        await client.post('/transactions', payload)
      }
      setShowAdd(false)
      // Jump to page 1 (newest-first sort puts the new row at the top) and re-pull.
      setPage(0)
      setRefreshKey(k => k + 1)
    } finally {
      setSavingAdd(false)
    }
  }

  if (loading) return <div style={{ padding: 32, color: 'var(--text-faint)' }}>Loading…</div>
  if (error)   return <div style={{ padding: 32, color: 'var(--negative)' }}>Error: {error}</div>

  return (
    <>
      <PageHeader
        title="Transactions"
        subtitle={<>
          {totalCount.toLocaleString()} {segment === 'All' ? '' : `${segment.toLowerCase()} `}across {accounts.length} accounts
          {stats.unverifiedCount > 0 && <> · <span style={{ color: 'var(--warning)' }}>{stats.unverifiedCount} need review</span></>}
        </>}
        isMobile={isMobile}
        actions={<>
          <Button variant="secondary" onClick={() => navigate('/import')}>Import</Button>
          <Button variant="primary"   onClick={() => setShowAdd(true)}>+ Add</Button>
        </>}
      />

      <div style={isMobile
        ? { padding: '0 0 24px', display: 'grid', gap: 16, minWidth: 0 }
        : { display: 'grid', alignContent: 'start', gap: 18 }
      }>
          <FilterBar
            segment={segment}
            onSegmentChange={handleSegmentChange}
            unverifiedCount={stats.unverifiedCount}
            selectedSum={selectedSum}
            selectedCount={selectedIds.size}
            onBulkDelete={() => setConfirmDelete({ ids: [...selectedIds] })}
            onClearSelection={() => { setSelectedIds(new Set()); setLastSelectedId(null) }}
          />

          <StatsStrip stats={stats}/>

          <TxTable
            rows={filtered}
            hoverId={hoverId}
            onHover={setHoverId}
            selectedIds={selectedIds}
            onSelect={handleSelect}
            onSelectAll={handleSelectAll}
            onDelete={(tx) => setConfirmDelete({ ids: [tx.id] })}
            onOpen={handleOpen}
            onLink={handleOpen}
          />

          {/* FE-011: numbered pager under the table. Hidden when only one page. */}
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 12, color: 'var(--text-faint)' }}>
              {totalCount === 0
                ? 'No transactions'
                : `${(page * PAGE_SIZE) + 1}–${Math.min((page + 1) * PAGE_SIZE, totalCount)} of ${totalCount.toLocaleString()}`}
              {pageLoading && <span style={{ marginLeft: 8 }}>· loading…</span>}
            </span>
            <Pager page={page} pageCount={pageCount} onPage={goToPage}/>
          </div>

          {openingTxId && (
            <div style={{ position: 'fixed', bottom: 20, right: 20, padding: '10px 14px', background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 8, color: 'var(--text-muted)', fontSize: 12 }}>
              Loading transaction…
            </div>
          )}
      </div>

      {openTx && (
        <LinkDrawer
          key={openTx.id}
          tx={openTx}
          goals={goals}
          debts={debts}
          categories={categories}
          onClose={() => setOpenTx(null)}
          onSaveAllocations={handleSaveAllocations}
          onUpdateCategory={handleUpdateCategory}
          isMobile={isMobile}
        />
      )}

      {showAdd && (
        <Modal title="Add transaction" onClose={() => setShowAdd(false)}>
          <AddTransactionForm
            accounts={accounts}
            categories={categories}
            saving={savingAdd}
            onSave={handleAddSave}
            onCancel={() => setShowAdd(false)}
          />
        </Modal>
      )}

      {confirmDelete && (
        <Modal
          title={`Delete ${confirmDelete.ids.length} transaction${confirmDelete.ids.length > 1 ? 's' : ''}?`}
          onClose={() => !deleting && setConfirmDelete(null)}
        >
          <p style={{ color: 'var(--text-muted)', fontSize: 14, marginBottom: 18 }}>
            {confirmDelete.ids.length === 1
              ? 'This permanently removes the transaction.'
              : `This permanently removes these ${confirmDelete.ids.length} transactions.`}
            {' '}Any debt or savings links are unlinked first. This cannot be undone.
          </p>
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Button variant="secondary" onClick={() => setConfirmDelete(null)} disabled={deleting}>Cancel</Button>
            <Button variant="danger" onClick={handleDeleteConfirmed} disabled={deleting}>
              {deleting ? 'Deleting…' : 'Delete'}
            </Button>
          </div>
        </Modal>
      )}
    </>
  )
}
