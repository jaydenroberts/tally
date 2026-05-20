// Pill — semantic status badge.
// Use tones to convey meaning, not just colour.

const tones = {
  neutral:  { bg: 'var(--bg-hover)',                                                color: 'var(--text-muted)', ring: 'var(--border)' },
  positive: { bg: 'color-mix(in oklab, var(--positive) 15%, transparent)',          color: 'var(--positive)',   ring: 'color-mix(in oklab, var(--positive) 35%, transparent)' },
  negative: { bg: 'color-mix(in oklab, var(--negative) 15%, transparent)',          color: 'var(--negative)',   ring: 'color-mix(in oklab, var(--negative) 35%, transparent)' },
  warning:  { bg: 'color-mix(in oklab, var(--warning) 15%, transparent)',           color: 'var(--warning)',    ring: 'color-mix(in oklab, var(--warning) 35%, transparent)' },
  info:     { bg: 'color-mix(in oklab, var(--info) 15%, transparent)',              color: 'var(--info)',       ring: 'color-mix(in oklab, var(--info) 35%, transparent)' },
  brand:    { bg: 'color-mix(in oklab, var(--brand) 15%, transparent)',             color: 'var(--brand)',      ring: 'color-mix(in oklab, var(--brand) 35%, transparent)' },
}

export default function Pill({ children, tone = 'neutral' }) {
  const t = tones[tone] || tones.neutral
  return (
    <span style={{
      display: 'inline-flex',
      alignItems: 'center',
      gap: 5,
      padding: '2px 9px',
      borderRadius: 999,
      background: t.bg,
      color: t.color,
      fontSize: 11,
      fontWeight: 600,
      border: `1px solid ${t.ring}`,
      lineHeight: 1.4,
      whiteSpace: 'nowrap',
    }}>
      {children}
    </span>
  )
}
