import { useEffect, useState, useCallback, useRef, useMemo } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useCurrency } from '../context/CurrencyContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'
import { formatDate } from '../utils/dateFormat'

const PAGE_SIZE = 50

// ─── Status badge ────────────────────────────────────────────────────────────

function StatusBadge({ tx }) {
  if (tx.is_verified) {
    return (
      <span style={badge.verified} title="Verified by bank statement">
        ✓ verified
      </span>
    )
  }
  return (
    <span style={badge.estimate} title="Manual estimate — not yet matched to a bank statement">
      ~ estimate
    </span>
  )
}

const badge = {
  verified: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    fontSize: 11, padding: '2px 8px', borderRadius: 99,
    background: '#50FA7B18', color: 'var(--green)',
    fontWeight: 600, whiteSpace: 'nowrap',
  },
  estimate: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    fontSize: 11, padding: '2px 8px', borderRadius: 99,
    background: '#FF79C618', color: 'var(--pink)',
    fontWeight: 600, whiteSpace: 'nowrap',
  },
  savings: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    fontSize: 11, padding: '2px 8px', borderRadius: 99,
    background: '#8BE9FD18', color: 'var(--cyan)',
    fontWeight: 600, whiteSpace: 'nowrap', marginLeft: 6,
  },
  debt: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    fontSize: 11, padding: '2px 8px', borderRadius: 99,
    background: '#BD93F918', color: 'var(--purple)',
    fontWeight: 600, whiteSpace: 'nowrap', marginLeft: 6,
  },
  income: {
    display: 'inline-flex', alignItems: 'center', gap: 3,
    fontSize: 10, fontWeight: 600, padding: '2px 6px',
    borderRadius: 4, marginLeft: 6,
    background: '#50FA7B18', color: 'var(--green)',
    border: '1px solid #50FA7B40',
  },
  transfer: {
    display: 'inline-flex', alignItems: 'center', gap: 3,
    fontSize: 10, fontWeight: 600, padding: '2px 6px',
    borderRadius: 4, marginLeft: 6,
    background: '#8BE9FD20', color: 'var(--cyan)',
    border: '1px solid #8BE9FD40',
  },
  savingsTransfer: {
    display: 'inline-flex', alignItems: 'center', gap: 4,
    fontSize: 11, padding: '2px 8px', borderRadius: 99,
    background: '#50FA7B18', color: 'var(--green)',
    fontWeight: 600, whiteSpace: 'nowrap', marginLeft: 6,
  },
}

// ─── Amount display (estimates shown muted with ~) ───────────────────────────

function AmountDisplay({ tx, currency }) {
  const { formatCurrency } = useCurrency()
  const formatted = formatCurrency(tx.amount, currency)
  if (!tx.is_verified) {
    return (
      <span style={{ color: 'var(--pink)', opacity: 0.8 }}>
        ~{formatted}
      </span>
    )
  }
  return (
    <span style={{ color: tx.amount >= 0 ? 'var(--green)' : 'var(--white)' }}>
      {formatted}
    </span>
  )
}

// ─── Match warning banner ─────────────────────────────────────────────────────

function ReconciliationBanner({ summary, onDismiss }) {
  const { formatCurrency } = useCurrency()
  if (!summary) return null
  const { matched_count, new_from_bank_count, estimates_pending, amount_diff_warnings } = summary
  return (
    <div style={bannerStyle.wrap}>
      <div style={bannerStyle.row}>
        <strong style={{ color: 'var(--cyan)' }}>Import complete</strong>
        <button style={bannerStyle.close} onClick={onDismiss}>✕</button>
      </div>
      <div style={bannerStyle.stats}>
        <span style={{ color: 'var(--green)' }}>✓ {matched_count} matched</span>
        <span style={{ color: 'var(--cyan)' }}>+ {new_from_bank_count} new from bank</span>
        {estimates_pending > 0 && (
          <span style={{ color: 'var(--pink)' }}>~ {estimates_pending} estimates still pending</span>
        )}
      </div>
      {amount_diff_warnings.length > 0 && (
        <div style={{ marginTop: 8 }}>
          <p style={{ fontSize: 12, color: 'var(--orange)', marginBottom: 4 }}>
            Amount differences found:
          </p>
          {amount_diff_warnings.map((w) => (
            <p key={w.transaction_id} style={{ fontSize: 12, color: 'var(--muted)' }}>
              · {w.description ?? 'Transaction'}: you estimated {formatCurrency(w.manual_amount)},
              bank says {formatCurrency(w.bank_amount)}
            </p>
          ))}
        </div>
      )}
    </div>
  )
}

const bannerStyle = {
  wrap: {
    background: 'var(--bg-card)',
    border: '1px solid var(--cyan)',
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
    color: 'var(--muted)',
    cursor: 'pointer',
    fontSize: 14,
  },
}

// ─── Quick / Full add form ────────────────────────────────────────────────────

// Transaction type toggle config — label and accent colour per type.
const TX_TYPES = [
  { key: 'expense',  label: '− Expense',   accent: 'var(--red)'   },
  { key: 'income',   label: '+ Income',    accent: 'var(--green)' },
  { key: 'transfer', label: '↔ Transfer',  accent: 'var(--cyan)'  },
]

