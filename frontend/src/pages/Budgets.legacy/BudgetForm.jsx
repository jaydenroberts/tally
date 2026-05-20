import { useEffect, useState } from 'react'
import client from '../../api/client'
import Button from '../../components/Button'
import FormField, { inputStyle, selectStyle } from '../../components/FormField'

// Self-contained budget add/edit form.
// Props: initial (null = new, or cat object with category_id/budget/period/start_date/end_date),
//        period (YYYY-MM string, used for default start_date),
//        onSave(payload), onCancel()
export default function BudgetForm({ initial, period, onSave, onCancel }) {
  const defaultStart = period ? `${period}-01` : new Date().toISOString().slice(0, 7) + '-01'

  const [form, setForm] = useState({
    category_id: initial?.category_id ?? '',
    amount:      initial?.budget      ?? '',
    period:      initial?.period      ?? 'monthly',
    start_date:  initial?.start_date  ?? defaultStart,
    end_date:    initial?.end_date    ?? '',
  })
  const [categories, setCategories] = useState([])
  const [saving, setSaving] = useState(false)
  const [error, setError]  = useState('')

  useEffect(() => {
    client.get('/categories').then(r => setCategories(r.data)).catch(() => {})
  }, [])

  function set(field) {
    return e => setForm(f => ({ ...f, [field]: e.target.value }))
  }

  async function handleSubmit(e) {
    e.preventDefault()
    if (!form.category_id) { setError('Select a category'); return }
    const amount = parseFloat(form.amount)
    if (isNaN(amount) || amount <= 0) { setError('Enter a positive budget amount'); return }
    setError('')
    setSaving(true)
    try {
      await onSave({
        category_id: parseInt(form.category_id),
        amount,
        period:     form.period,
        start_date: form.start_date,
        end_date:   form.end_date || null,
      })
    } finally {
      setSaving(false)
    }
  }

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Category *">
        <select style={selectStyle} value={form.category_id} onChange={set('category_id')} required autoFocus>
          <option value="">Select category…</option>
          {categories.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </FormField>

      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <FormField label="Budget amount *">
          <input style={inputStyle} type="number" step="0.01" min="0.01" value={form.amount} onChange={set('amount')} required inputMode="decimal"/>
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
          <input style={inputStyle} type="date" value={form.start_date} onChange={set('start_date')}/>
        </FormField>
        <FormField label="End date" hint="Leave blank for ongoing">
          <input style={inputStyle} type="date" value={form.end_date} onChange={set('end_date')}/>
        </FormField>
      </div>

      {error && <p style={{ color: 'var(--negative)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : initial ? 'Save changes' : 'Add budget'}</Button>
      </div>
    </form>
  )
}
