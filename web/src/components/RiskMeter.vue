<script setup lang="ts">
// 四级风险梯：无 → 低 → 中 → 高，点亮到当前等级。
import { computed } from 'vue'
import { RISK_ORDER, riskKey } from '../lib/format'
const props = withDefaults(defineProps<{ level?: string | null; compact?: boolean }>(), { level: null, compact: false })
const idx = computed(() => (props.level ? RISK_ORDER.findIndex((r) => r.key === riskKey(props.level)) : -1))
</script>

<template>
  <div class="meter" :class="{ compact }" role="img" :aria-label="`风险等级：${level || '未判定'}`">
    <div class="bars">
      <span v-for="(r, i) in RISK_ORDER" :key="r.key" class="bar" :class="[`k-${r.key}`, { lit: i <= idx }]" />
    </div>
    <div v-if="!compact" class="labels">
      <span v-for="(r, i) in RISK_ORDER" :key="r.key" :class="i === idx ? ['cur', `risk-${r.key}`] : []">{{ r.short }}</span>
    </div>
  </div>
</template>

<style scoped>
.bars, .labels { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 4px; }
.bar { height: 8px; background: var(--inset); transition: background-color .25s; }
.bar.lit.k-none { background: var(--risk-none); }
.bar.lit.k-low { background: var(--risk-low); }
.bar.lit.k-mid { background: var(--risk-mid); }
.bar.lit.k-high { background: var(--risk-high); }
.labels { margin-top: 6px; font-size: 12px; color: var(--ink-3); }
.labels .cur { font-weight: 700; }
.compact .bars { grid-template-columns: repeat(4, 10px); align-items: end; gap: 3px; }
.compact .bar:nth-child(1) { height: 8px; }
.compact .bar:nth-child(2) { height: 12px; }
.compact .bar:nth-child(3) { height: 16px; }
.compact .bar:nth-child(4) { height: 20px; }
</style>
