/**
 * Date formatting utilities for Tally.
 *
 * Dates are stored in the database as YYYY-MM-DD strings and returned by the
 * API in that form. These helpers convert them to DD-MM-YYYY for display.
 * Do NOT use these functions to format values that are sent back to the API —
 * always send/receive dates in YYYY-MM-DD format.
 */

/**
 * Format a YYYY-MM-DD date string (or Date object) as DD-MM-YYYY.
 * Returns '—' for null/undefined/empty inputs.
 *
 * @param {string|Date|null|undefined} d
 * @returns {string}
 */
export function formatDate(d) {
  if (!d) return '—'
  // If it's already a Date object, extract parts directly to avoid timezone issues.
  if (d instanceof Date) {
    const dd = String(d.getDate()).padStart(2, '0')
    const mm = String(d.getMonth() + 1).padStart(2, '0')
    const yyyy = d.getFullYear()
    return `${dd}-${mm}-${yyyy}`
  }
  // For YYYY-MM-DD strings: split directly — no Date constructor needed, avoids
  // UTC-vs-local offset bugs that can shift the day by ±1.
  const parts = String(d).slice(0, 10).split('-')
  if (parts.length !== 3) return String(d)
  const [yyyy, mm, dd] = parts
  return `${dd}-${mm}-${yyyy}`
}

/**
 * Format an ISO datetime string (e.g. from `imported_at`, `paid_at`,
 * `contributed_at`) as "DD-MM-YYYY HH:MM".
 * Returns '—' for null/undefined/empty inputs.
 *
 * @param {string|null|undefined} iso
 * @returns {string}
 */
export function formatDateTime(iso) {
  if (!iso) return '—'
  const dt = new Date(iso)
  if (isNaN(dt.getTime())) return String(iso)
  const dd   = String(dt.getDate()).padStart(2, '0')
  const mm   = String(dt.getMonth() + 1).padStart(2, '0')
  const yyyy = dt.getFullYear()
  const hh   = String(dt.getHours()).padStart(2, '0')
  const min  = String(dt.getMinutes()).padStart(2, '0')
  return `${dd}-${mm}-${yyyy} ${hh}:${min}`
}
