// ─────────────────────────────────────────────────────────────────────────────
// useBreakpoint — single source of truth for "are we on mobile?".
//
// Returns { width, isMobile, isTablet, isDesktop } and re-renders on resize.
// Breakpoints match the rest of the app (768 / 1024).
//
// Use in any component that needs JS-driven layout changes — e.g. swap
// `gridTemplateColumns: '180px 1fr 220px'` for `'1fr'` when isMobile.
// ─────────────────────────────────────────────────────────────────────────────

import { useEffect, useState } from 'react'

const MOBILE  = 768
const TABLET  = 1024

function read() {
  if (typeof window === 'undefined') {
    return { width: 1280, isMobile: false, isTablet: false, isDesktop: true }
  }
  const w = window.innerWidth
  return {
    width:     w,
    isMobile:  w <= MOBILE,
    isTablet:  w >  MOBILE && w <= TABLET,
    isDesktop: w >  TABLET,
  }
}

export default function useBreakpoint() {
  const [bp, setBp] = useState(read)

  useEffect(() => {
    let raf = null
    function onResize() {
      // Coalesce — orientation change fires several events in quick succession
      if (raf) cancelAnimationFrame(raf)
      raf = requestAnimationFrame(() => setBp(read()))
    }
    window.addEventListener('resize',            onResize)
    window.addEventListener('orientationchange', onResize)
    return () => {
      window.removeEventListener('resize',            onResize)
      window.removeEventListener('orientationchange', onResize)
      if (raf) cancelAnimationFrame(raf)
    }
  }, [])

  return bp
}
