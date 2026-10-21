<script setup lang="ts">
// 标本签：一条检测结果按昆虫标本标签的格式呈现（编号 · 采集地 · 时间 / 学名 / 中文名 / 读数）。
import type { Detection } from '../lib/api'
import { latinName } from '../lib/format'

withDefaults(defineProps<{
  det: Detection
  no?: string
  origin?: string
  time?: string
  area?: number | null
  elapsed?: number | null
  compact?: boolean
}>(), { no: '', origin: '', time: '', area: null, elapsed: null, compact: false })

const corner = (b: number[], from: number) => b.slice(from, from + 2).map((v) => Math.round(v)).join(',')
</script>

<template>
  <article class="label" :class="{ compact }">
    <div class="meta mono">
      <span>{{ no ? `NO. ${no}` : '' }}{{ origin ? ` · ${origin}` : '' }}</span>
      <span>{{ time }}</span>
    </div>
    <div class="names">
      <div>
        <div class="latin">{{ latinName(det.class_name) }}</div>
        <div class="cn">{{ det.chinese_name || det.class_name }}</div>
      </div>
      <div v-if="compact" class="num big">{{ Math.round(det.confidence * 100) }}<small>%</small></div>
    </div>
    <div v-if="!compact" class="readings">
      <div>
        <div class="k">置信度</div>
        <div class="num big">{{ Math.round(det.confidence * 100) }}<small>%</small></div>
      </div>
      <div v-if="area != null">
        <div class="k">占画面</div>
        <div class="num big">{{ (area * 100).toFixed(1) }}<small>%</small></div>
      </div>
      <div>
        <div class="k">定位框</div>
        <div class="mono v">{{ corner(det.bbox, 0) }} → {{ corner(det.bbox, 2) }}</div>
      </div>
      <div v-if="elapsed != null">
        <div class="k">推理耗时</div>
        <div class="mono v">{{ elapsed.toFixed(2) }} s</div>
      </div>
    </div>
    <slot />
  </article>
</template>

<style scoped>
.label {
  background: var(--paper); border: 1px solid var(--ink); border-radius: 2px;
  padding: 16px 18px; box-shadow: 3px 3px 0 var(--line);
}
.meta { display: flex; justify-content: space-between; gap: 12px; font-size: 11px; letter-spacing: 0.06em; color: var(--ink-3); }
.names { display: flex; align-items: flex-end; justify-content: space-between; gap: 12px; margin-top: 8px; }
.latin { font-family: var(--font-mono); font-style: italic; font-size: 13px; color: var(--ink-2); }
.cn { font-family: var(--font-serif); font-size: 22px; font-weight: 700; line-height: 1.35; }
.readings {
  display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px 16px;
  margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line-strong);
}
.k { font-size: 12px; color: var(--ink-3); }
.big { font-size: 40px; }
.big small { font-size: 20px; }
.v { font-size: 12.5px; }
.compact { padding: 12px 14px; }
.compact .cn { font-size: 20px; }
.compact .big { font-size: 36px; }
</style>
