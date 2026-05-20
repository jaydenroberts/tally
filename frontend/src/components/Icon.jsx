// Icon set — stroke-only SVG icons used across the redesign.
// Keep monochrome (currentColor) so callers control color via CSS.

const PATHS = {
  dashboard: <><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></>,
  wallet:    <><path d="M3 7a2 2 0 0 1 2-2h13a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7Z"/><path d="M16 12h3"/><path d="M3 9h15"/></>,
  list:      <><path d="M8 6h13"/><path d="M8 12h13"/><path d="M8 18h13"/><circle cx="4" cy="6" r="1"/><circle cx="4" cy="12" r="1"/><circle cx="4" cy="18" r="1"/></>,
  repeat:    <><path d="M17 2l4 4-4 4"/><path d="M3 12V9a4 4 0 0 1 4-4h14"/><path d="M7 22l-4-4 4-4"/><path d="M21 12v3a4 4 0 0 1-4 4H3"/></>,
  target:    <><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/></>,
  piggy:     <><path d="M4 11c0-4 4-6 8-6s8 2 8 6v4a3 3 0 0 1-3 3h-1v2h-3v-2H9v2H6v-2a3 3 0 0 1-2-3v-4Z"/><circle cx="16" cy="12" r="0.8"/></>,
  coins:     <><ellipse cx="8" cy="8" rx="5" ry="2.5"/><path d="M3 8v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5V8"/><ellipse cx="16" cy="15" rx="5" ry="2.5"/><path d="M11 15v4c0 1.4 2.2 2.5 5 2.5s5-1.1 5-2.5v-4"/></>,
  chat:      <><path d="M21 12a8 8 0 0 1-11.5 7.2L3 21l1.8-6.5A8 8 0 1 1 21 12Z"/></>,
  settings:  <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z"/></>,
  upload:    <><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="M17 8l-5-5-5 5"/><path d="M12 3v12"/></>,
  plus:      <><path d="M12 5v14"/><path d="M5 12h14"/></>,
  search:    <><circle cx="11" cy="11" r="7"/><path d="M20 20l-3.5-3.5"/></>,
  arrowUp:   <><path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></>,
  arrowDown: <><path d="M12 5v14"/><path d="M19 12l-7 7-7-7"/></>,
  check:     <><path d="M4 12l5 5L20 6"/></>,
  warn:      <><path d="M12 3 2 21h20L12 3Z"/><path d="M12 10v5"/><circle cx="12" cy="18" r="0.8"/></>,
  filter:    <><path d="M3 5h18"/><path d="M6 12h12"/><path d="M10 19h4"/></>,
  sparkle:   <><path d="M12 3v4"/><path d="M12 17v4"/><path d="M3 12h4"/><path d="M17 12h4"/><path d="M6 6l2.5 2.5"/><path d="M15.5 15.5 18 18"/><path d="M6 18l2.5-2.5"/><path d="M15.5 8.5 18 6"/></>,
  menu:      <><path d="M4 6h16"/><path d="M4 12h16"/><path d="M4 18h16"/></>,
  logout:    <><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><path d="M16 17l5-5-5-5"/><path d="M21 12H9"/></>,
  external:  <><path d="M15 3h6v6"/><path d="M10 14 21 3"/><path d="M21 14v5a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5"/></>,
  chevronDown:  <><path d="M6 9l6 6 6-6"/></>,
  chevronRight: <><path d="M9 18l6-6-6-6"/></>,
  dot:       <circle cx="12" cy="12" r="3"/>,
}

export default function Icon({ name, size = 18, stroke = 1.6 }) {
  const path = PATHS[name] || PATHS.dot
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={stroke}
      strokeLinecap="round"
      strokeLinejoin="round"
      style={{ flexShrink: 0, display: 'block' }}
    >
      {path}
    </svg>
  )
}
