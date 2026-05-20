import { useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import client from '../api/client'
import { useCurrency } from '../context/CurrencyContext'
import Button from '../components/Button'
import useBreakpoint from '../hooks/useBreakpoint'
import { parseServerDate } from '../utils/dateFormat'

// Option B — STEPS is now a function. When the PDF parser surfaces multiple
// candidate tables, an extra "Pick table" step is injected between Upload
// and Match columns. Step keys stay stable strings; the displayed step
// number is the index + 1 (no "Step 2.5" hack). LOCKED (IRIS-1).
function buildSteps(hasMultipleCandidates) {
  const steps = [
    { key: 'account', title: 'Choose account',   hint: 'Where these transactions land.' },
    { key: 'upload',  title: 'Upload file',      hint: 'CSV or PDF.' },
  ]
  if (hasMultipleCandidates) {
    steps.push({ key: 'pick_table', title: 'Pick table', hint: 'We found more than one.' })
  }
  steps.push(
    { key: 'map',    title: 'Match columns',    hint: 'Tell us what each column is.' },
    { key: 'review', title: 'Review & confirm', hint: 'Last chance before writing.' },
    { key: 'done',   title: 'Imported',         hint: 'Undo for 5 min.' },
  )
  return steps.map((s, i) => ({ ...s, n: i + 1 }))
}

const SUPPORTED_FORMATS = { csv: true, pdf: true, ofx: false, qif: false }

function formatRollbackCountdown(secondsLeft) {
  if (secondsLeft >= 60) {
    const m = Math.floor(secondsLeft / 60)
    const s = secondsLeft % 60
    return s === 0 ? `${m}m` : `${m}m ${s}s`
  }
  return `${secondsLeft}s`
}

// ─── Step rail ───────────────────────────────────────────────────────────────
function StepRail({ steps, current, onJump }) {
  return (
    <div style={{
      width: 240, padding: '24px 18px', borderRight: '1px solid var(--border)',
      background: 'var(--bg-elevated)', display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: 'var(--text-faint)',
        textTransform: 'uppercase', letterSpacing: '0.08em', marginBottom: 14,
      }}>Import transactions</div>
      {steps.map(s => {
        const state = s.n < current ? 'done' : s.n === current ? 'active' : 'future'
        const clickable = state === 'done'
        return (
          <div
            key={s.key}
            onClick={clickable ? () => onJump(s.n) : undefined}
            style={{
              display: 'grid', gridTemplateColumns: '28px 1fr', gap: 10,
              padding: '8px 8px', borderRadius: 8,
              background: state === 'active' ? 'color-mix(in oklab, var(--brand) 14%, transparent)' : 'transparent',
              cursor: clickable ? 'pointer' : 'default',
              opacity: state === 'future' ? 0.5 : 1,
            }}>
            <div style={{
              width: 24, height: 24, borderRadius: 999,
              display: 'grid', placeItems: 'center',
              fontSize: 11, fontWeight: 700, fontVariantNumeric: 'tabular-nums',
              background: state === 'done'   ? 'var(--positive)'
                       : state === 'active' ? 'var(--brand)'
                       : 'var(--bg-input)',
              color: state === 'future' ? 'var(--text-faint)' : 'var(--brand-ink)',
              border: state === 'future' ? '1px solid var(--border)' : 'none',
            }}>{state === 'done' ? '✓' : s.n}</div>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, color: state === 'future' ? 'var(--text-faint)' : 'var(--text)' }}>
                {s.title}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-faint)', marginTop: 2 }}>{s.hint}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

// ─── Locked account header ───────────────────────────────────────────────────
function AccountHeader({ account }) {
  const { formatCurrency } = useCurrency()
  if (!account) return null
  return (
    <div style={{
      padding: '16px 28px', borderBottom: '1px solid var(--border)',
      display: 'flex', alignItems: 'center', gap: 14,
      background: 'var(--bg-elevated)',
    }}>
      <div style={{
        fontSize: 11, fontWeight: 700, color: 'var(--text-faint)',
        textTransform: 'uppercase', letterSpacing: '0.08em',
      }}>Importing into</div>
      <div style={{ fontSize: 18, fontWeight: 700, color: 'var(--text)' }}>
        {account.name}
        {account.account_type && (
          <span style={{
            marginLeft: 10, fontSize: 13, color: 'var(--text-faint)',
            fontWeight: 500,
          }}>{account.account_type}</span>
        )}
      </div>
      <div style={{ flex: 1 }}/>
      <div style={{ textAlign: 'right' }}>
        <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>Current balance</div>
        <div style={{ fontSize: 15, fontWeight: 600, color: 'var(--text)', fontVariantNumeric: 'tabular-nums' }}>
          {formatCurrency(account.balance)}
        </div>
      </div>
    </div>
  )
}

// ─── Footer with Back / primary CTA ──────────────────────────────────────────
function StepFooter({ onBack, onNext, nextLabel = 'Continue', nextDisabled, primary = true }) {
  return (
    <div style={{
      padding: '16px 28px', borderTop: '1px solid var(--border)',
      display: 'flex', justifyContent: 'space-between',
      background: 'var(--bg-elevated)',
    }}>
      <Button variant="ghost" onClick={onBack} disabled={!onBack}>{onBack ? '← Back' : ' '}</Button>
      <Button variant={primary ? 'primary' : 'secondary'} onClick={onNext} disabled={nextDisabled}>{nextLabel}</Button>
    </div>
  )
}

// ─── Step 1: Choose account ──────────────────────────────────────────────────
function StepChooseAccount({ accounts, selectedId, onSelect, onCancel, onNext }) {
  const { formatCurrency } = useCurrency()
  return (
    <>
      <div style={{ flex: 1, overflow: 'auto', padding: '28px 32px' }}>
        <div style={{ marginBottom: 20 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>Where should these transactions go?</h2>
          <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-faint)' }}>
            The account you pick is locked for the rest of this import.
          </p>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, 1fr)', gap: 10 }}>
          {accounts.map(a => {
            const active = a.id === selectedId
            return (
              <button
                key={a.id}
                onClick={() => onSelect(a.id)}
                style={{
                  textAlign: 'left', padding: 16,
                  background: active ? 'color-mix(in oklab, var(--brand) 12%, var(--bg-elevated))' : 'var(--bg-elevated)',
                  border: `1px solid ${active ? 'var(--brand)' : 'var(--border)'}`,
                  borderRadius: 10, cursor: 'pointer',
                  display: 'grid', gridTemplateColumns: '36px 1fr auto', gap: 12, alignItems: 'center',
                }}>
                <div style={{ width: 32, height: 32, borderRadius: 8, background: 'var(--brand)' }}/>
                <div>
                  <div style={{ fontWeight: 600, color: 'var(--text)', fontSize: 14 }}>{a.name}</div>
                  <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>{a.account_type || 'Account'}</div>
                </div>
                <div style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-muted)', fontSize: 13 }}>
                  {formatCurrency(a.balance)}
                </div>
              </button>
            )
          })}
        </div>
      </div>
      <StepFooter onBack={onCancel} onNext={onNext} nextDisabled={!selectedId} nextLabel="Continue →"/>
    </>
  )
}

// ─── Step 2: Upload file ─────────────────────────────────────────────────────
function StepUpload({ account, onBack, onUploaded }) {
  const [format, setFormat] = useState('csv')
  const [file,   setFile]   = useState(null)
  const [error,  setError]  = useState(null)
  const [busy,   setBusy]   = useState(false)
  const inputRef = useRef(null)

  const upload = async () => {
    if (!file) return
    setBusy(true); setError(null)
    try {
      const form = new FormData()
      form.append('file', file)
      // account_id and format are Query params — do NOT append to form body
      const { data } = await client.post('/imports', form, {
        params: { account_id: account.id, format },
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      onUploaded(data, file, format)
    } catch (e) {
      setError(e.response?.data?.detail?.message || e.response?.data?.detail || e.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <div style={{ flex: 1, overflow: 'auto', padding: '28px 32px' }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>Upload your statement file</h2>

        {/* Format tabs */}
        <div style={{ display: 'flex', gap: 6, marginBottom: 16 }}>
          {[
            { k: 'csv', label: 'CSV',  hint: 'Most banks · spreadsheets' },
            { k: 'pdf', label: 'PDF',  hint: 'Bank statements · printed exports' },
            { k: 'ofx', label: 'OFX',  hint: 'Quicken · MS Money' },
            { k: 'qif', label: 'QIF',  hint: 'Older finance apps' },
          ].map(f => {
            const enabled = SUPPORTED_FORMATS[f.k]
            const active  = f.k === format
            return (
              <button
                key={f.k}
                disabled={!enabled}
                onClick={() => setFormat(f.k)}
                style={{
                  flex: 1, padding: '10px 14px', borderRadius: 8,
                  background: active ? 'var(--bg-hover)' : 'var(--bg-elevated)',
                  border: `1px solid ${active ? 'var(--brand)' : 'var(--border)'}`,
                  color: !enabled ? 'var(--text-faint)' : active ? 'var(--text)' : 'var(--text-muted)',
                  cursor: enabled ? 'pointer' : 'not-allowed', textAlign: 'left',
                }}>
                <div style={{ fontWeight: 600, fontSize: 13 }}>
                  {f.label}{!enabled && <span style={{ marginLeft: 6, fontSize: 10, fontWeight: 500 }}>· soon</span>}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-faint)' }}>{f.hint}</div>
              </button>
            )
          })}
        </div>

        {/* Drop zone */}
        <div
          onClick={() => inputRef.current?.click()}
          onDragOver={e => { e.preventDefault() }}
          onDrop={e => { e.preventDefault(); if (e.dataTransfer.files[0]) setFile(e.dataTransfer.files[0]) }}
          style={{
            padding: 40, borderRadius: 12,
            border: `2px dashed ${file ? 'var(--brand)' : 'var(--border)'}`,
            background: 'var(--bg-elevated)', textAlign: 'center', cursor: 'pointer',
          }}>
          <div style={{ fontSize: 16, fontWeight: 600, color: 'var(--text)' }}>
            {file ? file.name : `Drop your .${format} file here`}
          </div>
          <div style={{ fontSize: 12, color: 'var(--text-faint)', marginTop: 6 }}>
            {file ? `${(file.size / 1024).toFixed(1)} KB · click to choose a different file` : 'or click to choose · max 10 MB'}
          </div>
          <input
            ref={inputRef} type="file" hidden
            // LOCKED (§ 5.4): CSV → .csv,text/csv ; PDF → .pdf,application/pdf
            accept={format === 'csv' ? '.csv,text/csv'
                  : format === 'pdf' ? '.pdf,application/pdf'
                  : `.${format}`}
            onChange={e => setFile(e.target.files[0] || null)}
          />
        </div>

        {error && (
          <div style={{
            marginTop: 14, padding: '10px 14px', borderRadius: 8,
            background: 'color-mix(in oklab, var(--negative) 12%, transparent)',
            border: '1px solid color-mix(in oklab, var(--negative) 35%, transparent)',
            color: 'var(--negative)', fontSize: 13,
          }}>{typeof error === 'string' ? error : JSON.stringify(error)}</div>
        )}
      </div>
      <StepFooter
        onBack={onBack}
        onNext={upload}
        nextDisabled={!file || busy}
        nextLabel={busy ? 'Parsing…' : 'Continue →'}
      />
    </>
  )
}

// ─── Step (conditional): Pick table — LOCKED IRIS-2..6 ───────────────────────
function StepPickTable({ candidates, strategy, onBack, onConfirm, busy }) {
  const [selected, setSelected] = useState(null)
  return (
    <>
      <div style={{ flex: 1, overflow: 'auto', padding: '28px 32px' }}>
        <div style={{ marginBottom: 12 }}>
          <h2 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>
            We found {candidates.length} tables in this PDF — which one are your transactions?
          </h2>
          {/* IRIS-6: faint caption surfaces the parser strategy without being interactive. */}
          {strategy && (
            <div style={{
              fontSize: 11, color: 'var(--text-faint)', marginTop: 6,
              textTransform: 'uppercase', letterSpacing: '0.08em',
            }}>
              Strategy · {strategy}
            </div>
          )}
        </div>
        <div style={{ display: 'grid', gap: 10 }}>
          {candidates.map(c => {
            const active = c.index === selected
            return (
              <button
                key={c.index}
                onClick={() => setSelected(c.index)}
                disabled={busy}
                style={{
                  textAlign: 'left', padding: 16,
                  background: active ? 'color-mix(in oklab, var(--brand) 12%, var(--bg-elevated))' : 'var(--bg-elevated)',
                  border: `1px solid ${active ? 'var(--brand)' : 'var(--border)'}`,
                  borderRadius: 10, cursor: busy ? 'wait' : 'pointer',
                  display: 'flex', flexDirection: 'column', gap: 8,
                }}>
                <div style={{ fontWeight: 600, color: 'var(--text)', fontSize: 14 }}>
                  Table {c.index + 1}
                  <span style={{ color: 'var(--text-faint)', fontWeight: 500 }}>
                    {' '}· {c.row_count} rows · {c.column_count} columns
                  </span>
                </div>
                {/* IRIS-3: horizontally-scrolling monospace preview strip, per-cell 160px cap */}
                <div style={{
                  display: 'flex', gap: 6, overflowX: 'auto',
                  fontFamily: 'JetBrains Mono, monospace', fontSize: 11,
                }}>
                  {(c.first_row_preview || []).map((cell, i) => (
                    <div key={i} style={{
                      maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap', padding: '4px 8px',
                      background: 'var(--bg-input)', borderRadius: 4, color: 'var(--text-muted)',
                    }}>{cell}</div>
                  ))}
                </div>
              </button>
            )
          })}
        </div>
      </div>
      <StepFooter
        onBack={onBack}
        onNext={() => onConfirm(selected)}
        nextDisabled={selected === null || busy}
        nextLabel={busy ? 'Loading…' : 'Continue →'}
      />
    </>
  )
}

// ─── Step: Match columns ─────────────────────────────────────────────────────
// Always-shown fields. Amount handling is mode-dependent (single vs split):
//   • Single  — one signed "Amount" column.
//   • Split   — separate "Money in (Credit)" + "Money out (Debit)" columns,
//               e.g. statements that put deposits and withdrawals in two columns.
// FE-001: split files previously dropped every debit row to $0.00.
const BASE_FIELDS = [
  { key: 'date',        label: 'Date'        },
  { key: 'description', label: 'Description' },
]
const SINGLE_AMOUNT_FIELDS = [
  { key: 'amount', label: 'Amount' },
]
const SPLIT_AMOUNT_FIELDS = [
  { key: 'credit', label: 'Money in (Credit)' },
  { key: 'debit',  label: 'Money out (Debit)' },
]

function StepMapColumns({ draft, onBack, onMapped }) {
  const [mapping, setMapping] = useState(draft.column_mapping || {})
  // Start in split mode if the draft arrived with a credit/debit mapping.
  const [splitAmount, setSplitAmount] = useState(
    () => (draft.column_mapping?.credit != null || draft.column_mapping?.debit != null)
  )
  const [busy, setBusy] = useState(false)
  const headers = draft.parsed_meta?.header || []
  // Use raw row data from draft rows for the sample preview
  const sample  = draft.rows?.slice(0, 3).map(r => r.raw || []) || []

  const fields = [
    ...BASE_FIELDS,
    ...(splitAmount ? SPLIT_AMOUNT_FIELDS : SINGLE_AMOUNT_FIELDS),
  ]

  // Date + Description always required. Amount source: single needs Amount;
  // split needs at least one of Credit / Debit.
  const baseSet = BASE_FIELDS.every(f => mapping[f.key] != null)
  const amountSet = splitAmount
    ? (mapping.credit != null || mapping.debit != null)
    : mapping.amount != null
  const allRequiredSet = baseSet && amountSet

  // Toggling modes clears the other mode's keys so we never PATCH a stale pair.
  const toggleSplit = () => {
    setSplitAmount(prev => {
      const next = !prev
      setMapping(m => {
        const { amount, credit, debit, ...rest } = m
        return rest
      })
      return next
    })
  }

  const save = async () => {
    setBusy(true)
    try {
      // Send only the keys for the active mode; drop unset (undefined) keys.
      const activeKeys = ['date', 'description', ...(splitAmount ? ['credit', 'debit'] : ['amount'])]
      const payload = {}
      for (const k of activeKeys) {
        if (mapping[k] != null) payload[k] = mapping[k]
      }
      const { data } = await client.patch(`/imports/${draft.id}`, { column_mapping: payload })
      onMapped(data)
    } finally { setBusy(false) }
  }

  return (
    <>
      <div style={{ flex: 1, overflow: 'auto', padding: '28px 32px' }}>
        <h2 style={{ margin: '0 0 4px', fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>Match columns to fields</h2>
        <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--text-faint)' }}>
          We've taken a guess. Adjust if anything's wrong.
        </p>

        <label style={{
          display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16,
          fontSize: 13, color: 'var(--text-muted)', cursor: 'pointer',
        }}>
          <input
            type="checkbox"
            checked={splitAmount}
            onChange={toggleSplit}
            style={{ width: 16, height: 16, accentColor: 'var(--brand)', cursor: 'pointer' }}
          />
          My file uses separate columns for money in and money out
        </label>

        <div style={{
          background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 10,
          overflow: 'hidden',
        }}>
          {fields.map((f, i) => (
            <div key={f.key} style={{
              display: 'grid', gridTemplateColumns: '180px 1fr 1fr',
              gap: 16, padding: '14px 18px',
              borderBottom: i < fields.length - 1 ? '1px solid var(--border)' : 'none',
              alignItems: 'center',
            }}>
              <div>
                <div style={{ fontWeight: 600, color: 'var(--text)', fontSize: 14 }}>
                  {f.label}{!splitAmount || (f.key !== 'credit' && f.key !== 'debit')
                    ? <span style={{ color: 'var(--negative)', marginLeft: 4 }}>*</span>
                    : null}
                </div>
              </div>
              <select
                value={mapping[f.key] ?? ''}
                onChange={e => setMapping({ ...mapping, [f.key]: e.target.value === '' ? undefined : Number(e.target.value) })}
                style={{
                  padding: '8px 10px', borderRadius: 6,
                  background: 'var(--bg-input)', border: '1px solid var(--border)',
                  color: 'var(--text)', fontSize: 13,
                }}>
                <option value="">— Don't map —</option>
                {headers.map((h, idx) => <option key={idx} value={idx}>{h}</option>)}
              </select>
              <div style={{ fontSize: 12, color: 'var(--text-faint)', fontFamily: 'JetBrains Mono, monospace' }}>
                {mapping[f.key] != null ? `e.g. ${sample[0]?.[mapping[f.key]] ?? '—'}` : '—'}
              </div>
            </div>
          ))}
        </div>

        {sample.length > 0 && (
          <>
            <div style={{ marginTop: 22, fontSize: 11, fontWeight: 700, color: 'var(--text-faint)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
              Sample · first {sample.length} row{sample.length !== 1 ? 's' : ''}
            </div>
            <div style={{
              marginTop: 8, background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 10,
              overflow: 'auto', fontFamily: 'JetBrains Mono, monospace', fontSize: 12,
              WebkitOverflowScrolling: 'touch',
              maskImage: 'linear-gradient(to right, #000 calc(100% - 24px), transparent)',
              WebkitMaskImage: 'linear-gradient(to right, #000 calc(100% - 24px), transparent)',
            }}>
              <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                <thead>
                  <tr style={{ background: 'var(--bg)' }}>
                    {headers.map((h, i) => (
                      <th key={i} style={{
                        padding: '8px 12px', textAlign: 'left',
                        color: 'var(--text-faint)', fontWeight: 600, fontSize: 11,
                        borderBottom: '1px solid var(--border)',
                      }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sample.map((row, i) => (
                    <tr key={i}>
                      {row.map((cell, j) => (
                        <td key={j} style={{ padding: '8px 12px', color: 'var(--text-muted)', borderBottom: i < sample.length - 1 ? '1px solid var(--border)' : 'none' }}>
                          {cell}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </>
        )}
      </div>
      <StepFooter
        onBack={onBack}
        onNext={save}
        nextDisabled={!allRequiredSet || busy}
        nextLabel={busy ? 'Saving…' : 'Continue →'}
      />
    </>
  )
}

// ─── Step: Review & confirm ──────────────────────────────────────────────────
function SummaryStat({ label, value, tone = 'var(--text)' }) {
  return (
    <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 10, padding: '12px 16px' }}>
      <div style={{ fontSize: 11, color: 'var(--text-faint)', fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700, color: tone, marginTop: 4, fontVariantNumeric: 'tabular-nums' }}>{value}</div>
    </div>
  )
}

function StepReview({ draft, account, onBack, onCommitted }) {
  const { formatCurrency } = useCurrency()
  const [preview, setPreview] = useState(draft)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    let ignore = false
    client.get(`/imports/${draft.id}/preview`).then(r => { if (!ignore) setPreview(r.data) })
    return () => { ignore = true }
  }, [draft.id])

  const toggleExclude = async (rowId, currentlyExcluded) => {
    const next = { ...preview }
    next.rows = preview.rows.map(r => r.id === rowId ? { ...r, excluded: !currentlyExcluded } : r)
    setPreview(next)
    client.patch(`/imports/${draft.id}`, { row_updates: [{ id: rowId, excluded: !currentlyExcluded }] }).catch(() => {})
  }

  const commit = async () => {
    setBusy(true); setError(null)
    try {
      const { data } = await client.post(`/imports/${draft.id}/commit`)
      onCommitted(data)
    } catch (e) {
      setError(e.response?.data?.detail || 'Import failed')
    } finally { setBusy(false) }
  }

  if (!preview.rows) return <div style={{ padding: 32, color: 'var(--text-faint)' }}>Loading preview…</div>

  const willImport = preview.rows.filter(r => !r.excluded).length
  const dupCount   = preview.rows.filter(r => r.duplicate_of).length

  return (
    <>
      <div style={{ flex: 1, overflow: 'auto', padding: '28px 32px' }}>
        <h2 style={{ margin: '0 0 20px', fontSize: 20, fontWeight: 700, color: 'var(--text)' }}>Review what will be imported</h2>

        {/* Summary strip */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, marginBottom: 18 }}>
          <SummaryStat label="Rows in file"   value={preview.summary?.total ?? preview.rows.length}/>
          <SummaryStat label="Duplicates"     value={dupCount} tone={dupCount > 0 ? 'var(--warning)' : 'var(--text)'}/>
          <SummaryStat label="Will import"    value={willImport} tone="var(--positive)"/>
        </div>

        {error && (
          <div style={{
            marginBottom: 14, padding: '10px 14px', borderRadius: 8,
            background: 'color-mix(in oklab, var(--negative) 12%, transparent)',
            border: '1px solid color-mix(in oklab, var(--negative) 35%, transparent)',
            color: 'var(--negative)', fontSize: 13,
          }}>{typeof error === 'string' ? error : JSON.stringify(error)}</div>
        )}

        {/* Rows table */}
        <div style={{ background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{
            display: 'grid', gridTemplateColumns: '40px 90px 1fr 110px 110px',
            padding: '10px 14px', background: 'var(--bg)',
            borderBottom: '1px solid var(--border)',
            fontSize: 10, fontWeight: 700, color: 'var(--text-faint)',
            textTransform: 'uppercase', letterSpacing: '0.08em',
          }}>
            <span></span><span>Date</span><span>Description</span><span>Status</span><span style={{ textAlign: 'right' }}>Amount</span>
          </div>
          {preview.rows.map(row => (
            <div key={row.id} style={{
              display: 'grid', gridTemplateColumns: '40px 90px 1fr 110px 110px',
              padding: '10px 14px', borderBottom: '1px solid var(--border)',
              alignItems: 'center', fontSize: 13,
              opacity: row.excluded ? 0.45 : 1,
              background: row.duplicate_of ? 'color-mix(in oklab, var(--warning) 5%, transparent)' : 'transparent',
            }}>
              <input
                type="checkbox"
                checked={!row.excluded}
                onChange={() => toggleExclude(row.id, row.excluded)}
                style={{ accentColor: 'var(--brand)' }}
              />
              <span style={{ color: 'var(--text-faint)', fontSize: 12, fontVariantNumeric: 'tabular-nums' }}>{row.date}</span>
              <span style={{ color: 'var(--text)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.description}</span>
              <span style={{ fontSize: 11 }}>
                {row.duplicate_of ? <span style={{ color: 'var(--warning)' }}>Duplicate</span> : <span style={{ color: 'var(--positive)' }}>New</span>}
              </span>
              <span style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontWeight: 600, color: row.amount >= 0 ? 'var(--positive)' : 'var(--text)' }}>
                {formatCurrency(row.amount)}
              </span>
            </div>
          ))}
        </div>
      </div>
      <StepFooter
        onBack={onBack}
        onNext={commit}
        nextDisabled={busy || willImport === 0}
        nextLabel={busy ? 'Importing…' : `Import ${willImport} transactions →`}
      />
    </>
  )
}

// ─── Step: Imported (success + undo banner) ──────────────────────────────────
function StepDone({ commit, onClose }) {
  const navigate = useNavigate()
  const { formatCurrency } = useCurrency()
  // FE-003: parse the server timestamp as UTC. An offset-less string would
  // otherwise be read as local time and clamp the countdown to 0 for UTC+ users.
  const rollbackUntil = useMemo(
    () => (parseServerDate(commit.rollback_until)?.getTime() ?? 0),
    [commit.rollback_until],
  )
  const [secondsLeft, setSecondsLeft] = useState(() => Math.max(0, Math.round((rollbackUntil - Date.now()) / 1000)))
  const [rolledBack, setRolledBack] = useState(false)
  const [rolling, setRolling] = useState(false)
  const [error, setError] = useState(null)

  useEffect(() => {
    if (rolledBack || secondsLeft <= 0) return
    const id = setInterval(() => {
      setSecondsLeft(Math.max(0, Math.round((rollbackUntil - Date.now()) / 1000)))
    }, 250)
    return () => clearInterval(id)
  }, [rollbackUntil, rolledBack, secondsLeft])

  const rollback = async () => {
    setRolling(true); setError(null)
    try {
      await client.post(`/imports/${commit.id}/rollback`)
      setRolledBack(true)
    } catch (e) {
      setError(e.response?.data?.detail || 'Could not roll back')
    } finally { setRolling(false) }
  }

  return (
    <div style={{ flex: 1, overflow: 'auto', padding: '40px 32px', display: 'grid', placeContent: 'center', textAlign: 'center' }}>
      <div style={{
        margin: '0 auto 18px', width: 56, height: 56, borderRadius: 999,
        background: rolledBack ? 'color-mix(in oklab, var(--text-faint) 25%, transparent)' : 'color-mix(in oklab, var(--positive) 25%, transparent)',
        color: rolledBack ? 'var(--text-faint)' : 'var(--positive)',
        display: 'grid', placeItems: 'center', fontSize: 28,
      }}>{rolledBack ? '↶' : '✓'}</div>

      <h2 style={{ margin: 0, fontSize: 22, fontWeight: 700, color: 'var(--text)' }}>
        {rolledBack
          ? 'Import rolled back'
          : (commit.matched_count > 0
              ? `${commit.transactions_created} imported · ${commit.matched_count} matched existing`
              : `${commit.transactions_created} transactions imported`)}
      </h2>
      <p style={{ margin: '6px 0 24px', fontSize: 13, color: 'var(--text-faint)' }}>
        {rolledBack ? 'Nothing was kept. You can start over.' : 'They\'re live in your transactions list.'}
      </p>

      {/* A8: surface matched estimates whose amount the bank revised, so the user can
          eyeball them inside the rollback window. */}
      {!rolledBack && (commit.amount_diff_warnings?.length ?? 0) > 0 && (
        <div style={{
          margin: '0 auto 24px', maxWidth: 480, padding: '14px 18px', textAlign: 'left',
          background: 'var(--bg-elevated)', border: '1px solid color-mix(in oklab, var(--warning) 35%, transparent)',
          borderRadius: 10,
        }}>
          <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--warning)', marginBottom: 8 }}>
            {commit.amount_diff_warnings.length} estimate{commit.amount_diff_warnings.length > 1 ? 's' : ''} updated to the bank amount
          </div>
          {commit.amount_diff_warnings.map(w => (
            <div key={w.transaction_id} style={{
              display: 'flex', justifyContent: 'space-between', gap: 12,
              fontSize: 12, color: 'var(--text-muted)', padding: '3px 0',
            }}>
              <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {w.description || '—'}
              </span>
              <span style={{ fontVariantNumeric: 'tabular-nums', whiteSpace: 'nowrap', color: 'var(--text)' }}>
                {formatCurrency(w.manual_amount)} → {formatCurrency(w.bank_amount)}
              </span>
            </div>
          ))}
        </div>
      )}

      {!rolledBack && secondsLeft > 0 && (
        <div style={{
          margin: '0 auto', maxWidth: 480, padding: '14px 18px',
          background: 'var(--bg-elevated)', border: '1px solid var(--border)', borderRadius: 10,
          display: 'flex', alignItems: 'center', gap: 14, justifyContent: 'space-between',
        }}>
          <div style={{ textAlign: 'left' }}>
            <div style={{ fontSize: 13, fontWeight: 600, color: 'var(--text)' }}>Made a mistake?</div>
            <div style={{ fontSize: 12, color: 'var(--text-faint)' }}>
              You can undo for {formatRollbackCountdown(secondsLeft)}. Undo removes the {commit.transactions_created} imported transactions{commit.matched_count > 0 ? `, reverts the ${commit.matched_count} matched estimate${commit.matched_count === 1 ? '' : 's'},` : ''} and any edits to them.
            </div>
          </div>
          <Button variant="secondary" onClick={rollback} disabled={rolling}>
            {rolling ? 'Undoing…' : 'Undo import'}
          </Button>
        </div>
      )}

      {error && (
        <div style={{ marginTop: 12, fontSize: 12, color: 'var(--negative)' }}>{typeof error === 'string' ? error : JSON.stringify(error)}</div>
      )}

      <div style={{ marginTop: 28, display: 'flex', gap: 10, justifyContent: 'center' }}>
        <Button variant="ghost"   onClick={onClose}>Close</Button>
        <Button variant="primary" onClick={() => navigate('/transactions')}>Go to transactions →</Button>
      </div>
    </div>
  )
}

// ─── Page shell ──────────────────────────────────────────────────────────────
export default function ImportWizard() {
  const navigate = useNavigate()
  const { isMobile } = useBreakpoint()

  const [step,       setStep]       = useState(1)
  const [accounts,   setAccounts]   = useState([])
  const [accountId,  setAccountId]  = useState(null)
  const [draft,      setDraft]      = useState(null)
  const [commitData, setCommitData] = useState(null)
  // Option B — keep the original uploaded bytes around so the user can
  // re-upload with a different selected_table_index without reselecting.
  const [uploadFile, setUploadFile] = useState(null)
  const [uploadFormat, setUploadFormat] = useState('csv')
  const [pickBusy,   setPickBusy]   = useState(false)

  // Steps list responds to whether the current draft has multiple PDF
  // candidates. Mid-wizard transition (no candidates → 2+ candidates) is
  // fine because the step state is an index, not a hard-coded number.
  const hasMultiple = (draft?.candidate_tables?.length ?? 0) > 1
  const steps = useMemo(() => buildSteps(hasMultiple), [hasMultiple])
  const currentKey = steps[step - 1]?.key

  useEffect(() => {
    client.get('/accounts').then(r => setAccounts(r.data))
  }, [])

  const account = useMemo(() => accounts.find(a => a.id === accountId), [accounts, accountId])

  const cancelAndClose = async () => {
    if (draft && !commitData) {
      try { await client.delete(`/imports/${draft.id}`) } catch (_) {}
    }
    navigate('/transactions')
  }

  // After a successful upload we know whether the wizard needs the
  // Pick-table step. Step indices are recomputed from the active steps array
  // so we always advance to the right "next" step regardless of insertion.
  const onUploaded = (newDraft, file, fmt) => {
    setDraft(newDraft)
    setUploadFile(file)
    setUploadFormat(fmt)
    // Advance to the step after 'upload'.
    const nextSteps = buildSteps((newDraft?.candidate_tables?.length ?? 0) > 1)
    const uploadIdx = nextSteps.findIndex(s => s.key === 'upload')
    setStep(uploadIdx + 2)   // +1 to convert idx→step number, +1 to move forward
  }

  // LOCKED (MASON Q2): table re-pick is DELETE + re-upload with ?selected_table_index=N.
  const onPickTable = async (index) => {
    if (index === null || !uploadFile) return
    setPickBusy(true)
    try {
      // Drop the existing draft before re-uploading so we don't leak rows.
      try { await client.delete(`/imports/${draft.id}`) } catch (_) {}
      const form = new FormData()
      form.append('file', uploadFile)
      const { data } = await client.post('/imports', form, {
        params: {
          account_id: account.id,
          format: uploadFormat,
          selected_table_index: index,
        },
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      setDraft(data)
      // Advance to 'map' step.
      const nextSteps = buildSteps((data?.candidate_tables?.length ?? 0) > 1)
      const mapIdx = nextSteps.findIndex(s => s.key === 'map')
      setStep(mapIdx + 1)
    } finally {
      setPickBusy(false)
    }
  }

  const goBack = (toKey) => {
    const idx = steps.findIndex(s => s.key === toKey)
    if (idx >= 0) setStep(idx + 1)
  }

  return (
    <div style={{ display: 'flex', flexDirection: isMobile ? 'column' : 'row', height: '100%', background: 'var(--bg)' }}>
      {!isMobile && <StepRail steps={steps} current={step} onJump={n => { if (n < step) setStep(n) }}/>}
      <div style={{ flex: 1, display: 'flex', flexDirection: 'column', minWidth: 0 }}>
        {step >= 2 && account && <AccountHeader account={account}/>}

        {currentKey === 'account' && (
          <StepChooseAccount
            accounts={accounts}
            selectedId={accountId}
            onSelect={setAccountId}
            onCancel={cancelAndClose}
            onNext={() => setStep(2)}
          />
        )}
        {currentKey === 'upload' && (
          <StepUpload
            account={account}
            onBack={() => goBack('account')}
            onUploaded={onUploaded}
          />
        )}
        {currentKey === 'pick_table' && draft && (
          <StepPickTable
            candidates={draft.candidate_tables || []}
            strategy={draft.extraction_strategy}
            onBack={() => goBack('upload')}
            onConfirm={onPickTable}
            busy={pickBusy}
          />
        )}
        {currentKey === 'map' && draft && (
          <StepMapColumns
            draft={draft}
            onBack={() => goBack(hasMultiple ? 'pick_table' : 'upload')}
            onMapped={d => {
              setDraft(d)
              const idx = steps.findIndex(s => s.key === 'review')
              setStep(idx + 1)
            }}
          />
        )}
        {currentKey === 'review' && draft && (
          <StepReview
            draft={draft}
            account={account}
            onBack={() => goBack('map')}
            onCommitted={c => {
              setCommitData(c)
              const idx = steps.findIndex(s => s.key === 'done')
              setStep(idx + 1)
            }}
          />
        )}
        {currentKey === 'done' && commitData && (
          <StepDone commit={commitData} onClose={cancelAndClose}/>
        )}
      </div>
    </div>
  )
}
