<script setup lang="ts">
import { computed } from 'vue'
import { describeHistory } from '../lib/format'
import { useStation } from '../composables/station'

const props = withDefaults(defineProps<{ limit?: number }>(), { limit: 50 })
const { state, zoneOf } = useStation({ history: true })
const rows = computed(() =>
  state.history.slice().reverse().slice(0, props.limit).map((h) => ({ ts: h.ts, ...describeHistory(h, zoneOf.value) })),
)
</script>

<template>
  <div v-if="rows.length" class="hist">
    <div v-for="(r, i) in rows" :key="i" class="row">
      <span class="ts mono">{{ r.ts }}</span>
      <span class="what">{{ r.what }}</span>
      <span class="tagx" :class="r.risk ? `risk-${r.risk}` : ''">{{ r.tag }}</span>
    </div>
  </div>
  <p v-else class="empty">还没有联动或喷淋记录。高、中风险检测和手动喷淋都会记在这里。</p>
</template>

<style scoped>
.row {
  display: grid; grid-template-columns: 64px minmax(0, 1fr) auto; gap: 10px; align-items: baseline;
  padding: 9px 0; border-top: 1px solid var(--inset); font-size: 13px;
}
.row:first-child { border-top: 0; }
.ts { font-size: 12px; color: var(--ink-3); }
.what { overflow-wrap: anywhere; }
.tagx { font-size: 12px; font-weight: 700; color: var(--ink-2); white-space: nowrap; }
</style>
