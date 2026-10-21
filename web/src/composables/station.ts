// 全站共享的"站点状态"：模型/语音/喷淋/历史。多个页面同时用时只轮询一份。
import { computed, onScopeDispose, reactive, ref } from 'vue'
import { api, type ClientConfig, type FeedbackStatus, type Health, type HistoryItem, type SprayStatus } from '../lib/api'

const state = reactive({
  online: null as boolean | null,
  health: null as Health | null,
  config: null as ClientConfig | null,
  feedback: null as FeedbackStatus['feedback'] | null,
  spray: null as SprayStatus | null,
  history: [] as HistoryItem[],
})

let statusTimer: number | undefined
let historyTimer: number | undefined
let statusUsers = 0
let historyUsers = 0

async function refreshStatus() {
  const [h, f, s] = await Promise.allSettled([api.health(), api.feedback(), api.sprayStatus()])
  state.online = h.status === 'fulfilled'
  if (h.status === 'fulfilled') state.health = h.value
  if (f.status === 'fulfilled') state.feedback = f.value.feedback
  if (s.status === 'fulfilled') state.spray = s.value
  if (!state.config && state.online) {
    try { state.config = await api.clientConfig() } catch { /* 老版本后端没有这个接口 */ }
  }
}

async function refreshHistory() {
  try {
    state.history = (await api.history()).history || []
  } catch { /* 下次轮询再试 */ }
}

/** 在组件 setup 里调用：引用计数管理轮询，最后一个页面卸载时停止 */
export function useStation(opts: { history?: boolean } = {}) {
  statusUsers += 1
  if (statusUsers === 1) {
    refreshStatus()
    statusTimer = window.setInterval(refreshStatus, 8000)
  }
  if (opts.history) {
    historyUsers += 1
    if (historyUsers === 1) {
      refreshHistory()
      historyTimer = window.setInterval(refreshHistory, 3000)
    }
  }
  onScopeDispose(() => {
    statusUsers -= 1
    if (statusUsers === 0) window.clearInterval(statusTimer)
    if (opts.history) {
      historyUsers -= 1
      if (historyUsers === 0) window.clearInterval(historyTimer)
    }
  })

  const zoneOf = computed<Record<string, string>>(() => {
    const m: Record<string, string> = {}
    for (const n of state.spray?.nodes || []) if (n.group && n.name) m[n.group] = n.name
    for (const z of state.spray?.zones || []) if (z.group && z.name) m[z.group] = z.name
    return m
  })
  const maxSpray = computed(() => state.spray?.max_duration || state.config?.max_spray || 5)
  const nodesOnline = computed(() => (state.spray?.nodes || []).filter((n) => n.online).length)

  return { state, zoneOf, maxSpray, nodesOnline, refreshStatus, refreshHistory }
}

/* ---------------- 提示条 ---------------- */
export interface Toast { id: number; text: string; tone: 'ok' | 'bad' }
const toasts = ref<Toast[]>([])
let toastSeq = 0
export function toast(text: string, tone: 'ok' | 'bad' = 'ok') {
  const id = ++toastSeq
  toasts.value = [...toasts.value.slice(-2), { id, text, tone }]
  window.setTimeout(() => { toasts.value = toasts.value.filter((t) => t.id !== id) }, tone === 'bad' ? 4200 : 2600)
}
export const useToasts = () => toasts

/* ---------------- 主题 ---------------- */
export type ThemeMode = 'system' | 'light' | 'dark'
const theme = ref<ThemeMode>('system')
try {
  const saved = localStorage.getItem('cg-theme') as ThemeMode | null
  if (saved === 'light' || saved === 'dark') theme.value = saved
} catch { /* 无痕模式等拿不到存储，跟随系统 */ }
function applyTheme() {
  const root = document.documentElement
  if (theme.value === 'system') root.removeAttribute('data-theme')
  else root.setAttribute('data-theme', theme.value)
}
applyTheme()
export function useTheme() {
  const cycle = () => {
    theme.value = theme.value === 'system' ? 'light' : theme.value === 'light' ? 'dark' : 'system'
    applyTheme()
    try { localStorage.setItem('cg-theme', theme.value) } catch { /* 忽略 */ }
  }
  const label = computed(() => ({ system: '跟随系统', light: '浅色', dark: '深色' })[theme.value])
  return { theme, cycle, label }
}
