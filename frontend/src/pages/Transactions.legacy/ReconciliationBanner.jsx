import { useCurrency } from '../../context/CurrencyContext'

const bannerStyle = {
  wrap: {
    background: 'var(--bg-elevated)',
    border: '1px solid var(--info)',
    borderRadius: 'var(--radius-lg)',
    padding: '14px 18px',
    marginBottom: 20,
  },
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    marginBottom: 6,
  },
  stats: {
    display: 'flex',
    gap: 20,
    fontSize: 13,
    flexWrap: 'wrap',
  },
  close: {
    background: 'none',
    border: 'none',
    color: 'var(--text-muted)',
    cursor: 'pointer',
    fontSize: 14,
  },
}

export default function ReconciliationBanner({ summary, onDismiss }) {
  const { formatCurrency } = useCurrency()
  if (!summary) return null
  const { matched_count, new_from_bank_count, estimates_pending, amount_diff_warnings } = summary
  return (
    <div style={bannerStyle.wrap}>
      <div style={bannerStyle.row}>
        <strong style={{ color: 'var(--info)' }}>Import complete</strong>
        <button style={bannerStyle.close} onClick={onDismiss}>✕</button>
      </div>
      <div style={bannerStyle.stats}>
        <span style={{ color: 'var(--positive)' }}>✓ {matched_count} matched</span>
        <span style={{ color: 'var(--info)' }}>+ {new_from_bank_count} new from bank</span>
        {estimates_pending > 0 && (
          <span style={{ color: 'var(--accent)' }}>~ {estimates_pending} estimates still pending</span>
        )}
      </div>
      {amount_diff_warnings.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <p style={{ fontSize: 12, color: 'var(--warning)', marginBottom: 4 }}>
            Amount differences found:
          </p>
          {amount_diff_warnings.map((w) => (
            <p key={w.transaction_id} style={{ fontSize: 12, color: 'var(--text-muted)' }}>
              · {w.description ?? 'Transaction'}: you estimated {formatCurrency(w.manual_amount)},
              bank says {formatCurrency(w.bank_amount)}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}
