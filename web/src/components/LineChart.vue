<script setup lang="ts">
// 多系列折线图（SVG）：单一 y 轴、2px 线、发丝网格、线尾直接标签（带引线防重叠）、
// 悬停十字线 + 数值提示。颜色按系列顺序取 --s1..--s4（已过色盲校验），文字一律用正文色。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'

export interface Series { key: string; label: string; values: number[] }

const props = withDefaults(defineProps<{
  x: number[]
  series: Series[]
  yMin?: number | null
  yMax?: number | null
  height?: number
  digits?: number
  xLabel?: string
}>(), { yMin: null, yMax: null, height: 280, digits: 3, xLabel: 'epoch' })

const root = ref<HTMLElement | null>(null)
const width = ref(640)
let ro: ResizeObserver | null = null
onMounted(() => {
  ro = new ResizeObserver((e) => { width.value = Math.max(280, Math.round(e[0].contentRect.width)) })
  if (root.value) ro.observe(root.value)
})
onBeforeUnmount(() => ro?.disconnect())

const M = { l: 44, r: 136, t: 12, b: 30 }
const color = (i: number) => `var(--s${(i % 4) + 1})`

const dom = computed(() => {
  const all = props.series.flatMap((s) => s.values).filter((v) => Number.isFinite(v))
  let lo = props.yMin ?? Math.min(...all)
  let hi = props.yMax ?? Math.max(...all)
  if (props.yMin == null || props.yMax == null) {
    const pad = (hi - lo) * 0.06 || 0.1
    if (props.yMin == null) lo = Math.max(0, lo - pad)
    if (props.yMax == null) hi = hi + pad
  }
  return { lo, hi, x0: props.x[0] ?? 0, x1: props.x[props.x.length - 1] ?? 1 }
})
const W = computed(() => width.value - M.l - M.r)
const H = computed(() => props.height - M.t - M.b)
const sx = (v: number) => M.l + ((v - dom.value.x0) / (dom.value.x1 - dom.value.x0 || 1)) * W.value
const sy = (v: number) => M.t + (1 - (v - dom.value.lo) / (dom.value.hi - dom.value.lo || 1)) * H.value

function niceTicks(lo: number, hi: number, n = 5) {
  const span = hi - lo || 1
  const raw = span / n
  const mag = 10 ** Math.floor(Math.log10(raw))
  const step = [1, 2, 2.5, 5, 10].map((k) => k * mag).find((s) => span / s <= n) || raw
  const out: number[] = []
  for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) out.push(+v.toFixed(6))
  return out
}
const yTicks = computed(() => niceTicks(dom.value.lo, dom.value.hi))
const xTicks = computed(() => {
  const xs = props.x
  if (!xs.length) return []
  const step = Math.max(1, Math.round(xs.length / Math.max(2, Math.floor(W.value / 80))))
  const idx = xs.map((_, i) => i).filter((i) => i % step === 0)
  const last = xs.length - 1
  if (idx[idx.length - 1] !== last) {
    // 最后一个常规刻度离末端太近时让位给末端，避免两个数字挤在一起
    if (last - idx[idx.length - 1] < step * 0.6) idx.pop()
    idx.push(last)
  }
  return idx.map((i) => xs[i])
})

const paths = computed(() =>
  props.series.map((s, i) => ({
    key: s.key,
    color: color(i),
    d: s.values.map((v, j) => `${j ? 'L' : 'M'}${sx(props.x[j]).toFixed(1)},${sy(v).toFixed(1)}`).join(''),
  })),
)

// 线尾标签：按末值排序后保证最小间距，用引线连回线尾
const endLabels = computed(() => {
  const items = props.series.map((s, i) => {
    const v = s.values[s.values.length - 1]
    return { i, label: s.label, v, y0: sy(v), y: sy(v) }
  }).sort((a, b) => a.y0 - b.y0)
  const gap = 17
  for (let k = 1; k < items.length; k++) if (items[k].y - items[k - 1].y < gap) items[k].y = items[k - 1].y + gap
  const over = items.length ? items[items.length - 1].y - (M.t + H.value) : 0
  if (over > 0) items.forEach((it) => { it.y -= over })
  return items
})

/* ---------------- 悬停 ---------------- */
const hover = ref<number | null>(null)
function onMove(e: PointerEvent) {
  const box = (e.currentTarget as SVGRectElement).getBoundingClientRect()
  const px = e.clientX - box.left
  const xs = props.x
  let best = 0
  for (let j = 1; j < xs.length; j++) if (Math.abs(sx(xs[j]) - M.l - px) < Math.abs(sx(xs[best]) - M.l - px)) best = j
  hover.value = best
}
const tip = computed(() => {
  const j = hover.value
  if (j == null) return null
  const x = sx(props.x[j])
  return {
    x, left: x + 12 > width.value - 170 ? x - 172 : x + 12,
    epoch: props.x[j],
    rows: props.series.map((s, i) => ({ label: s.label, v: s.values[j], color: color(i), y: sy(s.values[j]) })),
  }
})
</script>

