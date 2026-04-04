import { useEffect, useState, useCallback, useRef } from 'react'
import client from '../api/client'
import { useAuth } from '../context/AuthContext'
import { useCurrency } from '../context/CurrencyContext'
import Modal from '../components/Modal'
import Button from '../components/Button'
import FormField, { inputStyle, selectStyle } from '../components/FormField'

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

function AddTransactionForm({ accounts, categories, onSave, onCancel, saving }) {
  const today = new Date().toISOString().split('T')[0]
  const [form, setForm] = useState({
    account_id: accounts[0]?.id ?? '',
    amount: '',
    category_id: '',
    date: today,
    description: '',
    notes: '',
  })
  const [showMore, setShowMore] = useState(false)
  const [error, setError] = useState('')

  function set(field) {
    return (e) => setForm((f) => ({ ...f, [field]: e.target.value }))
  }

  function handleSubmit(e) {
    e.preventDefault()
    const amount = parseFloat(form.amount)
    if (isNaN(amount)) { setError('Amount must be a number'); return }
    if (!form.account_id) { setError('Select an account'); return }
    setError('')
    onSave({
      account_id: parseInt(form.account_id),
      amount,
      category_id: form.category_id ? parseInt(form.category_id) : null,
      date: form.date || today,
      description: form.description || null,
      notes: form.notes || null,
    })
  }

  return (
    <form onSubmit={handleSubmit}>
      {/* ── Required fields ── */}
      <FormField label="Account *">
        <select style={selectStyle} value={form.account_id} onChange={set('account_id')} required autoFocus>
          <option value="">Select account…</option>
          {accounts.map((a) => (
            <option key={a.id} value={a.id}>{a.name}</option>
          ))}
        </select>
      </FormField>

      <FormField label="Amount *" hint="Use negative for expenses (e.g. -45.00), positive for income">
        <input
          style={inputStyle}
          type="number"
          step="0.01"
          placeholder="-45.00"
          value={form.amount}
          onChange={set('amount')}
          required
          inputMode="decimal"
        />
      </FormField>

      <FormField label="Category">
        <select style={selectStyle} value={form.category_id} onChange={set('category_id')}>
          <option value="">Uncategorised</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      </FormField>

      {/* ── Optional fields toggle ── */}
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
          <FormField label="Description">
            <input style={inputStyle} value={form.description} onChange={set('description')} placeholder="e.g. Groceries" />
          </FormField>
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
        <Button type="submit" disabled={saving}>{saving ? 'Saving…' : 'Add transaction'}</Button>
      </div>
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
  const [mappingError, setMappingError] = useState('')

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

  // Auto-select first available column when preview loads
  useEffect(() => {
    if (!preview) return
    const cols = preview.columns
    // Heuristic: pick the first column name containing "date", "desc", "amount"
    setDateCol(cols.find((c) => /date/i.test(c)) ?? cols[0] ?? '')
    setDescCol(cols.find((c) => /desc|narr|detail|name|memo/i.test(c)) ?? cols[1] ?? '')
    setAmtCol(cols.find((c) => /amount|amt|debit|credit|value/i.test(c)) ?? cols[2] ?? '')
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
      } catch (e) {
        setMappingError(e.response?.data?.detail ?? 'Failed to preview PDF')
      } finally {
        setPreviewLoading(false)
      }
    } else {
      // For CSV, we'll show column fields without a preview table
      // Fetch a preview anyway so we can populate dropdowns
      setPreviewLoading(true)
      try {
        // CSV preview: read first 5 rows using pandas read_csv on backend
        // We use the same pdf preview logic but for csv — however the backend
        // doesn't have a CSV preview endpoint yet. We'll use generic column names
        // and let users type them in. A note is shown.
        setPreview(null)
      } catch {
        setPreview(null)
      } finally {
        setPreviewLoading(false)
      }
    }
    setStep(2)
  }

  async function handleImport() {
    if (!dateCol || !descCol || !amtCol) {
      setMappingError('All three columns are required')
      return
    }
    setMappingError('')
    setImporting(true)
    try {
      const type = fileTypeOf(selectedFile)
      const endpoint = type === 'pdf' ? '/import/pdf' : '/import/csv'
      const r = await client.post(endpoint, null, {
        params: {
          filename:   selectedFile.filename,
          account_id: accountId,
          date_col:   dateCol,
          desc_col:   descCol,
          amount_col: amtCol,
        },
      })
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

          {type === 'pdf' && preview ? (
            // Dropdown selectors when we know the column names
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
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
              <FormField label="Amount column *">
                <select style={selectStyle} value={amtCol} onChange={(e) => setAmtCol(e.target.value)}>
                  <option value="">Select…</option>
                  {preview.columns.map((c) => <option key={c} value={c}>{c}</option>)}
                </select>
              </FormField>
            </div>
          ) : (
            // Text inputs for CSV (or PDF where preview failed)
            <>
              <p style={{ fontSize: 12, color: 'var(--muted)', marginBottom: 12 }}>
                Enter the exact column header names from your {type === 'pdf' ? 'PDF' : 'CSV'} file.
              </p>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: 12 }}>
                <FormField label="Date column *">
                  <input style={inputStyle} value={dateCol} onChange={(e) => setDateCol(e.target.value)} placeholder="e.g. Date" />
                </FormField>
                <FormField label="Description column *">
                  <input style={inputStyle} value={descCol} onChange={(e) => setDescCol(e.target.value)} placeholder="e.g. Description" />
                </FormField>
                <FormField label="Amount column *">
                  <input style={inputStyle} value={amtCol} onChange={(e) => setAmtCol(e.target.value)} placeholder="e.g. Amount" />
                </FormField>
              </div>
            </>
          )}

          {mappingError && <p style={{ color: 'var(--red)', fontSize: 13, marginTop: 8 }}>{mappingError}</p>}
          {importError  && <p style={{ color: 'var(--red)', fontSize: 13, marginTop: 8 }}>{importError}</p>}

          <div style={importStyles.footer}>
            <Button variant="secondary" onClick={() => { setStep(1); setPreview(null); setImportError('') }}>← Back</Button>
            <Button onClick={handleImport} disabled={importing || !dateCol || !descCol || !amtCol}>
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

  const [filters, setFilters] = useState({
    account_id: '', category_id: '', is_verified: '', date_from: '', date_to: '',
  })

  const [showAdd, setShowAdd]       = useState(false)
  const [showImport, setShowImport] = useState(false)
  const [editing, setEditing]       = useState(null)
  const [deleting, setDeleting]     = useState(null)
  const [saving, setSaving]         = useState(false)
  const [actionError, setActionError] = useState('')
  const [reconciliation, setReconciliation] = useState(null)

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

    const countParams = new URLSearchParams(params)
    countParams.delete('skip')
    countParams.delete('limit')

    Promise.all([
      client.get(`/transactions?${params.toString()}`),
      client.get(`/transactions/count?${countParams.toString()}`),
    ])
      .then(([txRes, countRes]) => {
        setTransactions(txRes.data)
        setTotal(countRes.data.count)
      })
      .catch(console.error)
      .finally(() => setLoading(false))
  }, [filters])

  // Load meta (accounts + categories) once
  useEffect(() => {
    Promise.all([
      client.get('/accounts'),
      client.get('/categories'),
    ]).then(([a, c]) => {
      setAccounts(a.data)
      setCategories(c.data)
    })
  }, [])

  // Reload on filter change, reset to page 0
  useEffect(() => {
    setPage(0)
    load(0)
  }, [filters])

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
      await client.post('/transactions', form)
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
            <div className="tx-table-header" style={styles.tableHeader}>
              <span>Date</span>
              <span>Description</span>
              <span>Category</span>
              <span>Account</span>
              <span style={{ textAlign: 'right' }}>Amount</span>
              <span style={{ textAlign: 'center' }}>Status</span>
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
                  }}
                >
                  <span style={{ color: 'var(--muted)', fontSize: 13 }}>{tx.date}</span>

                  <span style={{ color: isEstimate ? 'var(--muted)' : 'var(--white)' }}>
                    {tx.description ?? <span style={{ color: 'var(--border)' }}>—</span>}
                    {tx.match_note && (
                      <span title={tx.match_note} style={{ marginLeft: 6, fontSize: 11, color: 'var(--orange)', cursor: 'help' }}>⚠</span>
                    )}
                  </span>

                  <span style={{ color: 'var(--muted)', fontSize: 13 }}>
                    {tx.category?.name ?? '—'}
                  </span>

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
            <strong>{deleting.description ?? 'This transaction'}</strong> on {deleting.date} (
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
    </div>
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
