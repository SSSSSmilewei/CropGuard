// 问答状态（全站共享）：网页检测台、问答页、手机端用同一份对话和"当前虫情"上下文。
import { reactive, ref } from 'vue'
import { api, type AskResult, type Detection, type KbSearch, type Risk } from '../lib/api'

export interface ChatMsg {
  id: number
  role: 'me' | 'ai'
  text: string
  pending?: boolean
  source?: AskResult['source']
  citations?: AskResult['citations']
  elapsed?: number
  guard?: AskResult['guard']
  gate?: { score: number; threshold: number } | null
}

export interface ChatContext {
  detections: Detection[]
  risk: Risk
  label: string
}

const messages = ref<ChatMsg[]>([])
const context = ref<ChatContext | null>(null)
const retrieval = ref<KbSearch | null>(null)
const busy = ref(false)
let seq = 0

export function setChatContext(detections: Detection[], risk: Risk) {
  if (!detections.length) return
  const names = [...new Set(detections.map((d) => d.chinese_name || d.class_name))]
  context.value = { detections, risk, label: `${names.slice(0, 3).join('、')} · ${risk.level}` }
}

export function useChat() {
  async function send(q: string) {
    const question = q.trim()
    if (!question || busy.value) return
    busy.value = true
    const history = messages.value
      .filter((m) => !m.pending)
      .slice(-8)
      .map((m) => ({ role: m.role === 'me' ? 'user' : 'assistant', content: m.text }))
    messages.value.push({ id: ++seq, role: 'me', text: question })
    const pending = reactive<ChatMsg>({ id: ++seq, role: 'ai', text: '正在检索知识库…', pending: true })
    messages.value.push(pending)

    // 检索透视与问答并行：检索只要几十毫秒，先出来给评委看"为什么答/为什么拒"
    const kb = api.kbSearch(question).then((r) => { retrieval.value = r; return r }).catch(() => null)
    try {
      const ctx = context.value ? { detections: context.value.detections, risk: context.value.risk } : null
      const r = await api.ask(question, history, ctx)
      const k = await kb
      Object.assign(pending, {
        pending: false,
        text: r.answer || '（没有返回内容）',
        source: r.source,
        citations: r.citations || [],
        elapsed: r.elapsed,
        guard: r.guard,
        gate: k ? { score: k.gate_score, threshold: k.refuse_below } : null,
      })
    } catch (e) {
      Object.assign(pending, { pending: false, text: `问答失败：${(e as Error).message}`, source: 'error' })
    } finally {
      busy.value = false
    }
  }
  function clear() {
    messages.value = []
    retrieval.value = null
  }
  return { messages, context, retrieval, busy, send, clear }
}