function AddTransactionForm({ accounts, categories, onSave, onCancel, saving }) {
  const today = new Date().toISOString().split('T')[0]

  // Transaction type: 'expense' | 'income' | 'transfer'
  const [txType, setTxType] = useState('expense')

  const [form, setForm] = useState({
    account_id: accounts[0]?.id ?? '',
    amount: '',
    category_id: '',
    date: today,
    description: '',
    notes: '',
  })

  // Transfer-specific fields
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

    // Expense / Income — user always enters a positive number.
    // Expenses are negated before saving; income is stored positive.
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

  const activeAccent = TX_TYPES.find((t) => t.key === txType)?.accent ?? 'var(--cyan)'

  return (
    <form onSubmit={handleSubmit}>
      {/* ── Transaction type toggle ── */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 20 }}>
        {TX_TYPES.map(({ key, label, accent }) => (
          <button
            key={key}
            type="button"
            onClick={() => { setTxType(key); setError('') }}
            style={{
              padding: '6px 16px',
              borderRadius: 'var(--radius)',
              border: `1px solid ${txType === key ? accent : 'var(--border)'}`,
              background: txType === key ? `${accent}18` : 'transparent',
              color: txType === key ? accent : 'var(--muted)',
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
        /* ── Transfer mode ── */
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

          {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16 }}>
            Transfers create a <span style={{ color: 'var(--cyan)' }}>linked pair</span> of transactions and are excluded from budget calculations.
          </p>

          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
            <Button variant="secondary" onClick={onCancel}>Cancel</Button>
            <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Create transfer'}</Button>
          </div>
        </>
      ) : (
        /* ── Expense / Income mode ── */
        <>
          <FormField label="Account *">
            <select style={selectStyle} value={form.account_id} onChange={set('account_id')} required autoFocus>
              <option value="">Select account…</option>
              {accounts.map((a) => (
                <option key={a.id} value={a.id}>{a.name}</option>
              ))}
            </select>
          </FormField>

          {/* Amount — user enters a positive value; sign is applied automatically by type */}
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

          {/* Description is prominent for income — who paid you is the key fact */}
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
              {categories.map((c) => (
                <option key={c.id} value={c.id}>{c.name}</option>
              ))}
            </select>
          </FormField>

          {/* Optional fields */}
          <button
            type="button"
            style={styles.moreToggle}
            onClick={() => setShowMore((v) => !v)}
          >
            {showMore ? '▲ Fewer options' : '▼ More options'}
          </button>

          {showMore && (
            <>
              <FormField label="Date">
                <input style={inputStyle} type="date" value={form.date} onChange={set('date')} />
              </FormField>
              {/* Description for expenses lives here; for income it's already shown above */}
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

          {error && <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>}

          <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16 }}>
            Manual entries are saved as <span style={{ color: 'var(--pink)' }}>~ estimates</span> until
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

// ─── Filter bar ───────────────────────────────────────────────────────────────

function FilterBar({ accounts, categories, filters, onChange }) {
  function set(field) {
    return (e) => onChange({ ...filters, [field]: e.target.value })
  }
  function reset() {
    onChange({ account_id: '', category_id: '', is_verified: '', date_from: '', date_to: '' })
  }
  const active = Object.values(filters).some(Boolean)
  return (
    <div style={styles.filterBar}>
      <select style={{ ...selectStyle, flex: '1 1 140px' }} value={filters.account_id} onChange={set('account_id')}>
        <option value="">All accounts</option>
        {accounts.map((a) => <option key={a.id} value={a.id}>{a.name}</option>)}
      </select>

      <select style={{ ...selectStyle, flex: '1 1 140px' }} value={filters.category_id} onChange={set('category_id')}>
        <option value="">All categories</option>
        {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
      </select>

      <select style={{ ...selectStyle, flex: '1 1 130px' }} value={filters.is_verified} onChange={set('is_verified')}>
        <option value="">All statuses</option>
        <option value="false">Estimates only</option>
        <option value="true">Verified only</option>
      </select>

      <input
        style={{ ...inputStyle, flex: '1 1 130px' }}
        type="date"
        value={filters.date_from}
        onChange={set('date_from')}
        title="From date"
      />
      <input
        style={{ ...inputStyle, flex: '1 1 130px' }}
        type="date"
        value={filters.date_to}
        onChange={set('date_to')}
        title="To date"
      />

      {active && (
        <Button variant="ghost" size="sm" onClick={reset}>Clear</Button>
      )}
    </div>
  )
}

// ─── Import modal (multi-step) ────────────────────────────────────────────────

/**
 * Step 1 — File & account selection
 * Step 2 — Column mapping (+ PDF preview table)
 * Step 3 — Result (reconciliation summary)
 */
function ImportModal({ accounts, onDone, onClose }) {
  const [step, setStep]           = useState(1)
  const [files, setFiles]         = useState([])
  const [filesLoading, setFilesLoading] = useState(true)
  const [filesError, setFilesError]     = useState('')

  // Step 1 state
  const [selectedFile, setSelectedFile] = useState(null)
  const [accountId, setAccountId]       = useState(accounts[0]?.id ?? '')

  // Step 2 state
  const [preview, setPreview]     = useState(null)   // { columns, sample_rows, total_rows }
  const [previewLoading, setPreviewLoading] = useState(false)
  const [dateCol, setDateCol]     = useState('')
  const [descCol, setDescCol]     = useState('')
  const [amtCol, setAmtCol]       = useState('')
  // Split credit/debit mode (e.g. ING Australia: Date, Description, Credit, Debit, Balance)
  const [splitMode, setSplitMode] = useState(false)
  const [creditCol, setCreditCol] = useState('')
  const [debitCol, setDebitCol]   = useState('')
  const [mappingError, setMappingError] = useState('')

  // Previously-imported warning
  const [prevImportWarning, setPrevImportWarning] = useState(null)

  // Step 3 state
  const [result, setResult]       = useState(null)
  const [importing, setImporting] = useState(false)
  const [importError, setImportError] = useState('')

  // Load file list on mount
  useEffect(() => {
    client.get('/import/files')
      .then((r) => setFiles(r.data))
      .catch(() => setFilesError('Could not load file list. Make sure /financial-data is mounted.'))
      .finally(() => setFilesLoading(false))
  }, [])

  // Auto-select columns and detect split mode when preview loads
  useEffect(() => {
    if (!preview) return
    const cols = preview.columns

    // Auto-detect ING-style split format: headers contain both "credit" and "debit"
    const hasCreditCol = cols.some((c) => /^credit$/i.test(c.trim()))
    const hasDebitCol  = cols.some((c) => /^debit$/i.test(c.trim()))
    const detectedSplit = hasCreditCol && hasDebitCol
    setSplitMode(detectedSplit)

    setDateCol(cols.find((c) => /date/i.test(c)) ?? cols[0] ?? '')
    setDescCol(cols.find((c) => /desc|narr|detail|name|memo/i.test(c)) ?? cols[1] ?? '')

    if (detectedSplit) {
      // Pre-select the Credit and Debit columns
      setCreditCol(cols.find((c) => /^credit$/i.test(c.trim())) ?? '')
      setDebitCol(cols.find((c) => /^debit$/i.test(c.trim())) ?? '')
      setAmtCol('')
    } else {
      setAmtCol(cols.find((c) => /amount|amt|value/i.test(c)) ?? cols[2] ?? '')
      setCreditCol('')
      setDebitCol('')
    }
  }, [preview])

  function fileTypeOf(file) {
    return file?.filename?.toLowerCase().endsWith('.pdf') ? 'pdf' : 'csv'
  }

  async function handleStep1Next() {
    if (!selectedFile) return
    if (!accountId) return
    const type = fileTypeOf(selectedFile)

    if (type === 'pdf') {
      // Fetch preview to populate column choices
      setPreviewLoading(true)
      try {
        const r = await client.get('/import/pdf/preview', {
          params: { filename: selectedFile.filename, rows: 5 },
        })
        setPreview(r.data)
        if (r.data.previously_imported) {
          const d = new Date(r.data.last_import_at)
          setPrevImportWarning(`This file was previously imported on ${d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}.`)
        } else {
          setPrevImportWarning(null)
        }
      } catch (e) {
        setMappingError(e.response?.data?.detail ?? 'Failed to preview PDF')
      } finally {
        setPreviewLoading(false)
      }
    } else {
      // Fetch CSV preview — populates column dropdowns and triggers split-mode auto-detection
      setPreviewLoading(true)
      try {
        const r = await client.get('/import/csv/preview', {
          params: { filename: selectedFile.filename, rows: 5 },
        })
        setPreview(r.data)
        if (r.data.previously_imported) {
          const d = new Date(r.data.last_import_at)
          setPrevImportWarning(`This file was previously imported on ${d.toLocaleDateString('en-AU', { day: 'numeric', month: 'short', year: 'numeric' })}.`)
        } else {
          setPrevImportWarning(null)
        }
      } catch {
        // If preview fails, fall back to manual text entry with no auto-detection
        setPreview(null)
        setPrevImportWarning(null)
      } finally {
        setPreviewLoading(false)
      }
    }
    setStep(2)
  }

  async function handleImport() {
    const type = fileTypeOf(selectedFile)

    // Validate required column mapping based on mode
    if (!dateCol || !descCol) {
      setMappingError('Date and description columns are required')
      return
    }
    if (type === 'csv' && splitMode) {
      if (!creditCol || !debitCol) {
        setMappingError('Both credit and debit columns are required in split mode')
        return
      }
    } else {
      if (!amtCol) {
        setMappingError('Amount column is required')
        return
      }
    }

    setMappingError('')
    setImporting(true)
    try {
      const endpoint = type === 'pdf' ? '/import/pdf' : '/import/csv'

      // Build params — CSV supports split credit/debit mode; PDF uses single amount column
      const params = {
        filename:   selectedFile.filename,
        account_id: accountId,
        date_col:   dateCol,
        desc_col:   descCol,
      }
      if (type === 'csv' && splitMode) {
        params.credit_col = creditCol
        params.debit_col  = debitCol
      } else {
        params.amount_col = amtCol
      }

      const r = await client.post(endpoint, null, { params })
      setResult(r.data)
      setStep(3)
    } catch (e) {
      setImportError(e.response?.data?.detail ?? 'Import failed')
    } finally {
      setImporting(false)
    }
  }

  const type = selectedFile ? fileTypeOf(selectedFile) : null

  return (
    <Modal title="Import bank statement" onClose={onClose} width={620}>
      {/* Step indicator */}
      <div style={importStyles.steps}>
        {['File & account', 'Column mapping', 'Results'].map((label, i) => {
          const n = i + 1
          const active = step === n
          const done   = step > n
          return (
            <div key={n} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{
                width: 22, height: 22, borderRadius: '50%',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                fontSize: 11, fontWeight: 700,
                background: done ? 'var(--green)' : active ? 'var(--cyan)' : 'var(--border)',
                color: done || active ? '#282A36' : 'var(--muted)',
              }}>
                {done ? '✓' : n}
              </span>
              <span style={{ fontSize: 12, color: active ? 'var(--white)' : 'var(--muted)' }}>
                {label}
              </span>
              {i < 2 && <span style={{ color: 'var(--border)', fontSize: 12, marginLeft: 6 }}>›</span>}
            </div>
          )
        })}
      </div>

      {/* ── Step 1: File & account ── */}
      {step === 1 && (
        <div>
          {filesLoading ? (
            <p style={{ color: 'var(--muted)' }}>Loading files…</p>
          ) : filesError ? (
            <p style={{ color: 'var(--red)', marginBottom: 16 }}>{filesError}</p>
          ) : files.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '20px 0', color: 'var(--muted)' }}>
              <p style={{ fontWeight: 600, marginBottom: 8 }}>No files found</p>
              <p style={{ fontSize: 13 }}>
                Place CSV or PDF bank statements in your <code>/financial-data</code> volume.
              </p>
            </div>
          ) : (
            <>
              {/* File list */}
              <p style={importStyles.stepLabel}>Select file</p>
              <div style={importStyles.fileList}>
                {files.map((f) => {
                  const isSelected = selectedFile?.filename === f.filename
                  return (
                    <div
                      key={f.filename}
                      onClick={() => setSelectedFile(f)}
                      style={{
                        ...importStyles.fileRow,
                        background: isSelected ? 'var(--bg)' : 'transparent',
                        borderColor: isSelected ? 'var(--cyan)' : 'var(--border)',
                      }}
                    >
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <p style={{ fontSize: 13, fontWeight: 500, color: 'var(--white)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {f.filename}
                        </p>
                        <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 2 }}>
                          {(f.size_bytes / 1024).toFixed(1)} KB
                        </p>
                      </div>
                      <span style={{
                        fontSize: 10, fontWeight: 700, padding: '2px 6px',
                        borderRadius: 4, textTransform: 'uppercase',
                        color: f.file_type === 'pdf' ? '#BD93F9' : '#8BE9FD',
                        background: f.file_type === 'pdf' ? '#BD93F920' : '#8BE9FD20',
                      }}>
                        {f.file_type}
                      </span>
                    </div>
                  )
                })}
              </div>

              {/* Account picker */}
              <div style={{ marginTop: 16 }}>
                <p style={importStyles.stepLabel}>Select account</p>
                <select
                  style={{ ...selectStyle, width: '100%' }}
                  value={accountId}
                  onChange={(e) => setAccountId(e.target.value)}
                >
                  <option value="">Select account…</option>
                  {accounts.filter((a) => a.is_active).map((a) => (
                    <option key={a.id} value={a.id}>
                      {a.name}{a.institution ? ` · ${a.institution}` : ''}
                    </option>
                  ))}
                </select>
              </div>
            </>
          )}

          <div style={importStyles.footer}>
            <Button variant="secondary" onClick={onClose}>Cancel</Button>
            <Button
              onClick={handleStep1Next}
              disabled={!selectedFile || !accountId || filesLoading}
            >
              {previewLoading ? 'Loading…' : 'Next →'}
            </Button>
          </div>
        </div>
      )}

      {/* ── Step 2: Column mapping ── */}
      {step === 2 && (
        <div>
          {prevImportWarning && (
            <div style={{
              background: 'rgba(255,170,0,0.12)',
              border: '1px solid rgba(255,170,0,0.4)',
              borderRadius: '6px',
              padding: '10px 14px',
              marginBottom: '16px',
              color: '#ffaa00',
              fontSize: '13px',
            }}>
              &#9888; {prevImportWarning} Duplicate transactions will be skipped automatically.
            </div>
          )}
          <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
            File: <strong style={{ color: 'var(--white)' }}>{selectedFile?.filename}</strong>
            {preview && (
              <span style={{ marginLeft: 8, color: 'var(--cyan)' }}>
                ({preview.total_rows} rows, {preview.columns.length} columns)
              </span>
            )}
          </p>

          {/* PDF preview table */}
          {type === 'pdf' && preview && preview.sample_rows.length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <p style={importStyles.stepLabel}>Preview (first {preview.sample_rows.length} rows)</p>
              <div style={{ overflowX: 'auto', border: '1px solid var(--border)', borderRadius: 'var(--radius)' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                  <thead>
                    <tr style={{ background: 'var(--bg)' }}>
                      {preview.columns.map((c) => (
                        <th key={c} style={{ padding: '6px 10px', textAlign: 'left', color: 'var(--muted)', fontWeight: 600, whiteSpace: 'nowrap', borderBottom: '1px solid var(--border)' }}>
                          {c}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.sample_rows.map((row, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid var(--border)' }}>
                        {preview.columns.map((c) => (
                          <td key={c} style={{ padding: '5px 10px', color: 'var(--white)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {row[c] ?? ''}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Column mapping fields */}
          <p style={importStyles.stepLabel}>Map columns</p>

          {/* Amount mode toggle — CSV only (PDF always uses single amount column) */}
          {type === 'csv' && (
            <div style={{ marginBottom: 16 }}>
              <p style={importStyles.stepLabel}>Amount format</p>
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={() => setSplitMode(false)}
                  style={{
                    ...importStyles.modeBtn,
                    background: !splitMode ? 'var(--cyan)' : 'var(--bg)',
                    color:      !splitMode ? '#282A36'     : 'var(--muted)',
                    borderColor: !splitMode ? 'var(--cyan)' : 'var(--border)',
                  }}
                >
                  Single amount column
                </button>
                <button
                  onClick={() => setSplitMode(true)}
                  style={{
                    ...importStyles.modeBtn,
                    background: splitMode ? 'var(--cyan)' : 'var(--bg)',
                    color:      splitMode ? '#282A36'    : 'var(--muted)',
                    borderColor: splitMode ? 'var(--cyan)' : 'var(--border)',
                  }}
                >
                  Separate credit / debit columns
                </button>
              </div>
              {splitMode && (
                <p style={{ fontSize: 11, color: 'var(--muted)', marginTop: 6 }}>
                  Use this for ING Australia and other banks that export Credit and Debit as separate columns.
                </p>
              )}
            </div>
          )}

          {preview ? (
            // Dropdown selectors when we have a preview (CSV or PDF)
            <div style={{ display: 'grid', gridTemplateColumns: type === 'csv' && splitMode ? '1fr 1fr 1fr 1fr' : '1fr 1fr 1fr', gap: 12 }}>
              <FormField label="Date column *">
                <select style={selectStyle} value={dateCol} onChange={(e) => setDateCol(e.target.value)}>
                  <option value="">Select…</option>
                  {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </FormField>
              <FormField label="Description column *">
                <select style={selectStyle} value={descCol} onChange={(e) => setDescCol(e.target.value)}>
                  <option value="">Select…</option>
                  {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </FormField>
              {type === 'csv' && splitMode ? (
                <>
                  <FormField label="Credit column *">
                    <select style={selectStyle} value={creditCol} onChange={(e) => setCreditCol(e.target.value)}>
                      <option value="">Select…</option>
                      {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </FormField>
                  <FormField label="Debit column *">
                    <select style={selectStyle} value={debitCol} onChange={(e) => setDebitCol(e.target.value)}>
                      <option value="">Select…</option>
                      {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </FormField>
                </>
              ) : (
                <FormField label="Amount column *">
                  <select style={selectStyle} value={amtCol} onChange={(e) => setAmtCol(e.target.value)}>
                    <option value="">Select…</option>
                    {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                </FormField>
              )}
            </div>
          ) : (
            // Text inputs for CSV where preview failed, or PDF where preview failed
            <>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>
                Enter the exact column header names from your {type === 'pdf' ? 'PDF' : 'CSV'} file.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: type === 'csv' && splitMode ? '1fr 1fr 1fr 1fr' : '1fr 1fr 1fr', gap: 12 }}>
                <FormField label="Date column *">
                  <input style={inputStyle} value={dateCol} onChange={(e) => setDateCol(e.target.value)} placeholder="e.g. Date" />
                </FormField>
                <FormField label="Description column *">
                  <input style={inputStyle} value={descCol} onChange={(e) => setDescCol(e.target.value)} placeholder="e.g. Description" />
                </FormField>
                {type === 'csv' && splitMode ? (
                  <>
                    <FormField label="Credit column *">
                      <input style={inputStyle} value={creditCol} onChange={(e) => setCreditCol(e.target.value)} placeholder="e.g. Credit" />
                    </FormField>
                    <FormField label="Debit column *">
                      <input style={inputStyle} value={debitCol} onChange={(e) => setDebitCol(e.target.value)} placeholder="e.g. Debit" />
                    </FormField>
                  </>
                ) : (
                  <FormField label="Amount column *">
                    <input style={inputStyle} value={amtCol} onChange={(e) => setAmtCol(e.target.value)} placeholder="e.g. Amount" />
                  </FormField>
                )}
              </div>
            </>
          )}

          {mappingError && <p style={{ color: 'var(--red)', fontSize: 13, marginTop: 8 }}>{mappingError}</p>}
          {importError  && <p style={{ color: 'var(--red)', fontSize: 13, marginTop: 8 }}>{importError}</p>}

          <div style={importStyles.footer}>
            <Button variant="secondary" onClick={() => { setStep(1); setPreview(null); setImportError(''); setPrevImportWarning(null) }}>← Back</Button>
            <Button
              onClick={handleImport}
              disabled={
                importing || !dateCol || !descCol ||
                (type === 'csv' && splitMode ? (!creditCol || !debitCol) : !amtCol)
              }
            >
              {importing ? 'Importing…' : 'Run import'}
            </Button>
          </div>
        </div>
      )}

      {/* ── Step 3: Results ── */}
      {step === 3 && result && (
        <div>
          <div style={importStyles.resultGrid}>
            <ResultTile value={result.matched_count}         label="Estimates matched"  color="#50FA7B" />
            <ResultTile value={result.new_from_bank_count}   label="New from bank"       color="#8BE9FD" />
            <ResultTile value={result.estimates_pending}     label="Estimates pending"   color="#FF79C6" />
          </div>
          {result.skipped_duplicates > 0 && (
            <div style={{ marginTop: 12, padding: '8px 14px', background: 'rgba(255,170,0,0.08)', border: '1px solid rgba(255,170,0,0.3)', borderRadius: 'var(--radius)', fontSize: 13, color: '#ffaa00' }}>
              Skipped (already imported): {result.skipped_duplicates}
            </div>
          )}

          {result.amount_diff_warnings.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--orange)', marginBottom: 8 }}>
                Amount differences ({result.amount_diff_warnings.length})
              </p>
              <div style={{ border: '1px solid var(--border)', borderRadius: 'var(--radius)', overflow: 'hidden' }}>
                {result.amount_diff_warnings.map((w) => (
                  <div key={w.transaction_id} style={importStyles.warnRow}>
                    <span style={{ fontSize: 12, color: 'var(--white)', flex: 1 }}>
                      {w.description ?? 'Transaction'}
                    </span>
                    <span style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                      estimated {w.manual_amount >= 0 ? '+' : ''}{w.manual_amount.toFixed(2)}
                      {' → '}{w.bank_amount >= 0 ? '+' : ''}{w.bank_amount.toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div style={importStyles.footer}>
            <Button onClick={() => { onDone(result); onClose() }}>Done</Button>
          </div>
        </div>
      )}
    </Modal>
  )
}

function ResultTile({ value, label, color }) {
  return (
    <div style={{ background: 'var(--bg)', border: '1px solid var(--border)', borderRadius: 'var(--radius-lg)', padding: '16px 20px', textAlign: 'center' }}>
      <p style={{ fontSize: 28, fontWeight: 700, color }}>{value}</p>
      <p style={{ fontSize: 12, color: 'var(--muted)', marginTop: 4 }}>{label}</p>
    </div>
  )
}

const importStyles = {
  steps: {
    display: 'flex', alignItems: 'center', gap: 8,
    marginBottom: 20, paddingBottom: 16,
    borderBottom: '1px solid var(--border)',
  },
  stepLabel: {
    fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
    letterSpacing: '0.06em', color: 'var(--muted)', marginBottom: 8,
  },
  fileList: {
    display: 'flex', flexDirection: 'column', gap: 6,
    maxHeight: 240, overflowY: 'auto',
    border: '1px solid var(--border)', borderRadius: 'var(--radius)',
    padding: 8,
  },
  fileRow: {
    display: 'flex', alignItems: 'center', gap: 10,
    padding: '8px 10px', borderRadius: 'var(--radius)',
    border: '1px solid transparent', cursor: 'pointer',
  },
  footer: {
    display: 'flex', justifyContent: 'flex-end', gap: 10, marginTop: 20,
  },
  resultGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12,
    marginBottom: 16,
  },
  warnRow: {
    display: 'flex', alignItems: 'center', gap: 12,
    padding: '8px 12px', borderBottom: '1px solid var(--border)',
  },
  modeBtn: {
    padding: '6px 14px', borderRadius: 'var(--radius)', border: '1px solid',
    fontSize: 12, fontWeight: 600, cursor: 'pointer', transition: 'all 0.15s',
  },
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function Transactions() {
  const { isOwner } = useAuth()
  const { formatCurrency } = useCurrency()

  const [transactions, setTransactions] = useState([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(0)
  const [loading, setLoading] = useState(true)

  const [accounts, setAccounts] = useState([])
  const [categories, setCategories] = useState([])
  const [debts, setDebts] = useState([])
  const [savingsGoals, setSavingsGoals] = useState([])

  const [filters, setFilters] = useState({
    account_id: '', category_id: '', is_verified: '', date_from: '', date_to: '',
  })

  // Sort state — default: date descending (most recent first)
  const [sort, setSort] = useState({ by: 'date', dir: 'desc' })

  const [showAdd, setShowAdd]       = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editing, setEditing]       = useState(null)
  const [deleting, setDeleting]     = useState(null)
  const [saving, setSaving]         = useState(false)
  const [actionError, setActionError] = useState('')
  const [reconciliation, setReconciliation] = useState(null)
  const [selectedIds, setSelectedIds] = useState(new Set())
  const [bulkDeleteConfirm, setBulkDeleteConfirm] = useState(false)
  const [bulkDeleteError, setBulkDeleteError] = useState('')

  // Bulk category update state
  const [bulkCategoryPickerOpen, setBulkCategoryPickerOpen] = useState(false)
  const [bulkCategoryValue, setBulkCategoryValue] = useState('')
  const [bulkCategoryConfirm, setBulkCategoryConfirm] = useState(false)
  const [bulkCategoryPatching, setBulkCategoryPatching] = useState(false)
  const [bulkCategoryError, setBulkCategoryError] = useState('')

  // Debt linkage state
  const [linkingTx, setLinkingTx]       = useState(null)  // tx to link to a debt
  const [linkDebtId, setLinkDebtId]     = useState('')
  const [linkError, setLinkError]       = useState('')
  const [linkLoading, setLinkLoading]   = useState(false)

  // Savings allocation state (credit tx → savings contribution)
  const [allocatingTx, setAllocatingTx]   = useState(null)  // tx to allocate to savings goals
  const [allocations, setAllocations]     = useState([])     // [{goal_id, amount}]
  const [allocError, setAllocError]       = useState('')
  const [allocLoading, setAllocLoading]   = useState(false)

  // Transfer pair linking state
  const [linkingTransfer, setLinkingTransfer]       = useState(null)  // source tx for pair selection
  const [transferPairError, setTransferPairError]   = useState('')
  const [transferPairLoading, setTransferPairLoading] = useState(false)

  // Savings withdrawal linking state (debit tx → savings withdrawal)
  const [withdrawLinkingTx, setWithdrawLinkingTx]     = useState(null)
  const [withdrawGoalId, setWithdrawGoalId]           = useState('')
  const [withdrawError, setWithdrawError]             = useState('')
  const [withdrawLoading, setWithdrawLoading]         = useState(false)

  // Inline category editing — tracks which tx row has the dropdown open
  const [categoryEditId, setCategoryEditId] = useState(null)
  const [categoryPatching, setCategoryPatching] = useState(null)
  const categorySelectRef = useRef(null)

  const load = useCallback((p = 0) => {
    setLoading(true)
    const params = new URLSearchParams()
    params.set('skip', p * PAGE_SIZE)
    params.set('limit', PAGE_SIZE)
    if (filters.account_id)  params.set('account_id',  filters.account_id)
    if (filters.category_id) params.set('category_id', filters.category_id)
    if (filters.is_verified !== '') params.set('is_verified', filters.is_verified)
    if (filters.date_from)   params.set('date_from',   filters.date_from)
    if (filters.date_to)     params.set('date_to',     filters.date_to)
    params.set('sort_by',  sort.by)
    params.set('sort_dir', sort.dir)

    const countParams = new URLSearchParams(params)
    countParams.delete('skip')
    countParams.delete('limit')
    countParams.delete('sort_by')
    countParams.delete('sort_dir')

    Promise.all([
      client.get(`/transactions?${params.toString()}`),
      client.get(`/transactions/count?${countParams.toString()}`),
    ])
      .then(([txRes, countRes]) => {
        setTransactions(txRes.data)
        setTotal(countRes.data.count)
        setSelectedIds(new Set())
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [filters, sort])

  // Load meta (accounts + categories + active debts + savings goals) once
  useEffect(() => {
    Promise.all([
      client.get('/accounts'),
      client.get('/categories'),
      client.get('/debt'),
      client.get('/savings'),
    ]).then(([a, c, d, s]) => {
      setAccounts(a.data)
      setCategories(c.data)
      setDebts(d.data.filter((debt) => !debt.is_paid_off))
      setSavingsGoals(s.data.filter((g) => !g.is_completed))
    })
  }, [])

  // Reload on filter or sort change, reset to page 0
  useEffect(() => {
    setPage(0)
    load(0)
  }, [filters, sort])

  function changePage(newPage) {
    setPage(newPage)
    load(newPage)
  }

  // ── Account lookup for currency display
  const accountMap = Object.fromEntries(accounts.map((a) => [a.id, a]))

  // ── Add / Edit / Delete ──────────────────────────────────────────────────

  async function handleAdd(form) {
    setSaving(true)
    setActionError('')
    try {
      if (form._isTransfer) {
        // Transfer flow — POST to dedicated endpoint; response includes both sides
        const { _isTransfer: _, ...transferPayload } = form
        await client.post('/transactions/transfer', transferPayload)
      } else {
        await client.post('/transactions', form)
      }
      setShowAdd(false)
      load(0)
      setPage(0)
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to add transaction')
    } finally {
      setSaving(false)
    }
  }

  async function handleEdit(form) {
    setSaving(true)
    setActionError('')
    try {
      await client.patch(`/transactions/${editing.id}`, form)
      setEditing(null)
      load(page)
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to update transaction')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setSaving(true)
    try {
      await client.delete(`/transactions/${deleting.id}`)
      setDeleting(null)
      load(page)
    } catch (e) {
      setActionError(e.response?.data?.detail ?? 'Failed to delete transaction')
    } finally {
      setSaving(false)
    }
  }

  const handleBulkDelete = async () => {
    setBulkDeleteError('')
    try {
      const ids = Array.from(selectedIds)
      await client.delete('/transactions/bulk', {
        params: { ids },
        paramsSerializer: params => params.ids.map(id => `ids=${id}`).join('&'),
      })
      setBulkDeleteConfirm(false)
      setBulkDeleteError('')
      setSelectedIds(new Set())
      load(page)
    } catch (err) {
      console.error('Bulk delete failed', err)
      setBulkDeleteError(err.response?.data?.detail ?? 'Delete failed — see console for details')
    }
  }

  // Bulk category update — fires PATCH in parallel for all selected IDs, updates in-place
  const handleBulkSetCategory = async () => {
    setBulkCategoryPatching(true)
    setBulkCategoryError('')
    const newCatId = bulkCategoryValue ? parseInt(bulkCategoryValue) : null
    const ids = Array.from(selectedIds)
    try {
      const results = await Promise.allSettled(
        ids.map((id) =>
          client.patch(`/transactions/${id}`, { category_id: newCatId })
        )
      )
      // Collect successful responses and failed IDs
      const successMap = new Map()
      const failedIds = []
      results.forEach((result, idx) => {
        if (result.status === 'fulfilled') {
          successMap.set(ids[idx], result.value.data)
        } else {
          failedIds.push(ids[idx])
        }
      })
      // Update all successful rows in-place using server response data
      if (successMap.size > 0) {
        setTransactions((prev) =>
          prev.map((t) =>
            successMap.has(t.id) ? successMap.get(t.id) : t
          )
        )
      }
      if (failedIds.length > 0) {
        setBulkCategoryError(`${failedIds.length} update${failedIds.length !== 1 ? 's' : ''} failed (verified transactions cannot be edited).`)
      } else {
        // Full success — reset bulk category state and clear selection
        setBulkCategoryConfirm(false)
        setBulkCategoryPickerOpen(false)
        setBulkCategoryValue('')
      }
      // Deselect successful IDs, keep failed ones selected for visibility
      setSelectedIds(new Set(failedIds))
    } catch (err) {
      console.error('Bulk category update failed', err)
      setBulkCategoryError('Some updates failed — please try again.')
    } finally {
      setBulkCategoryPatching(false)
    }
  }

  // Close inline category dropdown when clicking outside it
  useEffect(() => {
    if (!categoryEditId) return
    function handleClickOutside(e) {
      if (categorySelectRef.current && !categorySelectRef.current.contains(e.target)) {
        setCategoryEditId(null)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [categoryEditId])

  // Patch just the category on a transaction, update in-place
  async function handleCategoryChange(tx, newCategoryId) {
    setCategoryPatching(tx.id)
    try {
      const payload = { category_id: newCategoryId ? parseInt(newCategoryId) : null }
      const res = await client.patch(`/transactions/${tx.id}`, payload)
      // Use the full server response (includes nested category object) to update in-place
      setTransactions((prev) =>
        prev.map((t) =>
          t.id === tx.id ? res.data : t
        )
      )
    } catch (e) {
      console.error('Failed to update category', e)
    } finally {
      setCategoryPatching(null)
      setCategoryEditId(null)
    }
  }

  // When the allocation modal opens, seed one row per active goal with amount=''
  useEffect(() => {
    if (!allocatingTx) return
    setAllocations(savingsGoals.map((g) => ({ goal_id: g.id, amount: '' })))
  }, [allocatingTx])

  // Debt name lookup by id (active debts only)
  const debtMap = useMemo(
    () => Object.fromEntries(debts.map((d) => [d.id, d.name])),
    [debts]
  )

  // Link a transaction to a debt — POST /api/transactions/{id}/link-debt
  async function handleLinkDebt() {
    if (!linkingTx || !linkDebtId) return
    setLinkLoading(true)
    setLinkError('')
    try {
      const res = await client.post(`/transactions/${linkingTx.id}/link-debt`, {
        debt_id: parseInt(linkDebtId),
      })
      // Update the transaction in local state with the server's response
      setTransactions((prev) =>
        prev.map((t) => (t.id === linkingTx.id ? res.data : t))
      )
      // Refresh active debt list so the name map stays current
      client.get('/debt').then((r) => setDebts(r.data.filter((d) => !d.is_paid_off)))
      setLinkingTx(null)
      setLinkDebtId('')
    } catch (e) {
      setLinkError(e.response?.data?.detail ?? 'Failed to link transaction to debt')
    } finally {
      setLinkLoading(false)
    }
  }

  // Unlink a transaction from its debt — DELETE /api/transactions/{id}/link-debt
  async function handleUnlinkDebt(tx) {
    if (!window.confirm('Remove debt linkage from this transaction? This will reverse the payment on the debt.')) return
    try {
      await client.delete(`/transactions/${tx.id}/link-debt`)
      // Clear debt_id and reset transaction_type in local state
      setTransactions((prev) =>
        prev.map((t) =>
          t.id === tx.id ? { ...t, debt_id: null, transaction_type: 'expense' } : t
        )
      )
      // Refresh active debts so balances are current
      client.get('/debt').then((r) => setDebts(r.data.filter((d) => !d.is_paid_off)))
    } catch (e) {
      console.error('Failed to unlink debt', e)
    }
  }

  // Allocate a credit transaction to one or more savings goals
  async function handleLinkSavings() {
    if (!allocatingTx) return
    const filtered = allocations.filter((a) => parseFloat(a.amount) > 0).map((a) => ({
      goal_id: a.goal_id,
      amount: parseFloat(a.amount),
    }))
    if (filtered.length === 0) {
      setAllocError('Enter an amount for at least one savings goal')
      return
    }
    setAllocLoading(true)
    setAllocError('')
    try {
      await client.post(`/transactions/${allocatingTx.id}/link-savings`, { allocations: filtered })
      // Update the transaction in local state — type is now savings_transfer
      setTransactions((prev) =>
        prev.map((t) =>
          t.id === allocatingTx.id ? { ...t, transaction_type: 'savings_transfer' } : t
        )
      )
      // Refresh savings goals so balances are current
      client.get('/savings').then((r) => setSavingsGoals(r.data.filter((g) => !g.is_completed)))
      setAllocatingTx(null)
      setAllocations([])
    } catch (e) {
      setAllocError(e.response?.data?.detail ?? 'Failed to allocate to savings goals')
    } finally {
      setAllocLoading(false)
    }
  }

  // Link two existing transactions as a transfer pair
  async function handleLinkTransferPair(pairTxId) {
    if (!linkingTransfer) return
    setTransferPairLoading(true)
    setTransferPairError('')
    try {
      const res = await client.post('/transactions/link-transfer-pair', {
        transaction_a_id: linkingTransfer.id,
        transaction_b_id: pairTxId,
      })
      // Update both sides in local state
      const { debit_transaction, credit_transaction } = res.data
      setTransactions((prev) =>
        prev.map((t) => {
          if (t.id === debit_transaction.id) return debit_transaction
          if (t.id === credit_transaction.id) return credit_transaction
          return t
        })
      )
      setLinkingTransfer(null)
    } catch (e) {
      setTransferPairError(e.response?.data?.detail ?? 'Failed to link transfer pair')
    } finally {
      setTransferPairLoading(false)
    }
  }

  // Unlink both sides of a transfer pair
  async function handleUnlinkTransferPair(tx) {
    if (!window.confirm('Remove transfer pair linkage? Both transactions will be reset to expense type.')) return
    try {
      await client.delete(`/transactions/${tx.id}/link-transfer-pair`)
      // Reset both sides — we know the pair by transfer_pair_id
      const pairId = tx.transfer_pair_id
      setTransactions((prev) =>
        prev.map((t) =>
          t.transfer_pair_id === pairId
            ? { ...t, transaction_type: 'expense', transfer_pair_id: null }
            : t
        )
      )
    } catch (e) {
      console.error('Failed to unlink transfer pair', e)
    }
  }

  // Link a debit transaction to a savings goal as a withdrawal
  async function handleLinkSavingsWithdrawal() {
    if (!withdrawLinkingTx || !withdrawGoalId) return
    setWithdrawLoading(true)
    setWithdrawError('')
    try {
      const res = await client.post(`/transactions/${withdrawLinkingTx.id}/link-savings-withdrawal`, {
        goal_id: parseInt(withdrawGoalId),
      })
      setTransactions((prev) =>
        prev.map((t) => (t.id === withdrawLinkingTx.id ? res.data : t))
      )
      // Refresh savings goals so balances are current
      client.get('/savings').then((r) => setSavingsGoals(r.data.filter((g) => !g.is_completed)))
      setWithdrawLinkingTx(null)
      setWithdrawGoalId('')
    } catch (e) {
      setWithdrawError(e.response?.data?.detail ?? 'Failed to link savings withdrawal')
    } finally {
      setWithdrawLoading(false)
    }
  }

  // Unlink a savings withdrawal from a debit transaction
  async function handleUnlinkSavingsWithdrawal(tx) {
    if (!window.confirm('Remove savings withdrawal linkage? This will restore the goal\'s balance.')) return
    try {
      await client.delete(`/transactions/${tx.id}/link-savings-withdrawal`)
      setTransactions((prev) =>
        prev.map((t) =>
          t.id === tx.id ? { ...t, transaction_type: 'expense' } : t
        )
      )
      // Refresh savings goals so balances are current
      client.get('/savings').then((r) => setSavingsGoals(r.data.filter((g) => !g.is_completed)))
    } catch (e) {
      console.error('Failed to unlink savings withdrawal', e)
    }
  }

  // Toggle sort: clicking the active column flips direction; clicking a new column sets it asc
  function handleSort(column) {
    setSort((prev) =>
      prev.by === column
        ? { by: column, dir: prev.dir === 'asc' ? 'desc' : 'asc' }
        : { by: column, dir: 'asc' }
    )
  }

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <div style={{ paddingBottom: 80 }}>
      {/* Header */}
      <div style={styles.pageHeader}>
        <div>
          <h1 style={styles.pageTitle}>Transactions</h1>
          <p style={styles.pageSubtitle}>
            {total} transaction{total !== 1 ? 's' : ''}
          </p>
        </div>
        {isOwner && (
          <div style={{ display: 'flex', gap: 8 }}>
            <Button
              variant="secondary"
              onClick={() => setShowImport(true)}
            >
              Import statement
            </Button>
            <Button
              onClick={() => { setShowAdd(true); setActionError('') }}
              style={{ display: 'none' }}  /* hidden on mobile — FAB used instead */
            >
              + Add
            </Button>
          </div>
        )}
      </div>

      {/* Reconciliation banner */}
      <ReconciliationBanner summary={reconciliation} onDismiss={() => setReconciliation(null)} />

      {/* Filters */}
      <FilterBar
        accounts={accounts}
        categories={categories}
        filters={filters}
        onChange={(f) => setFilters(f)}
      />

      {/* Bulk action toolbar */}
      {selectedIds.size > 0 && (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '8px',
          padding: '10px 14px',
          marginBottom: '10px',
          background: 'rgba(255,85,85,0.08)',
          border: '1px solid rgba(255,85,85,0.25)',
          borderRadius: '8px',
          fontSize: '13px',
          color: 'var(--text)',
        }}>
          {/* Top row: count + actions */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
            <span>{selectedIds.size} transaction{selectedIds.size !== 1 ? 's' : ''} selected</span>

            {/* Set category button / picker */}
            {!bulkCategoryPickerOpen ? (
              <button
                onClick={() => { setBulkCategoryPickerOpen(true); setBulkCategoryConfirm(false); setBulkCategoryValue(''); setBulkCategoryError('') }}
                style={{
                  background: 'rgba(139,233,253,0.1)',
                  border: '1px solid rgba(139,233,253,0.35)',
                  borderRadius: '6px',
                  color: 'var(--cyan)',
                  padding: '5px 14px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                Set category…
              </button>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
                <select
                  value={bulkCategoryValue}
                  onChange={(e) => { setBulkCategoryValue(e.target.value); setBulkCategoryConfirm(false); setBulkCategoryError('') }}
                  style={{
                    ...selectStyle,
                    fontSize: 12,
                    padding: '3px 8px',
                    height: 30,
                    minWidth: 140,
                  }}
                >
                  <option value="">Uncategorised</option>
                  {categories.map((c) => (
                    <option key={c.id} value={c.id}>{c.name}</option>
                  ))}
                </select>
                <button
                  onClick={() => setBulkCategoryConfirm(true)}
                  disabled={bulkCategoryConfirm}
                  style={{
                    background: 'rgba(139,233,253,0.15)',
                    border: '1px solid rgba(139,233,253,0.4)',
                    borderRadius: '6px',
                    color: 'var(--cyan)',
                    padding: '5px 12px',
                    cursor: 'pointer',
                    fontSize: '13px',
                    opacity: bulkCategoryConfirm ? 0.5 : 1,
                  }}
                >
                  Apply
                </button>
                <button
                  onClick={() => { setBulkCategoryPickerOpen(false); setBulkCategoryConfirm(false); setBulkCategoryValue(''); setBulkCategoryError('') }}
                  style={{
                    background: 'transparent',
                    border: 'none',
                    color: 'var(--comment)',
                    cursor: 'pointer',
                    fontSize: '13px',
                    padding: '5px 4px',
                  }}
                >
                  ✕
                </button>
              </div>
            )}

            <button
              onClick={() => setBulkDeleteConfirm(true)}
              style={{
                background: 'rgba(255,85,85,0.15)',
                border: '1px solid rgba(255,85,85,0.4)',
                borderRadius: '6px',
                color: '#ff5555',
                padding: '5px 14px',
                cursor: 'pointer',
                fontSize: '13px',
              }}
            >
              Delete selected
            </button>
            <button
              onClick={() => { setSelectedIds(new Set()); setBulkCategoryPickerOpen(false); setBulkCategoryConfirm(false); setBulkCategoryValue(''); setBulkCategoryError('') }}
              style={{
                background: 'transparent',
                border: 'none',
                color: 'var(--comment)',
                cursor: 'pointer',
                fontSize: '13px',
                padding: '5px 8px',
                marginLeft: 'auto',
              }}
            >
              Clear selection
            </button>
          </div>

          {/* Inline confirm strip — only shown after clicking Apply */}
          {bulkCategoryConfirm && !bulkCategoryPatching && (
            <div style={{
              display: 'flex',
              alignItems: 'center',
              gap: '12px',
              padding: '8px 12px',
              background: 'rgba(139,233,253,0.06)',
              border: '1px solid rgba(139,233,253,0.25)',
              borderRadius: '6px',
              flexWrap: 'wrap',
            }}>
              <span style={{ color: 'var(--cyan)', fontSize: 13 }}>
                This will update the category of <strong>{selectedIds.size}</strong> transaction{selectedIds.size !== 1 ? 's' : ''} to{' '}
                <strong>{bulkCategoryValue ? (categories.find((c) => c.id === parseInt(bulkCategoryValue))?.name ?? 'Unknown') : 'Uncategorised'}</strong>. Continue?
              </span>
              <button
                onClick={handleBulkSetCategory}
                style={{
                  background: 'var(--cyan)',
                  border: 'none',
                  borderRadius: '6px',
                  color: '#282A36',
                  padding: '5px 16px',
                  cursor: 'pointer',
                  fontSize: '13px',
                  fontWeight: 600,
                }}
              >
                Confirm
              </button>
              <button
                onClick={() => { setBulkCategoryConfirm(false); setBulkCategoryError('') }}
                style={{
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  borderRadius: '6px',
                  color: 'var(--comment)',
                  padding: '5px 12px',
                  cursor: 'pointer',
                  fontSize: '13px',
                }}
              >
                Cancel
              </button>
            </div>
          )}

          {/* Patching in-progress */}
          {bulkCategoryPatching && (
            <p style={{ fontSize: 13, color: 'var(--cyan)', margin: 0 }}>Updating categories…</p>
          )}

          {/* Error */}
          {bulkCategoryError && (
            <p style={{ fontSize: 13, color: 'var(--red)', margin: 0 }}>{bulkCategoryError}</p>
          )}
        </div>
      )}

      {/* Table */}
      {loading ? (
        <p style={{ color: 'var(--muted)', marginTop: 24 }}>Loading…</p>
      ) : transactions.length === 0 ? (
        <div style={styles.empty}>
          <p style={styles.emptyTitle}>No transactions found</p>
          <p style={{ color: 'var(--muted)', fontSize: 14 }}>
            {Object.values(filters).some(Boolean)
              ? 'Try clearing the filters.'
              : 'Add a manual entry or import a bank statement.'}
          </p>
        </div>
      ) : (
        <>
          <div style={styles.table}>
            {/* Desktop header */}
            <div className="tx-table-header" style={{ ...styles.tableHeader, gridTemplateColumns: isOwner ? '36px 100px 1fr 120px 120px 110px 110px 150px' : '100px 1fr 120px 120px 110px 110px 150px' }}>
              {isOwner && (
                <th style={{ width: '36px', padding: '10px 8px' }}>
                  <input
                    type="checkbox"
                    checked={selectedIds.size > 0 && selectedIds.size === transactions.length}
                    ref={el => { if (el) el.indeterminate = selectedIds.size > 0 && selectedIds.size < transactions.length; }}
                    onChange={e => {
                      if (e.target.checked) {
                        setSelectedIds(new Set(transactions.map(t => t.id)));
                      } else {
                        setSelectedIds(new Set());
                      }
                    }}
                    style={{ cursor: 'pointer' }}
                  />
                </th>
              )}
              {/* Sortable: Date */}
              <button style={sortHeaderBtn(sort, 'date')} onClick={() => handleSort('date')}>
                Date{sort.by === 'date' ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
              </button>
              <span>Description</span>
              <span>Category</span>
              {/* Sortable: Account */}
              <button style={sortHeaderBtn(sort, 'account_id')} onClick={() => handleSort('account_id')}>
                Account{sort.by === 'account_id' ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
              </button>
              {/* Sortable: Amount */}
              <button style={{ ...sortHeaderBtn(sort, 'amount'), textAlign: 'right', justifyContent: 'flex-end' }} onClick={() => handleSort('amount')}>
                Amount{sort.by === 'amount' ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
              </button>
              {/* Sortable: Status */}
              <button style={{ ...sortHeaderBtn(sort, 'is_verified'), justifyContent: 'center' }} onClick={() => handleSort('is_verified')}>
                Status{sort.by === 'is_verified' ? (sort.dir === 'asc' ? ' ↑' : ' ↓') : ''}
              </button>
              {isOwner && <span />}
            </div>

            {transactions.map((tx) => {
              const account = accountMap[tx.account_id]
              const isEstimate = !tx.is_verified
              return (
                <div
                  key={tx.id}
                  className="tx-table-row"
                  style={{
                    ...styles.tableRow,
                    opacity: isEstimate ? 0.82 : 1,
                    gridTemplateColumns: isOwner ? '36px 100px 1fr 120px 120px 110px 110px 150px' : '100px 1fr 120px 120px 110px 110px 150px',
                  }}
                >
                  {isOwner && (
                    <span style={{ padding: '10px 8px' }}>
                      <input
                        type="checkbox"
                        checked={selectedIds.has(tx.id)}
                        onChange={e => {
                          setSelectedIds(prev => {
                            const next = new Set(prev);
                            if (e.target.checked) next.add(tx.id); else next.delete(tx.id);
                            return next;
                          });
                        }}
                        style={{ cursor: 'pointer' }}
                      />
                    </span>
                  )}
                  <span style={{ color: 'var(--muted)', fontSize: 13 }}>{formatDate(tx.date)}</span>

                  <span style={{ color: isEstimate ? 'var(--muted)' : 'var(--white)' }}>
                    {tx.description ?? <span style={{ color: 'var(--border)' }}>—</span>}
                    {tx.match_note && (
                      <span title={tx.match_note} style={{ marginLeft: 6, fontSize: 11, color: 'var(--orange)', cursor: 'help' }}>⚠</span>
                    )}
                    {tx.savings_goal_id && (
                      <span style={badge.savings} title="Created by savings goal withdrawal">⬡ Savings</span>
                    )}
                    {tx.debt_id && (
                      <span style={badge.debt} title="Click to unlink">
                        ⬡ {debtMap[tx.debt_id] ?? 'Debt'}
                      </span>
                    )}
                    {tx.transaction_type === 'income' && (
                      <span style={badge.income} title="Income">
                        + Income
                      </span>
                    )}
                    {tx.transaction_type === 'transfer' && (
                      <span style={badge.transfer} title={tx.transfer_pair_id ? `Transfer pair #${tx.transfer_pair_id}` : 'Transfer'}>
                        ↔ Transfer
                      </span>
                    )}
                    {tx.transaction_type === 'savings_transfer' && (
                      <span style={badge.savingsTransfer} title="Allocated to savings goals">
                        ⬡ Savings
                      </span>
                    )}
                  </span>

                  {/* Category cell — clickable for owners to set/override inline */}
                  {isOwner ? (
                    categoryEditId === tx.id ? (
                      // Inline dropdown — open state
                      <select
                        ref={categorySelectRef}
                        autoFocus
                        disabled={categoryPatching === tx.id}
                        defaultValue={tx.category_id ?? ''}
                        onChange={(e) => handleCategoryChange(tx, e.target.value)}
                        onKeyDown={(e) => { if (e.key === 'Escape') setCategoryEditId(null) }}
                        style={{
                          ...selectStyle,
                          fontSize: 12,
                          padding: '2px 6px',
                          height: 28,
                          minWidth: 0,
                          width: '100%',
                          opacity: categoryPatching === tx.id ? 0.5 : 1,
                        }}
                      >
                        <option value="">Uncategorised</option>
                        {categories.map((c) => (
                          <option key={c.id} value={c.id}>{c.name}</option>
                        ))}
                      </select>
                    ) : (
                      // Clickable label — closed state
                      <span
                        onClick={() => setCategoryEditId(tx.id)}
                        title="Click to set category"
                        style={{
                          color: 'var(--muted)',
                          fontSize: 13,
                          cursor: 'pointer',
                          borderRadius: 'var(--radius)',
                          padding: '2px 4px',
                          margin: '-2px -4px',
                          display: 'inline-block',
                          transition: 'background 0.12s',
                        }}
                        className="tx-category-cell"
                      >
                        {tx.category?.name ?? '—'}
                      </span>
                    )
                  ) : (
                    // Viewer — static display
                    <span style={{ color: 'var(--muted)', fontSize: 13 }}>
                      {tx.category?.name ?? '—'}
                    </span>
                  )}

                  <span style={{ color: 'var(--muted)', fontSize: 13 }}>
                    {account?.name ?? '—'}
                  </span>

                  <span style={{ textAlign: 'right' }} className="tx-row-amount">
                    <AmountDisplay tx={tx} currency={account?.currency} />
                  </span>

                  <span style={{ textAlign: 'center' }}>
                    <StatusBadge tx={tx} />
                  </span>

                  {isOwner && (
                    <span className="tx-row-actions" style={{ display: 'flex', gap: 4, justifyContent: 'flex-end' }}>
                      {/* Allocate to savings goals — credit transactions not already typed */}
                      {tx.amount > 0
                        && tx.transaction_type !== 'transfer'
                        && tx.transaction_type !== 'debt_payment'
                        && tx.transaction_type !== 'savings_transfer'
                        && savingsGoals.length > 0 && (
                        <button
                          style={{ ...styles.iconBtn, color: 'var(--green)' }}
                          onClick={() => { setAllocatingTx(tx); setAllocError('') }}
                          title="Allocate to savings goals"
                        >⬡</button>
                      )}
                      {/* Link debit transaction to savings withdrawal */}
                      {tx.amount < 0
                        && tx.transaction_type === 'expense'
                        && savingsGoals.length > 0 && (
                        <button
                          style={{ ...styles.iconBtn, color: 'var(--green)' }}
                          onClick={() => { setWithdrawLinkingTx(tx); setWithdrawGoalId(''); setWithdrawError('') }}
                          title="Link to savings goal withdrawal"
                        >⬡</button>
                      )}
                      {/* Unlink savings withdrawal — debit savings_transfer rows */}
                      {tx.amount < 0 && tx.transaction_type === 'savings_transfer' && (
                        <button
                          style={{ ...styles.iconBtn, color: 'var(--green)' }}
                          onClick={() => handleUnlinkSavingsWithdrawal(tx)}
                          title="Unlink savings withdrawal"
                        >✂</button>
                      )}
                      {/* Mark as transfer pair — for transactions not yet typed as transfer/debt/savings */}
                      {tx.transaction_type !== 'transfer'
                        && tx.transaction_type !== 'debt_payment'
                        && tx.transaction_type !== 'savings_transfer'
                        && !tx.transfer_pair_id && (
                        <button
                          style={{ ...styles.iconBtn, color: 'var(--cyan)' }}
                          onClick={() => { setLinkingTransfer(tx); setTransferPairError('') }}
                          title="Link as transfer pair"
                        >↔</button>
                      )}
                      {/* Unlink transfer pair */}
                      {tx.transaction_type === 'transfer' && tx.transfer_pair_id && (
                        <button
                          style={{ ...styles.iconBtn, color: 'var(--cyan)' }}
                          onClick={() => handleUnlinkTransferPair(tx)}
                          title="Unlink transfer pair"
                        >✂</button>
                      )}
                      {/* Link to debt — only for unlinked debit transactions that are not transfers */}
                      {tx.amount < 0 && !tx.debt_id && tx.transaction_type !== 'transfer' && debts.length > 0 && (
                        <button
                          style={{ ...styles.iconBtn, color: 'var(--purple)' }}
                          onClick={() => { setLinkingTx(tx); setLinkDebtId(''); setLinkError('') }}
                          title="Link to debt"
                        >⛓</button>
                      )}
                      {/* Unlink from debt — only for linked transactions */}
                      {tx.debt_id && (
                        <button
                          style={{ ...styles.iconBtn, color: 'var(--purple)' }}
                          onClick={() => handleUnlinkDebt(tx)}
                          title="Unlink from debt"
                        >✂</button>
                      )}
                      {/* Only manual/unverified entries are editable */}
                      {tx.source === 'manual' && (
                        <button
                          style={styles.iconBtn}
                          onClick={() => { setEditing(tx); setActionError('') }}
                          title="Edit"
                        >✎</button>
                      )}
                      <button
                        style={{ ...styles.iconBtn, color: 'var(--red)' }}
                        onClick={() => { setDeleting(tx); setActionError('') }}
                        title="Delete"
                      >✕</button>
                    </span>
                  )}
                </div>
              )
            })}
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div style={styles.pagination}>
              <Button variant="secondary" size="sm" disabled={page === 0} onClick={() => changePage(page - 1)}>
                ← Prev
              </Button>
              <span style={{ color: 'var(--muted)', fontSize: 13 }}>
                Page {page + 1} of {totalPages}
              </span>
              <Button variant="secondary" size="sm" disabled={page >= totalPages - 1} onClick={() => changePage(page + 1)}>
                Next →
              </Button>
            </div>
          )}
        </>
      )}

      {/* ── FAB (floating action button) — visible on all screen sizes ── */}
      {isOwner && (
        <button
          className="fab"
          onClick={() => { setShowAdd(true); setActionError('') }}
          aria-label="Add transaction"
          title="Quick add transaction"
        >+</button>
      )}

      {/* Add modal */}
      {showAdd && (
        <Modal title="Add transaction" onClose={() => setShowAdd(false)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <AddTransactionForm
            accounts={accounts}
            categories={categories}
            onSave={handleAdd}
            onCancel={() => setShowAdd(false)}
            saving={saving}
          />
        </Modal>
      )}

      {/* Edit modal */}
      {editing && (
        <Modal title="Edit transaction" onClose={() => setEditing(null)}>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <EditTransactionForm
            tx={editing}
            accounts={accounts}
            categories={categories}
            onSave={handleEdit}
            onCancel={() => setEditing(null)}
            saving={saving}
          />
        </Modal>
      )}

      {/* Delete confirmation */}
      {deleting && (
        <Modal title="Delete transaction?" onClose={() => setDeleting(null)} width={400}>
          <p style={{ color: 'var(--white)', marginBottom: 8 }}>
            <strong>{deleting.description ?? 'This transaction'}</strong> on {formatDate(deleting.date)} (
            {formatCurrency(deleting.amount)}) will be permanently removed.
          </p>
          {actionError && <p style={styles.modalError}>{actionError}</p>}
          <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 20 }}>
            <Button variant="secondary" onClick={() => setDeleting(null)}>Cancel</Button>
            <Button variant="danger" onClick={handleDelete} disabled={saving}>
              {saving ? 'Deleting…' : 'Delete'}
            </Button>
          </div>
        </Modal>
      )}

      {/* Import modal */}
      {showImport && (
        <ImportModal
          accounts={accounts}
          onDone={(result) => {
            setReconciliation(result)
            load(0)
          }}
          onClose={() => setShowImport(false)}
        />
      )}

      {/* Link to debt modal */}
      {linkingTx && (
        <LinkToDebtModal
          tx={linkingTx}
          debts={debts}
          linkDebtId={linkDebtId}
          onDebtChange={(id) => { setLinkDebtId(id); setLinkError('') }}
          linkError={linkError}
          linkLoading={linkLoading}
          onConfirm={handleLinkDebt}
          onCancel={() => { setLinkingTx(null); setLinkDebtId(''); setLinkError('') }}
        />
      )}

      {/* Allocate to savings goals modal */}
      {allocatingTx && (
        <AllocateToGoalsModal
          tx={allocatingTx}
          savingsGoals={savingsGoals}
          allocations={allocations}
          onAllocationChange={(goalId, amount) =>
            setAllocations((prev) =>
              prev.map((a) => (a.goal_id === goalId ? { ...a, amount } : a))
            )
          }
          allocError={allocError}
          allocLoading={allocLoading}
          onConfirm={handleLinkSavings}
          onCancel={() => { setAllocatingTx(null); setAllocations([]); setAllocError('') }}
        />
      )}

      {/* Link as transfer pair modal */}
      {linkingTransfer && (
        <LinkTransferPairModal
          sourceTx={linkingTransfer}
          allTransactions={transactions}
          accounts={accounts}
          error={transferPairError}
          loading={transferPairLoading}
          onConfirm={handleLinkTransferPair}
          onCancel={() => { setLinkingTransfer(null); setTransferPairError('') }}
        />
      )}

      {/* Link savings withdrawal modal */}
      {withdrawLinkingTx && (
        <LinkSavingsWithdrawalModal
          tx={withdrawLinkingTx}
          savingsGoals={savingsGoals}
          goalId={withdrawGoalId}
          onGoalChange={(id) => { setWithdrawGoalId(id); setWithdrawError('') }}
          error={withdrawError}
          loading={withdrawLoading}
          onConfirm={handleLinkSavingsWithdrawal}
          onCancel={() => { setWithdrawLinkingTx(null); setWithdrawGoalId(''); setWithdrawError('') }}
        />
      )}

      {/* Bulk delete confirmation */}
      {bulkDeleteConfirm && (
        <div style={{ position: 'fixed', inset: 0, background: 'rgba(0,0,0,0.6)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000 }}>
          <div style={{ background: 'var(--bg)', border: '1px solid var(--selection)', borderRadius: '12px', padding: '28px', width: '360px' }}>
            <h3 style={{ marginTop: 0, color: '#ff5555' }}>Delete {selectedIds.size} transaction{selectedIds.size !== 1 ? 's' : ''}?</h3>
            <p style={{ color: 'var(--comment)', fontSize: '14px', marginBottom: '24px' }}>This cannot be undone.</p>
            {bulkDeleteError && (
              <p style={{ color: '#ff5555', fontSize: '13px', marginBottom: '16px', marginTop: 0 }}>{bulkDeleteError}</p>
            )}
            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button onClick={() => { setBulkDeleteConfirm(false); setBulkDeleteError('') }} style={{ background: 'transparent', border: '1px solid var(--selection)', borderRadius: '6px', color: 'var(--text)', padding: '8px 16px', cursor: 'pointer' }}>Cancel</button>
              <button onClick={handleBulkDelete} style={{ background: 'rgba(255,85,85,0.15)', border: '1px solid rgba(255,85,85,0.4)', borderRadius: '6px', color: '#ff5555', padding: '8px 16px', cursor: 'pointer' }}>Delete</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

// ─── Link to debt modal ───────────────────────────────────────────────────────

function LinkToDebtModal({ tx, debts, linkDebtId, onDebtChange, linkError, linkLoading, onConfirm, onCancel }) {
  const { formatCurrency } = useCurrency()
  return (
    <Modal title="Link transaction to debt" onClose={onCancel} width={460}>
      {/* Transaction summary */}
      <div style={{
        background: 'var(--bg)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '12px 16px',
        marginBottom: 20,
      }}>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>{formatDate(tx.date)}</p>
        <p style={{ fontSize: 14, color: 'var(--white)', marginBottom: 4 }}>
          {tx.description ?? <span style={{ color: 'var(--border)' }}>No description</span>}
        </p>
        <p style={{ fontSize: 16, fontWeight: 700, color: 'var(--pink)' }}>
          {formatCurrency(tx.amount)}
        </p>
      </div>

      <FormField label="Debt to link">
        <select
          style={selectStyle}
          value={linkDebtId}
          onChange={(e) => onDebtChange(e.target.value)}
          autoFocus
        >
          <option value="">Select debt…</option>
          {debts.map((d) => (
            <option key={d.id} value={d.id}>{d.name}</option>
          ))}
        </select>
      </FormField>

      <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 16 }}>
        This will reduce the selected debt's balance by{' '}
        <strong style={{ color: 'var(--white)' }}>{formatCurrency(Math.abs(tx.amount))}</strong>{' '}
        and create an audit entry in the debt's payment history.
      </p>

      {linkError && (
        <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{linkError}</p>
      )}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button onClick={onConfirm} disabled={!linkDebtId || linkLoading}>
          {linkLoading ? 'Linking…' : 'Link to debt'}
        </Button>
      </div>
    </Modal>
  )
}

// ─── Allocate to savings goals modal ─────────────────────────────────────────

function AllocateToGoalsModal({
  tx, savingsGoals, allocations, onAllocationChange,
  allocError, allocLoading, onConfirm, onCancel,
}) {
  const { formatCurrency } = useCurrency()

  const totalAllocated = allocations.reduce((sum, a) => {
    const v = parseFloat(a.amount)
    return sum + (isNaN(v) ? 0 : v)
  }, 0)
  const txAbs = Math.abs(tx.amount)
  const isOverAllocated = totalAllocated > txAbs + 0.001
  const hasAnyAllocation = allocations.some((a) => parseFloat(a.amount) > 0)

  return (
    <Modal title="Allocate to savings goals" onClose={onCancel} width={500}>
      {/* Transaction summary */}
      <div style={{
        background: 'var(--bg)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '12px 16px',
        marginBottom: 16,
      }}>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>{formatDate(tx.date)}</p>
        <p style={{ fontSize: 14, color: 'var(--white)', marginBottom: 4 }}>
          {tx.description ?? <span style={{ color: 'var(--border)' }}>No description</span>}
        </p>
        <p style={{ fontSize: 16, fontWeight: 700, color: 'var(--green)' }}>
          {formatCurrency(txAbs)}
        </p>
      </div>

      <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 16 }}>
        Allocate this amount across your savings goals. Partial allocation is fine — you
        don't need to assign every cent.
      </p>

      {/* Goal rows */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginBottom: 16 }}>
        {savingsGoals.map((goal) => {
          const row = allocations.find((a) => a.goal_id === goal.id)
          return (
            <div key={goal.id} style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <span style={{ flex: 1, fontSize: 14, color: 'var(--white)', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {goal.name}
              </span>
              <span style={{ fontSize: 12, color: 'var(--muted)', whiteSpace: 'nowrap' }}>
                {formatCurrency(goal.current_amount)} saved
              </span>
              <input
                style={{ ...inputStyle, width: 110, textAlign: 'right' }}
                type="number"
                min="0"
                step="0.01"
                placeholder="0.00"
                value={row?.amount ?? ''}
                onChange={(e) => onAllocationChange(goal.id, e.target.value)}
              />
            </div>
          )
        })}
      </div>

      {/* Running total */}
      <div style={{
        display: 'flex',
        justifyContent: 'space-between',
        padding: '10px 0',
        borderTop: '1px solid var(--border)',
        marginBottom: 16,
        fontSize: 14,
        fontWeight: 600,
      }}>
        <span style={{ color: 'var(--muted)' }}>Total allocated</span>
        <span style={{ color: isOverAllocated ? 'var(--red)' : 'var(--white)' }}>
          {formatCurrency(totalAllocated)} of {formatCurrency(txAbs)}
        </span>
      </div>

      {isOverAllocated && (
        <p style={{ fontSize: 13, color: 'var(--red)', marginBottom: 12 }}>
          Total exceeds the transaction amount.
        </p>
      )}

      {allocError && (
        <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{allocError}</p>
      )}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button
          onClick={onConfirm}
          disabled={!hasAnyAllocation || isOverAllocated || allocLoading}
        >
          {allocLoading ? 'Allocating…' : 'Confirm allocation'}
        </Button>
      </div>
    </Modal>
  )
}

// ─── Link as transfer pair modal ─────────────────────────────────────────────

function LinkTransferPairModal({ sourceTx, allTransactions, accounts, error, loading, onConfirm, onCancel }) {
  const { formatCurrency } = useCurrency()
  const [selectedId, setSelectedId] = useState(null)

  // Account lookup
  const accountMap = Object.fromEntries(accounts.map((a) => [a.id, a]))
  const sourceAccount = accountMap[sourceTx.account_id]

  // Filter candidate transactions:
  //   - different account from source
  //   - similar amount (within 20% of abs source amount)
  //   - similar date (±7 days)
  //   - not already in a transfer pair
  //   - not already typed as transfer
  const sourceAbs  = Math.abs(sourceTx.amount)
  const sourceDate = new Date(sourceTx.date)

  const candidates = allTransactions.filter((tx) => {
    if (tx.id === sourceTx.id) return false
    if (tx.account_id === sourceTx.account_id) return false
    if (tx.transfer_pair_id != null) return false
    if (tx.transaction_type === 'transfer') return false

    // Amount within 20% (or within $1 for very small amounts)
    const txAbs = Math.abs(tx.amount)
    const tolerance = Math.max(sourceAbs * 0.2, 1)
    if (Math.abs(txAbs - sourceAbs) > tolerance) return false

    // Date within ±7 days
    const txDate = new Date(tx.date)
    const dayDiff = Math.abs((txDate - sourceDate) / 86400000)
    if (dayDiff > 7) return false

    return true
  })

  return (
    <Modal title="Link as transfer pair" onClose={onCancel} width={520}>
      {/* Source transaction summary */}
      <div style={{
        background: 'var(--bg)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '12px 16px',
        marginBottom: 20,
      }}>
        <p style={{ fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em', color: 'var(--muted)', marginBottom: 6 }}>
          Source transaction
        </p>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 2 }}>{formatDate(sourceTx.date)} · {sourceAccount?.name ?? '—'}</p>
        <p style={{ fontSize: 14, color: 'var(--white)', marginBottom: 4 }}>
          {sourceTx.description ?? <span style={{ color: 'var(--border)' }}>No description</span>}
        </p>
        <p style={{ fontSize: 16, fontWeight: 700, color: sourceTx.amount >= 0 ? 'var(--green)' : 'var(--white)' }}>
          {formatCurrency(sourceTx.amount)}
        </p>
      </div>

      <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 14 }}>
        Select the matching transaction on another account (filtered to different account, similar amount ±20%, ±7 days):
      </p>

      {candidates.length === 0 ? (
        <div style={{
          padding: '20px',
          textAlign: 'center',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          color: 'var(--muted)',
          fontSize: 13,
          marginBottom: 16,
        }}>
          No matching transactions found. Try adjusting the date range or importing the other side.
        </div>
      ) : (
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: 6,
          maxHeight: 240,
          overflowY: 'auto',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius)',
          padding: 8,
          marginBottom: 16,
        }}>
          {candidates.map((tx) => {
            const acct = accountMap[tx.account_id]
            const isSelected = selectedId === tx.id
            return (
              <div
                key={tx.id}
                onClick={() => setSelectedId(tx.id)}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 12,
                  padding: '8px 10px',
                  borderRadius: 'var(--radius)',
                  border: `1px solid ${isSelected ? 'var(--cyan)' : 'transparent'}`,
                  background: isSelected ? 'var(--cyan)12' : 'transparent',
                  cursor: 'pointer',
                  transition: 'all 0.12s',
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 2 }}>
                    {formatDate(tx.date)} · {acct?.name ?? '—'}
                  </p>
                  <p style={{ fontSize: 13, color: 'var(--white)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {tx.description ?? <span style={{ color: 'var(--border)' }}>No description</span>}
                  </p>
                </div>
                <span style={{ fontSize: 14, fontWeight: 700, color: tx.amount >= 0 ? 'var(--green)' : 'var(--white)', whiteSpace: 'nowrap' }}>
                  {formatCurrency(tx.amount)}
                </span>
              </div>
            )
          })}
        </div>
      )}

      {selectedId && (
        <div style={{
          padding: '10px 14px',
          background: 'rgba(139,233,253,0.08)',
          border: '1px solid rgba(139,233,253,0.3)',
          borderRadius: 'var(--radius)',
          marginBottom: 16,
          fontSize: 13,
          color: 'var(--cyan)',
        }}>
          Link these two transactions as a transfer pair? Both will be excluded from budget calculations.
        </div>
      )}

      {error && (
        <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>
      )}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button
          onClick={() => onConfirm(selectedId)}
          disabled={!selectedId || loading}
        >
          {loading ? 'Linking…' : 'Link as transfer pair'}
        </Button>
      </div>
    </Modal>
  )
}

// ─── Link savings withdrawal modal ───────────────────────────────────────────

function LinkSavingsWithdrawalModal({ tx, savingsGoals, goalId, onGoalChange, error, loading, onConfirm, onCancel }) {
  const { formatCurrency } = useCurrency()
  const selectedGoal = savingsGoals.find((g) => g.id === parseInt(goalId))

  return (
    <Modal title="Link to savings goal withdrawal" onClose={onCancel} width={460}>
      {/* Transaction summary */}
      <div style={{
        background: 'var(--bg)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius)',
        padding: '12px 16px',
        marginBottom: 20,
      }}>
        <p style={{ fontSize: 13, color: 'var(--muted)', marginBottom: 4 }}>{formatDate(tx.date)}</p>
        <p style={{ fontSize: 14, color: 'var(--white)', marginBottom: 4 }}>
          {tx.description ?? <span style={{ color: 'var(--border)' }}>No description</span>}
        </p>
        <p style={{ fontSize: 16, fontWeight: 700, color: 'var(--white)' }}>
          {formatCurrency(tx.amount)}
        </p>
      </div>

      <FormField label="Savings goal">
        <select
          style={selectStyle}
          value={goalId}
          onChange={(e) => onGoalChange(e.target.value)}
          autoFocus
        >
          <option value="">Select goal…</option>
          {savingsGoals.map((g) => (
            <option key={g.id} value={g.id}>
              {g.name} ({formatCurrency(g.current_amount)} saved)
            </option>
          ))}
        </select>
      </FormField>

      {selectedGoal && (
        <div style={{
          padding: '10px 14px',
          background: 'rgba(255,85,85,0.08)',
          border: '1px solid rgba(255,85,85,0.3)',
          borderRadius: 'var(--radius)',
          marginBottom: 16,
          fontSize: 13,
          color: 'var(--orange)',
        }}>
          This will reduce <strong style={{ color: 'var(--white)' }}>{selectedGoal.name}</strong>'s balance by{' '}
          <strong style={{ color: 'var(--white)' }}>{formatCurrency(Math.abs(tx.amount))}</strong>.
        </div>
      )}

      {error && (
        <p style={{ color: 'var(--red)', fontSize: 13, marginBottom: 12 }}>{error}</p>
      )}

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button onClick={onConfirm} disabled={!goalId || loading}>
          {loading ? 'Linking…' : 'Link withdrawal'}
        </Button>
      </div>
    </Modal>
  )
}

// ─── Edit form (pre-populated, no source/verified fields) ────────────────────

function EditTransactionForm({ tx, accounts, categories, onSave, onCancel, saving }) {
  const [form, setForm] = useState({
    account_id: tx.account_id,
    amount: tx.amount,
    category_id: tx.category_id ?? '',
    date: tx.date,
    description: tx.description ?? '',
    notes: tx.notes ?? '',
  })

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    onSave({
      amount: parseFloat(form.amount),
      category_id: form.category_id ? parseInt(form.category_id) : null,
      date: form.date,
      description: form.description || null,
      notes: form.notes || null,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      <FormField label="Amount">
        <input style={inputStyle} type="number" step="0.01" value={form.amount} onChange={set('amount')} required inputMode="decimal" />
      </FormField>

      <FormField label="Category">
        <select style={selectStyle} value={form.category_id} onChange={set('category_id')}>
          <option value="">Uncategorised</option>
          {categories.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
        </select>
      </FormField>

      <FormField label="Date">
        <input style={inputStyle} type="date" value={form.date} onChange={set('date')} />
      </FormField>

      <FormField label="Description">
        <input style={inputStyle} value={form.description} onChange={set('description')} />
      </FormField>

      <FormField label="Notes">
        <textarea style={{ ...inputStyle, resize: 'vertical', minHeight: 60 }} value={form.notes} onChange={set('notes')} />
      </FormField>

      <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end', marginTop: 8 }}>
        <Button variant="secondary" onClick={onCancel}>Cancel</Button>
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Save changes'}</Button>
      </div>
    </form>
  )
}

// Returns inline styles for a sortable column header button.
// Active column is highlighted in --white; inactive columns use --muted.
function sortHeaderBtn(sort, column) {
  const isActive = sort.by === column
  return {
    background: 'none',
    border: 'none',
    cursor: 'pointer',
    padding: 0,
    font: 'inherit',
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: isActive ? 'var(--white)' : 'var(--muted)',
    display: 'flex',
    alignItems: 'center',
    gap: 2,
    whiteSpace: 'nowrap',
  }
}

const styles = {
  pageHeader: {
    display: 'flex',
    alignItems: 'flex-start',
    justifyContent: 'space-between',
    marginBottom: 20,
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
  filterBar: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 8,
    marginBottom: 20,
    alignItems: 'center',
  },
  table: {
    background: 'var(--bg-card)',
    border: '1px solid var(--border)',
    borderRadius: 'var(--radius-lg)',
    overflow: 'hidden',
    marginBottom: 16,
  },
  tableHeader: {
    display: 'grid',
    gridTemplateColumns: '100px 1fr 120px 120px 110px 110px 70px',
    alignItems: 'center',
    padding: '10px 20px',
    background: 'var(--bg)',
    fontSize: 11,
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.06em',
    color: 'var(--muted)',
    borderBottom: '1px solid var(--border)',
  },
  tableRow: {
    display: 'grid',
    gridTemplateColumns: '100px 1fr 120px 120px 110px 110px 70px',
    padding: '12px 20px',
    fontSize: 14,
    borderBottom: '1px solid var(--border)',
    alignItems: 'center',
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
  pagination: {
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 16,
    marginTop: 16,
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
  modalError: {
    color: 'var(--red)',
    fontSize: 13,
    marginBottom: 12,
  },
  moreToggle: {
    background: 'none',
    border: 'none',
    color: 'var(--cyan)',
    fontSize: 13,
    cursor: 'pointer',
    padding: '4px 0',
    marginBottom: 12,
  },
}
