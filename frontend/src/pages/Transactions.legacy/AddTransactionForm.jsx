import { useState } from 'react'
import Button from '../../components/Button'
import FormField, { inputStyle, selectStyle } from '../../components/FormField'
import { todayLocalISO } from '../../utils/dateFormat'

const TX_TYPES = [
  { key: 'expense',  label: '− Expense',   accent: 'var(--negative)'   },
  { key: 'income',   label: '+ Income',    accent: 'var(--positive)' },
  { key: 'transfer', label: '↔ Transfer',  accent: 'var(--info)'  },
]

const moreToggleStyle = {
  background: 'none',
  border: 'none',
  color: 'var(--info)',
  fontSize: 13,
  cursor: 'pointer',
  padding: '4px 0',
  marginBottom: 12,
}

export default function AddTransactionForm({ accounts, categories, onSave, onCancel, saving }) {
  const today = todayLocalISO()   // local date, not UTC — avoids saving yesterday (AUDIT-24)

  const [txType, setTxType] = useState('expense')

  const [form, setForm] = useState({
    account_id: accounts[0]?.id ?? '',
    amount: '',
    category_id: '',
    date: today,
    description: '',
    notes: '',
  })

  const [transferForm, setTransferForm] = useState({
    source_account_id: accounts[0]?.id ?? '',
    destination_account_id: accounts[1]?.id ?? '',
    amount: '',
    date: today,
    description: '',
    notes: '',
  })

  const [showMore, setShowMore] = useState(false)
  const [error, setError] = useState('')

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function setTransfer(field) {
    return (e) => setTransferForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()

    if (txType === 'transfer') {
      const amount = parseFloat(transferForm.amount)
      if (isNaN(amount) || amount <= 0) { setError('Transfer amount must be a positive number'); return }
      if (!transferForm.source_account_id) { setError('Select a source account'); return }
      if (!transferForm.destination_account_id) { setError('Select a destination account'); return }
      if (parseInt(transferForm.source_account_id) === parseInt(transferForm.destination_account_id)) {
        setError('Source and destination accounts must be different')
        return
      }
      setError('')
      onSave({
        _isTransfer: true,
        source_account_id: parseInt(transferForm.source_account_id),
        destination_account_id: parseInt(transferForm.destination_account_id),
        amount,
        date: transferForm.date || today,
        description: transferForm.description || null,
        notes: transferForm.notes || null,
      })
      return
    }

    const raw = parseFloat(form.amount)
    if (isNaN(raw) || raw <= 0) { setError('Enter a positive amount'); return }
    if (!form.account_id) { setError('Select an account'); return }
    setError('')
    onSave({
      account_id: parseInt(form.account_id),
      amount: txType === 'expense' ? -raw : raw,
      category_id: form.category_id ? parseInt(form.category_id) : null,
      date: form.date || today,
      description: form.description || null,
      notes: form.notes || null,
      transaction_type: txType,
    })
  }

  const activeAccent = TX_TYPES.find((t) => t.key === txType)?.accent ?? 'var(--info)'

  return (
    <form onSubmit={handleSubmit}>
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {TX_TYPES.map(({ key, label, accent }) => (
          <button
            key={key}
            type="button"
            onClick={() => { setTxType(key); setError('') }}
            style={{
              flex: 1,
              padding: '6px 16px',
              borderRadius: 'var(--radius)',
              border: `1px solid ${txType === key ? accent : 'var(--border)'}`,
              background: txType === key ? `${accent}18` : 'transparent',
              color: txType === key ? accent : 'var(--text-muted)',
              fontSize: 13,
              fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {txType === 'transfer' ? (
        <>
          <FormField label="From account *">
            <select
              style={selectStyle}
              value={transferForm.source_account_id}
              onChange={setTransfer('source_account_id')}
              required
              autoFocus
            >
              <option value="">Select account…</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </FormField>

          <FormField label="To account *">
            <select
              style={selectStyle}
              value={transferForm.destination_account_id}
              onChange={setTransfer('destination_account_id')}
              required
            >
              <option value="">Select account…</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </FormField>

          <FormField label="Amount *" hint="Enter the transfer amount (positive)">
            <input
              style={inputStyle}
              type="number"
              step="0.01"
              placeholder="100.00"
              value={transferForm.amount}
              onChange={setTransfer('amount')}
              required
              inputMode="decimal"
            />
          </FormField>

          <FormField label="Date">
            <input style={inputStyle} type="date" value={transferForm.date} onChange={setTransfer('date')} />
          </FormField>

          <FormField label="Description">
            <input style={inputStyle} value={transferForm.description} onChange={setTransfer('description')} placeholder="e.g. Move savings" />
          </FormField>

          <FormField label="Notes">
            <textarea style={{ ...inputStyle, resize: 'vertical', minHeight: 60 }} value={transferForm.notes} onChange={setTransfer('notes')} />
          </FormField>

          {error && <p style={{ color: 'var(--negative)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
            Transfers create a <span style={{ color: 'var(--info)' }}>linked pair</span> of transactions and are excluded from budget calculations.
          </p>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Button variant="secondary" onClick={onCancel}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Create transfer'}</Button>
          </div>
        </>
      ) : (
        <>
          <FormField label="Account *">
            <select style={selectStyle} value={form.account_id} onChange={set('account_id')} required autoFocus>
              <option value="">Select account…</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </FormField>

          <FormField label="Amount *">
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ color: activeAccent, fontWeight: 700, fontSize: 18, lineHeight: 1, userSelect: 'none' }}>
                {txType === 'expense' ? '−' : '+'}
              </span>
              <input
                style={{ ...inputStyle, flex: 1 }}
                type="number"
                step="0.01"
                min="0.01"
                placeholder="45.00"
                value={form.amount}
                onChange={set('amount')}
                required
                inputMode="decimal"
              />
            </div>
          </FormField>

          {txType === 'income' && (
            <FormField label="Description" hint="e.g. John — rent reimbursement">
              <input
                style={inputStyle}
                value={form.description}
                onChange={set('description')}
                placeholder="Who paid you / what for"
              />
            </FormField>
          )}

          <FormField label="Category">
            <select style={selectStyle} value={form.category_id} onChange={set('category_id')}>
              <option value="">Uncategorised</option>
              {(categories ?? []).map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </FormField>

          <button
            type="button"
            style={moreToggleStyle}
            onClick={() => setShowMore((v) => !v)}
          >
            {showMore ? '▲ Fewer options' : '▼ More options'}
          </button>

          {showMore && (
            <>
              <FormField label="Date">
                <input style={inputStyle} type="date" value={form.date} onChange={set('date')} />
              </FormField>
              {txType === 'expense' && (
                <FormField label="Description">
                  <input style={inputStyle} value={form.description} onChange={set('description')} placeholder="e.g. Groceries run" />
                </FormField>
              )}
              <FormField label="Notes">
                <textarea style={{ ...inputStyle, resize: 'vertical', minHeight: 60 }} value={form.notes} onChange={set('notes')} />
              </FormField>
            </>
          )}

          {error && <p style={{ color: 'var(--negative)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginBottom: 16 }}>
            Manual entries are saved as <span style={{ color: 'var(--accent)' }}>~ estimates</span> until
            matched by a bank statement import.
          </p>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Button variant="secondary" onClick={onCancel}>Cancel</Button>
            <Button type="submit" disabled={saving}>
              {saving ? 'Saving…' : txType === 'income' ? 'Add income' : 'Add expense'}
            </Button>
          </div>
        </>
      )}
    </form>
  )
}
