import type { Detection, HistoryItem } from './api'

export type RiskKey = 'high' | 'mid' | 'low' | 'none'

export const RISK_ORDER: { key: RiskKey; label: string; short: string }[] = [
  { key: 'none', label: '无风险', short: '无' },
  { key: 'low', label: '低风险', short: '低' },
  { key: 'mid', label: '中风险', short: '中' },
  { key: 'high', label: '高风险', short: '高' },
]

export function riskKey(level?: string | null): RiskKey {
  return ({ 高风险: 'high', 中风险: 'mid', 低风险: 'low' } as Record<string, RiskKey>)[level || ''] || 'none'
}

/** 数据集类名 → 学名写法：Lycorma_delicatula → Lycorma delicatula */
export function latinName(cls: string) {
  return (cls || '').replace(/_/g, ' ').trim()
}

export const pct = (v: number, digits = 0) => (v * 100).toFixed(digits)

export function sortByConf(list: Detection[]) {
  return list.slice().sort((a, b) => b.confidence - a.confidence)
}

/** 所有检测框占画面的比例（与后端 assess_risk 同口径：框面积直接相加） */
export function areaRatio(list: Detection[], w: number, h: number) {
  if (!w || !h) return 0
  const s = list.reduce((acc, d) => acc + (d.bbox[2] - d.bbox[0]) * (d.bbox[3] - d.bbox[1]), 0)
  return s / (w * h)
}

export function groupLabel(g: string | null | undefined, zoneOf: Record<string, string> = {}) {
  if (!g || g === 'all') return '全体片区'
  return zoneOf[g] || g
}

export const VIA_LABEL: Record<string, string> = {
  web: '网页', phone: '手机', chat: '指令', manual: '手动', auto: '自动', 'phone-chat': '手机指令',
}

export function describeHistory(h: HistoryItem, zoneOf: Record<string, string> = {}) {
  const auto = h.source === 'auto'
  const tag = auto ? h.risk : VIA_LABEL[h.via] || '手动'
  let what: string
  if (h.duration === 0) what = `停止 ${groupLabel(h.group, zoneOf)}`
  else if (h.group) what = `${groupLabel(h.group, zoneOf)} 喷淋 ${h.duration} s`
  else what = h.risk || ''
  if (h.detections?.length) what += ` · ${h.detections.slice(0, 3).join('、')}`
  return { tag, what, risk: auto ? riskKey(h.risk) : null }
}

export function clock(sec: number) {
  const s = Math.max(0, Math.floor(sec))
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export function timeOf(iso?: string) {
  if (!iso) return ''
  const d = new Date(iso)
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleTimeString('zh-CN', { hour12: false })
}

/* ---------------- 防治建议文本 → 结构化 ----------------
 * 知识库输出形如：
 *   【为害特征与防治建议】
 *   ◆ 蚜虫（为害 棉花、小麦…）
 *     为害：……
 *     防治：……
 *   【通用预防措施】
 *   1. ……
 * 大模型输出不保证格式，解析不出结构时按段落原样显示。
 */
export interface AdviceBlock {
  kind: 'heading' | 'subhead' | 'field' | 'list' | 'para'
  label?: string
  text?: string
  items?: string[]
}

export function parseAdvice(raw: string, opts: { skipDiagnosis?: boolean } = {}): AdviceBlock[] {
  const out: AdviceBlock[] = []
  let skipping = false
  let list: string[] | null = null
  const flush = () => {
    if (list?.length) out.push({ kind: 'list', items: list })
    list = null
  }
  for (const line0 of (raw || '').split(/\r?\n/)) {
    const line = line0.trim()
    if (!line) { flush(); continue }
    const head = line.match(/^【(.+?)】\s*(.*)$/)
    if (head) {
      flush()
      skipping = !!opts.skipDiagnosis && head[1].includes('诊断')
      if (!skipping) {
        out.push({ kind: 'heading', text: head[1] })
        if (head[2]) out.push({ kind: 'para', text: head[2] })
      }
      continue
    }
    if (skipping) continue
    const bullet = line.match(/^(?:\d+[.、)]|[-•·*])\s*(.+)$/)
    if (bullet) {
      ;(list ||= []).push(bullet[1].replace(/[；;。]$/, ''))
      continue
    }
    flush()
    if (line.startsWith('◆')) {
      out.push({ kind: 'subhead', text: line.replace(/^◆\s*/, '') })
      continue
    }
    const field = line.match(/^([一-龥]{2,6})[：:]\s*(.+)$/)
    if (field) {
      out.push({ kind: 'field', label: field[1], text: field[2] })
      continue
    }
    out.push({ kind: 'para', text: line })
  }
  flush()
  return out
}

/** "黑光灯诱杀成虫；幼虫期药剂灌根；结合秋耕拾虫。" → 三条 */
export function splitMeasures(text: string) {
  const parts = text.split(/[；;]/).map((s) => s.replace(/[。.]$/, '').trim()).filter(Boolean)
  return parts.length > 1 ? parts : null
}
