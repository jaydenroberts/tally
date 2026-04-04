/**
 * CurrencyContext
 *
 * Reads the user's preferred currency from localStorage (tally_settings.currency,
 * defaulting to 'USD'). Exposes:
 *
 *   currency      — the ISO 4217 code string (e.g. 'USD', 'AUD')
 *   formatCurrency(n, overrideCurrency?) — Intl.NumberFormat formatter
 *
 * The provider listens for the custom 'tally:settings-changed' event so that
 * when the General tab saves new preferences the rest of the app updates
 * immediately without a page reload.
 */
import React, { createContext, useContext, useState, useEffect, useCallback } from 'react'

const LS_KEY = 'tally_settings'

function readCurrencyFromStorage() {
  try {
    const s = JSON.parse(localStorage.getItem(LS_KEY))
    return s?.currency || 'USD'
  } catch {
    return 'USD'
  }
}

const CurrencyContext = createContext(null)

export function CurrencyProvider({ children }) {
  const [currency, setCurrency] = useState(readCurrencyFromStorage)

  // Re-read from localStorage when the General tab fires the settings event
  useEffect(() => {
    function handleSettingsChange() {
      setCurrency(readCurrencyFromStorage())
    }
    window.addEventListener('tally:settings-changed', handleSettingsChange)
    return () => window.removeEventListener('tally:settings-changed', handleSettingsChange)
  }, [])

  /**
   * Format a number as currency.
   * @param {number} n
   * @param {string} [overrideCurrency] - use a specific currency code instead of the
   *   user's preference (e.g. for per-account display in Accounts page)
   */
  const formatCurrency = useCallback((n, overrideCurrency) => {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: overrideCurrency ?? currency,
      minimumFractionDigits: 2,
    }).format(n)
  }, [currency])

  return (
    <CurrencyContext.Provider value={{ currency, formatCurrency }}>
      {children}
    </CurrencyContext.Provider>
  )
}

export function useCurrency() {
  const ctx = useContext(CurrencyContext)
  if (!ctx) throw new Error('useCurrency must be used within CurrencyProvider')
  return ctx
}
