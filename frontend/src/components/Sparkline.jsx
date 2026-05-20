// Sparkline — tiny inline trend chart.
// Pass `points` as an array of numbers; the component normalises to its bounds.

export default function Sparkline({
  points,
  width = 120,
  height = 32,
  color = 'var(--brand)',
  fill = true,
}) {
  if (!points || points.length < 2) return null

  const min = Math.min(...points)
  const max = Math.max(...points)
  const range = max - min || 1
  const step = width / (points.length - 1)

  const coords = points.map((p, i) => [
    i * step,
    height - ((p - min) / range) * (height - 4) - 2,
  ])

  const path = coords
    .map((c, i) => `${i === 0 ? 'M' : 'L'}${c[0].toFixed(1)} ${c[1].toFixed(1)}`)
    .join(' ')

  const areaPath = `${path} L${width} ${height} L0 ${height} Z`

  // Unique gradient ID per render so multiple sparklines on a page don't collide.
  const gid = 'sparkline-grad-' + Math.random().toString(36).slice(2, 8)

  return (
    <svg
      width="100%"
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      style={{ display: 'block', maxWidth: '100%' }}
    >
      <defs>
        <linearGradient id={gid} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35"/>
          <stop offset="100%" stopColor={color} stopOpacity="0"/>
        </linearGradient>
      </defs>
      {fill && <path d={areaPath} fill={`url(#${gid})`}/>}
      <path
        d={path}
        fill="none"
        stroke={color}
        strokeWidth="1.8"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  )
}
