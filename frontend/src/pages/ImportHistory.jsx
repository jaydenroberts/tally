import { useEffect, useState } from 'react'
import client from '../api/client'
import { formatDate } from '../utils/dateFormat'

// ─── Status badge ─────────────────────────────────────────────────────────────

function StatusBadge({ status }) {
  const map = {
    success: { color: '#50FA7B', label: 'Success' },
    partial: { color: '#FFB86C', label: 'Partial' },
    failed:  { color: '#FF5555', label: 'Failed'  },
  }
  const { color, label } = map[status] ?? { color: '#6272A4', label: status ?? '—' }
  return (
    <span style={{
      fontSize: 11, fontWeight: 600, padding: '2px 8px',
      borderRadius: 99, color, background: color + '20',
      whiteSpace: 'nowrap',
    }}>
      {label}
    </span>
  )
}

// ─── File type badge ──────────────────────────────────────────────────────────

function TypeBadge({ type }) {
  const color = type === 'pdf' ? '#BD93F9' : '#8BE9FD'   // purple : cyan
  return (
    <span style={{
      fontSize: 10, fontWeight: 700, padding: '1px 6px',
      borderRadius: 4, color, background: color + '20',
      textTransform: 'uppercase', letterSpacing: '0.05em',
    }}>
      {type ?? '—'}
    </span>
  )
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function ImportHistory() {
  const [logs, setLogs]       = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError]     = useState('')

  useEffect(() => {
    client.get('/import/logs')
      .then((r) => setLogs(r.data))
      .catch(() => setError('Failed to load import history'))
      .finally(() => setLoading(false))
  }, [])

  const successCount = logs.filter((l) => l.status === 'success').length
  const totalTx      = logs.reduce((s, l) => s + (l.transaction_count ?? 0), 0)

  return (
    <div>
      {/* Header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.pageTitle}>Import History</h1>
          {logs.length > 0 && (
            <p style={styles.pageSubtitle}>
              {logs.length} import{logs.length !== 1 ? 's' : ''} ·{' '}
              {successCount} successful ·{' '}
              {totalTx} transactions processed
            </p>
          )}
        </div>
      </div>

      {error && <p style={{ color: 'var(--red)', marginBottom: 16 }}>{error}</p>}

      {loading ? (
        <p style={{ color: 'var(--muted)' }}>Loading…</p>
      ) : logs.length === 0 ? (
        <div style={styles.empty}>
          <p style={styles.emptyTitle}>No imports yet</p>
          <p style={{ color: 'var(--muted)', fontSize: 14 }}>
            Import a CSV or PDF bank statement from the Transactions page to get started.
          </p>
        </div>
      ) : (
        <div style={styles.tableWrap}>
          {/* Table header */}
          <div style={styles.tableHeader}>
            <span>File</span>
            <span>Type</span>
            <span>Imported</span>
            <span>Transactions</span>
            <span>Status</span>
          </div>

          {logs.map((log, i) => (
            <div key={log.id} style={{
              ...styles.tableRow,
              borderBottom: i < logs.length - 1 ? '1px solid var(--border)' : 'none',
            }}>
              {/* Filename */}
              <div style={{ minWidth: 0 }}>
                <p style={styles.filename} title={log.filename}>
                  {log.filename}
                </p>
                {log.error_detail && (
                  <p style={styles.errorDetail}>{log.error_detail}</p>
                )}
              </div>

              {/* Type */}
              <div>
                <TypeBadge type={log.file_type} />
              </div>

              {/* Date */}
              <div>
                <p style={styles.date}>
                  {formatDate(new Date(log.imported_at))}
                </p>
                <p style={styles.time}>
                  {new Date(log.imported_at).toLocaleTimeString('en-US', {
                    hour: '2-digit', minute: '2-digit',
                  })}
                </p>
              </div>

              {/* Transaction count */}
              <div>
                <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--white)' }}>
                  {log.transaction_count ?? 0}
                </span>
              </div>

              {/* Status */}
              <div>
                <StatusBadge status={log.status} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

const styles = {
  pageHeader: {
    marginBottom: 24,
  },
  pageTitle:    { fontSize: 24, fontWeight: 700, color: 'var(--white)' },
  pageSubtitle: { color: 'var(--muted)', fontSize: 14, marginTop: 4 },
  tableWrap: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    overflow: 'hidden',
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '1fr 60px 140px 120px 90px',
    padding: '10px 20px',
    background: 'var(--bg)',
    fontSize: 11, fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: 'var(--muted)',
    borderBottom: '1px solid var(--border)',
  },
  tableRow: {
    display: 'grid',
    gridTemplateColumns: '1fr 60px 140px 120px 90px',
    padding: '14px 20px',
    alignItems: 'center',
  },
  filename: {
    fontSize: 13, fontWeight: 500, color: 'var(--white)',
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  errorDetail: {
    fontSize: 11, color: 'var(--orange)', marginTop: 4,
    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
  },
  date: { fontSize: 13, color: 'var(--white)' },
  time: { fontSize: 11, color: 'var(--muted)', marginTop: 2 },
  empty: { textAlign: 'center', padding: '60px 0' },
  emptyTitle: { fontSize: 18, fontWeight: 600, color: 'var(--white)', marginBottom: 8 },
}
