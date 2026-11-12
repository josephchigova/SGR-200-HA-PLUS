import { useSyncExternalStore } from 'react'

const KEY = 'sgr_theme'
const listeners = new Set()

function readTheme() {
  try {
    const saved = localStorage.getItem(KEY)
    if (saved === 'light' || saved === 'dark') return saved
  } catch { /* ignore */ }
  const prefersDark = typeof window.matchMedia === 'function' && window.matchMedia('(prefers-color-scheme: dark)').matches
  return prefersDark ? 'dark' : 'light'
}

let current = readTheme()

export function applyTheme(theme) {
  document.documentElement.setAttribute('data-theme', theme)
  const meta = document.querySelector('meta[name="theme-color"]')
  if (meta) meta.setAttribute('content', theme === 'dark' ? '#0e1411' : '#f3f6f2')
}

function setTheme(next) {
  if (next !== 'light' && next !== 'dark') return
  current = next
  try { localStorage.setItem(KEY, next) } catch { /* ignore */ }
  applyTheme(next)
  listeners.forEach((listener) => listener())
}

function subscribe(listener) {
  listeners.add(listener)
  // Keeps every open tab on the same theme.
  const sync = (event) => {
    if (event.key === KEY && (event.newValue === 'light' || event.newValue === 'dark') && event.newValue !== current) {
      current = event.newValue
      applyTheme(current)
      listeners.forEach((item) => item())
    }
  }
  window.addEventListener('storage', sync)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('storage', sync)
  }
}

applyTheme(current)

// One theme for the whole app. Every component that calls this sees the same value.
export function useTheme() {
  const theme = useSyncExternalStore(subscribe, () => current)
  return { theme, setTheme, toggleTheme: () => setTheme(current === 'dark' ? 'light' : 'dark') }
}
