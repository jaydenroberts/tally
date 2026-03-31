const variants = {
  primary: {
    background: 'var(--green)',
    color: '#282A36',
    border: 'none',
    fontWeight: 700,
  },
  secondary: {
    background: 'none',
    color: 'var(--white)',
    border: '1px solid var(--border)',
    fontWeight: 500,
  },
  danger: {
    background: 'none',
    color: 'var(--red)',
    border: '1px solid var(--red)',
    fontWeight: 500,
  },
  ghost: {
    background: 'none',
    color: 'var(--muted)',
    border: 'none',
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
    fontSize: size === 'sm' ? 13 : 14,
    padding: size === 'sm' ? '5px 12px' : '9px 16px',
    transition: 'opacity 0.15s',
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
