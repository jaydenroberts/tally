import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useCurrency } from '../context/CurrencyContext'
import Button from '../components/Button'
import PageHeader from '../components/PageHeader'
import useBreakpoint from '../hooks/useBreakpoint'
import { formatDate, parseServerDate } from '../utils/dateFormat'

// ─── Status pill ─────────────────────────────────────────────────────────────
const STATUS_TONES = {
  committed:    { label: 'Imported',      bg: 'color-mix(in oklab, var(--positive) 15%, transparent)', fg: 'var(--positive)', ring: 'color-mix(in oklab, var(--positive) 35%, transparent)' },
  rolled_back:  { label: 'Rolled back',   bg: 'color-mix(in oklab, var(--text-faint) 18%, transparent)', fg: 'var(--text-faint)', ring: 'var(--border)' },
  cancelled:    { label: 'Cancelled',     bg: 'color-mix(in oklab, var(--text-faint) 18%, transparent)', fg: 'var(--text-faint)', ring: 'var(--border)' },
  preview_ready:{ label: 'Draft',         bg: 'color-mix(in oklab, var(--info) 15%, transparent)',     fg: 'var(--info)',     ring: 'color-mix(in oklab, var(--info) 35%, transparent)' },
  committing:   { label: 'Committing…',   bg: 'color-mix(in oklab, var(--info) 15%, transparent)',     fg: 'var(--info)',     ring: 'color-mix(in oklab, var(--info) 35%, transparent)' },
}

function StatusPill({ status }) {
  const t = STATUS_TONES[status] || STATUS_TONES.cancelled
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5,
      padding: '2px 9px', borderRadius: 999,
      background: t.bg, color: t.fg, fontSize: 11, fontWeight: 600,
      border: `1px solid ${t.ring}`, whiteSpace: 'nowrap',
    }}>{t.label}</span>
  )
}

// ─── Live countdown for the rollback window ──────────────────────────────────
function useSecondsUntil(iso) {
  // FE-003: parse as UTC so the countdown isn't clamped to 0 for UTC+ clients.
  const target = useMemo(() => parseServerDate(iso)?.getTime() ?? 0, [iso])
  const [s, setS] = useState(() => Math.max(0, Math.round((target - Date.now()) / 1000)))
  useEffect(() => {
    if (!target || s <= 0) return
    const id = setInterval(() => setS(Math.max(0, Math.round((target - Date.now()) / 1000))), 500)
    return () => clearInterval(id)
  }, [target, s])
  return s
}

// ─── A single row ────────────────────────────────────────────────────────────
function ImportRow({ row, onRollback, onView }) {
  const remaining = useSecondsUntil(row.rollback_until)
  const canRollback = row.status === 'committed' && remaining > 0
  const displayDate = row.committed_at || row.created_at

  return (
    <div className="ih-table-row" style={{
      display: 'grid', gridTemplateColumns: '160px 1fr 130px 110px 1fr',
      padding: '14px 18px', borderBottom: '1px solid var(--border)',
      alignItems: 'center', fontSize: 13, gap: 12,
    }}>
      {/* When */}
      <div>
        <div style={{ color: 'var(--text)', fontWeight: 600 }}>
          {displayDate ? formatDate(displayDate, 'short') : '—'}
        </div>
        <div style={{ color: 'var(--text-faint)', fontSize: 11, fontVariantNumeric: 'tabular-nums' }}>
          {displayDate ? new Date(displayDate).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }) : ''}
        </div>
      </div>

      {/* Account + filename */}
      <div style={{ minWidth: 0 }}>
        <div style={{ color: 'var(--text)', fontWeight: 500, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {row.account?.name ?? '—'}
        </div>
        <div style={{
          color: 'var(--text-faint)', fontSize: 11,
          fontFamily: 'JetBrains Mono, monospace',
          overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
        }}>{row.filename}</div>
      </div>

      {/* Transaction count */}
      <div style={{ fontVariantNumeric: 'tabular-nums' }}>
        <div style={{ color: row.status === 'committed' ? 'var(--positive)' : 'var(--text-faint)', fontWeight: 600 }}>
          {row.transactions_count ?? 0} added
        </div>
      </div>

      {/* Status */}
      <div><StatusPill status={row.status}/></div>

      {/* Actions */}
      <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
        {canRollback && (
          <button
            onClick={() => onRollback(row)}
            style={{
              padding: '6px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600,
              background: 'color-mix(in oklab, var(--warning) 15%, transparent)',
              border: '1px solid color-mix(in oklab, var(--warning) 35%, transparent)',
              color: 'var(--warning)', cursor: 'pointer',
              display: 'inline-flex', alignItems: 'center', gap: 6,
            }}>
            ↶ Undo · {remaining}s
          </button>
        )}
        {row.status === 'committed' && (
          <button
            onClick={() => onView(row)}
            style={{
              padding: '6px 10px', borderRadius: 6, fontSize: 12,
              background: 'transparent', border: '1px solid var(--border)',
              color: 'var(--text-muted)', cursor: 'pointer',
            }}>
            View
          </button>
        )}
      </div>
    </div>
  )
}