<template>
  <div ref="root" class="chart">
    <div class="legend">
      <span v-for="(s, i) in series" :key="s.key" class="lg"><i :style="{ background: color(i) }" />{{ s.label }}</span>
    </div>
    <svg :width="width" :height="height" :viewBox="`0 0 ${width} ${height}`" role="img" :aria-label="`${series.map((s) => s.label).join('、')} 随 ${xLabel} 变化`">
      <g class="grid">
        <line v-for="t in yTicks" :key="t" :x1="M.l" :x2="M.l + W" :y1="sy(t)" :y2="sy(t)" />
      </g>
      <g class="axis">
        <text v-for="t in yTicks" :key="`y${t}`" :x="M.l - 8" :y="sy(t) + 4" text-anchor="end">{{ t.toFixed(t < 10 ? 2 : 0) }}</text>
        <text v-for="t in xTicks" :key="`x${t}`" :x="sx(t)" :y="M.t + H + 18" text-anchor="middle">{{ t }}</text>
        <text :x="M.l + W + 10" :y="M.t + H + 18" text-anchor="start" class="xl">{{ xLabel }}</text>
      </g>
      <path v-for="p in paths" :key="p.key" :d="p.d" :stroke="p.color" class="line" />
      <g v-for="e in endLabels" :key="`e${e.i}`" class="end">
        <circle :cx="sx(x[x.length - 1])" :cy="e.y0" r="3.5" :fill="color(e.i)" class="ring" />
        <path :d="`M${sx(x[x.length - 1]) + 5},${e.y0} L${sx(x[x.length - 1]) + 14},${e.y}`" class="leader" />
        <text :x="sx(x[x.length - 1]) + 18" :y="e.y + 4">{{ e.label }} <tspan class="ev">{{ e.v.toFixed(digits) }}</tspan></text>
      </g>
      <g v-if="tip">
        <line :x1="tip.x" :x2="tip.x" :y1="M.t" :y2="M.t + H" class="cross" />
        <circle v-for="r in tip.rows" :key="r.label" :cx="tip.x" :cy="r.y" r="4" :fill="r.color" class="ring" />
      </g>
      <rect :x="M.l" :y="M.t" :width="W" :height="H" fill="transparent" @pointermove="onMove" @pointerleave="hover = null" />
    </svg>
    <div v-if="tip" class="tip" :style="{ left: `${tip.left}px`, top: `${M.t + 22}px` }">
      <div class="th mono">{{ xLabel }} {{ tip.epoch }}</div>
      <div v-for="r in tip.rows" :key="r.label" class="tr"><i :style="{ background: r.color }" /><span>{{ r.label }}</span><b class="mono">{{ r.v.toFixed(digits) }}</b></div>
    </div>
  </div>
</template>

<style scoped>
.chart { position: relative; width: 100%; min-width: 0; }
.legend { display: flex; flex-wrap: wrap; gap: 6px 16px; margin-bottom: 8px; font-size: 12px; color: var(--ink-2); }
.lg { display: inline-flex; align-items: center; gap: 6px; }
.lg i { width: 14px; height: 2px; border-radius: 1px; display: inline-block; }
svg { display: block; overflow: visible; }
.grid line { stroke: var(--inset); stroke-width: 1; }
.axis text { fill: var(--ink-3); font: 11px var(--font-mono); }
.line { fill: none; stroke-width: 2; stroke-linejoin: round; stroke-linecap: round; }
.ring { stroke: var(--panel); stroke-width: 2; }
.leader { stroke: var(--line-strong); stroke-width: 1; fill: none; }
.end text { fill: var(--ink); font: 12px var(--font-cn); }
.end .ev { fill: var(--ink-2); font-family: var(--font-mono); }
.cross { stroke: var(--ink-3); stroke-width: 1; }
.tip {
  position: absolute; pointer-events: none; min-width: 160px; padding: 8px 10px; border-radius: var(--r);
  background: var(--paper); border: 1px solid var(--line-strong); box-shadow: 0 6px 18px rgba(0, 0, 0, 0.12); font-size: 12px;
}
.th { color: var(--ink-3); margin-bottom: 4px; }
.tr { display: grid; grid-template-columns: 10px 1fr auto; align-items: center; gap: 8px; }
.tr i { width: 10px; height: 2px; }
.tr b { font-weight: 500; }
</style>
