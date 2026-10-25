import { reactive, computed } from 'vue'

export type ThemeMode = 'light' | 'dark' | 'auto'
export const THEME_ORDER: ThemeMode[] = ['light', 'dark', 'auto']
export const THEME_LABEL: Record<ThemeMode, string> = { light: '浅色', dark: '深色', auto: '跟随系统' }
export const THEME_KEY = 'vs-theme'

const mq = window.matchMedia('(prefers-color-scheme: light)')
const state = reactive<{ mode: ThemeMode; mem: ThemeMode | null }>({ mode: 'auto', mem: null })

function lsGet(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}
function lsSet(key: string, value: string) {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* 隐私模式下忽略 */
  }
}

export function effectiveTheme(mode: ThemeMode = state.mode): 'light' | 'dark' {
  return mode === 'auto' ? (mq.matches ? 'light' : 'dark') : mode
}

export function applyTheme() {
  const theme = effectiveTheme()
  document.documentElement.dataset.theme = theme
}

export function setThemeMode(mode: ThemeMode) {
  state.mem = mode // 先应用，再持久化：存储被禁也不影响切换
  state.mode = mode
  applyTheme()
  lsSet(THEME_KEY, mode)
}

/** 循环切换：跳过"看起来和当前一样"的档位 */
export function nextThemeMode(): ThemeMode {
  const cur = state.mode
  const curEffective = effectiveTheme()
  for (let i = 1; i <= 3; i++) {
    const cand = THEME_ORDER[(THEME_ORDER.indexOf(cur) + i) % 3]
    if (effectiveTheme(cand) !== curEffective || cand === cur) {
      if (effectiveTheme(cand) !== curEffective) return cand
    }
  }
  return THEME_ORDER[(THEME_ORDER.indexOf(cur) + 1) % 3]
}

export function initTheme() {
  const stored = (state.mem || lsGet(THEME_KEY)) as ThemeMode | null
  state.mode = stored && THEME_ORDER.includes(stored) ? stored : 'auto'
  applyTheme()
  mq.addEventListener('change', () => {
    if (state.mode === 'auto') applyTheme()
  })
}

export const themeMode = computed(() => state.mode)
export const themeNow = computed(() => effectiveTheme())
export const themeIcon = computed(() => (state.mode === 'auto' ? 'auto' : effectiveTheme()))
