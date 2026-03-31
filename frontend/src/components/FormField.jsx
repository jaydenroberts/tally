/**
 * Reusable labelled form field.
 * Usage:
 *   <FormField label="Name" error={errors.name}>
 *     <input ... />
 *   </FormField>
 */
export default function FormField({ label, error, children, hint }) {
  return (
    <div style={styles.wrap}>
      {label && <label style={styles.label}>{label}</label>}
      {children}
      {hint && !error && <p style={styles.hint}>{hint}</p>}
      {error && <p style={styles.error}>{error}</p>}
    </div>
  )
}

export const inputStyle = {
  display: 'block',
  width: '100%',
  background: 'var(--bg-input)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius)',
  color: 'var(--white)',
  padding: '9px 12px',
  fontSize: 14,
  outline: 'none',
  boxSizing: 'border-box',
}

export const selectStyle = {
  ...inputStyle,
  appearance: 'none',
}

const styles = {
  wrap: {
    display: 'flex',
    flexDirection: 'column',
    gap: 6,
    marginBottom: 16,
  },
  label: {
    fontSize: 13,
    fontWeight: 500,
    color: 'var(--muted)',
  },
  hint: {
    fontSize: 12,
    color: 'var(--muted)',
    marginTop: 2,
  },
  error: {
    fontSize: 12,
    color: 'var(--red)',
    marginTop: 2,
  },
}
