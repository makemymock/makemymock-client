import { useSyncExternalStore } from 'react'

const STORAGE_KEY = 'vibeprep-theme'

const getSystemTheme = () => {
  if (typeof window === 'undefined') return 'dark'
  return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

const getInitialTheme = () => {
  if (typeof window === 'undefined') return 'dark'
  const stored = window.localStorage.getItem(STORAGE_KEY)
  if (stored === 'light' || stored === 'dark') return stored
  return getSystemTheme()
}

// Single shared theme state for the whole app. Without this, every
// component that calls useTheme() got its own useState — toggling in
// one (e.g. the topbar) wouldn't update the others (sidebar, FAQ image,
// hero logo), and the only way to resync them was a hard refresh.
let currentTheme = getInitialTheme()
const subscribers = new Set()

if (typeof document !== 'undefined') {
  document.documentElement.setAttribute('data-theme', currentTheme)
}

function setThemeValue(next) {
  if (next !== 'light' && next !== 'dark') return
  if (next === currentTheme) return
  currentTheme = next
  if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', next)
  }
  if (typeof window !== 'undefined') {
    try { window.localStorage.setItem(STORAGE_KEY, next) } catch { /* ignore */ }
  }
  subscribers.forEach((cb) => cb())
}

function subscribe(callback) {
  subscribers.add(callback)
  return () => subscribers.delete(callback)
}

function getSnapshot() {
  return currentTheme
}

function getServerSnapshot() {
  return 'dark'
}

export default function useTheme() {
  const theme = useSyncExternalStore(subscribe, getSnapshot, getServerSnapshot)

  return {
    theme,
    setTheme: setThemeValue,
    toggleTheme: () => setThemeValue(currentTheme === 'dark' ? 'light' : 'dark'),
  }
}
