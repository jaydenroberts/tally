// Button — token-driven, four semantic variants.
// `brand` and `primary` are aliases for now (purple action button).
// Existing call sites using variant="primary" don't need to change.

const variants = {
  brand: {
    background: 'var(--brand)',
    color: 'var(--brand-ink)',
    border: '1px solid var(--brand)',
    fontWeight: 600,
  },
  primary: {
    background: 'var(--brand)',
    color: 'var(--brand-ink)',
    border: '1px solid var(--brand)',
    fontWeight: 600,
  },
  secondary: {
    background: 'var(--bg-elevated)',
    color: 'var(--text)',
    border: '1px solid var(--border)',
    fontWeight: 500,
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-muted)',
    border: '1px solid transparent',
    fontWeight: 500,
  },
  danger: {
    background: 'transparent',
    color: 'var(--negative)',
    border: '1px solid color-mix(in oklab, var(--negative) 40%, transparent)',
    fontWeight: 500,
  },
}

export default function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled,
  onClick,
  type = 'button',
  style: extraStyle,
}) {
  const base = {
    display: 'inline-flex',
    alignItems: 'center',
    gap: 6,
    borderRadius: 'var(--radius)',
    cursor: disabled ? 'not-allowed' : 'pointer',
    opacity: disabled ? 0.5 : 1,
    fontFamily: 'inherit',
    fontSize: size === 'sm' ? 12 : 13,
    padding: size === 'sm' ? '5px 10px' : '8px 14px',
    transition: 'opacity 0.12s, background 0.12s',
    whiteSpace: 'nowrap',
  }

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      style={{ ...base, ...variants[variant], ...extraStyle }}
    >
      {children}
    </button>
  )
}