// ─── Page shell ──────────────────────────────────────────────────────────────
export default function ImportHistory() {
  const navigate = useNavigate()
  const { isMobile } = useBreakpoint()

  const [imports, setImports] = useState([])
  const [loading, setLoading] = useState(true)
  const [error,   setError]   = useState(null)
  const [filter,  setFilter]  = useState('all')

  const load = async () => {
    setLoading(true)
    try {
      const { data } = await client.get('/imports')
      setImports(data.items ?? data)
    } catch (e) {
      setError(e.message)
    } finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const filtered = useMemo(() => {
    if (filter === 'all') return imports
    return imports.filter(r => r.status === filter)
  }, [imports, filter])

  const handleRollback = async (row) => {
    const count = row.transactions_count ?? 0
    const acct  = row.account?.name ?? 'this account'
    if (!confirm(`Roll back ${count} transaction${count !== 1 ? 's' : ''} imported into ${acct}?`)) return
    try {
      await client.post(`/imports/${row.id}/rollback`)
      await load()
    } catch (e) {
      alert(e.response?.data?.detail || 'Could not roll back')
    }
  }

  return (
    <>
      <PageHeader
        title="Import history"
        subtitle={`${imports.length} import${imports.length !== 1 ? 's' : ''} · roll back any committed import within 5 min`}
        isMobile={isMobile}
        actions={<Button variant="primary" onClick={() => navigate('/import')}>+ New import</Button>}
      />

      <div style={isMobile
        ? { padding: '0 0 24px', display: 'grid', gap: 16, minWidth: 0 }
        : { display: 'grid', alignContent: 'start', gap: 18 }
      }>
        {/* Filter chips */}
        <div style={{
          display: 'flex', flexWrap: 'wrap', gap: 8, padding: 10, alignItems: 'center',
          background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 10,
        }}>
          {[
            { k: 'all',         label: 'All' },
            { k: 'committed',   label: 'Committed' },
            { k: 'rolled_back', label: 'Rolled back' },
            { k: 'cancelled',   label: 'Cancelled' },
          ].map(f => {
            const active = f.k === filter
            return (
              <button
                key={f.k}
                onClick={() => setFilter(f.k)}
                style={{
                  flex: '1 1 auto', minWidth: 'fit-content',
                  padding: '5px 12px', borderRadius: 7, fontSize: 12, fontWeight: 600,
                  cursor: 'pointer',
                  background: active ? 'var(--bg-hover)' : 'transparent',
                  color:      active ? 'var(--text)'    : 'var(--text-muted)',
                  border: '1px solid transparent',
                }}>
                {f.label}
              </button>
            )
          })}
        </div>

        {/* Table */}
        {loading ? (
          <div style={{ padding: 32, color: 'var(--text-faint)' }}>Loading…</div>
        ) : error ? (
          <div style={{ padding: 32, color: 'var(--negative)' }}>Error: {error}</div>
        ) : (
          <div className="ih-table" style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
            {/* Header row */}
            <div className="ih-table-header" style={{
              display: 'grid', gridTemplateColumns: '160px 1fr 130px 110px 1fr',
              padding: '10px 18px', background: 'var(--bg)',
              borderBottom: '1px solid var(--border)', gap: 12,
              fontSize: 10, fontWeight: 700, color: 'var(--text-faint)',
              textTransform: 'uppercase', letterSpacing: '0.08em',
            }}>
              <span>When</span>
              <span>Account · file</span>
              <span>Added</span>
              <span>Status</span>
              <span style={{ textAlign: 'right' }}>Actions</span>
            </div>
            {filtered.length === 0 ? (
              <div style={{ padding: 60, textAlign: 'center', color: 'var(--text-faint)', fontSize: 13 }}>
                {filter === 'all' ? 'No imports yet.' : `No ${filter.replace('_', ' ')} imports.`}
              </div>
            ) : (
              filtered.map(row => (
                <ImportRow
                  key={row.id}
                  row={row}
                  onRollback={handleRollback}
                  onView={(r) => navigate(`/transactions?import_id=${r.id}`)}
                />
              ))
            )}
          </div>
        )}
      </div>
    </>
  )
}
