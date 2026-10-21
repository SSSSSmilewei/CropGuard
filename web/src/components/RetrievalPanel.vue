<script setup lang="ts">
// 检索透视：把"为什么答 / 为什么拒"摊开给人看——闸门分、拒答线、召回片段及分数。
import { computed } from 'vue'
import { useChat } from '../composables/chat'

const { retrieval } = useChat()
const SCALE = 0.5 // 刻度上限：闸门分实际很少超过 0.5
const r = computed(() => retrieval.value)
const pos = (v: number) => `${Math.min(100, (v / SCALE) * 100)}%`
const maxChunk = computed(() => Math.max(0.0001, ...(r.value?.chunks || []).map((c) => c.score)))
</script>

<template>
  <div class="panel panel-pad">
    <div class="panel-head">
      <h2>检索透视</h2>
      <span v-if="r" class="muted q">“{{ r.question }}”</span>
    </div>
    <template v-if="r">
      <div class="gate">
        <span class="num gv">{{ r.gate_score.toFixed(3) }}</span>
        <span :class="r.will_refuse ? 'risk-mid' : 'muted'">闸门分 · {{ r.will_refuse ? '低于拒答线，不调用大模型' : '放行' }}</span>
      </div>
      <div class="scale">
        <div class="track"><div class="fill" :class="{ low: r.will_refuse }" :style="{ width: pos(r.gate_score) }" /></div>
        <div class="line" :style="{ left: pos(r.refuse_below) }" />
      </div>
      <div class="axis mono">
        <span>0</span>
        <span class="ax-mid" :style="{ left: pos(r.refuse_below) }">拒答线 {{ r.refuse_below }}</span>
        <span>{{ SCALE.toFixed(2) }}</span>
      </div>
      <div v-if="r.detected_pests?.length" class="pests">识别到问题里的害虫：{{ r.detected_pests.join('、') }}</div>
      <div class="chunks">
        <details v-for="(c, i) in r.chunks" :key="c.id" class="chunk">
          <summary>
            <span class="ct"><span class="mono muted">[{{ i + 1 }}]</span> {{ c.title }}</span>
            <span class="mono">{{ c.score.toFixed(3) }}</span>
            <span class="cb"><span :style="{ width: `${(c.score / maxChunk) * 100}%` }" /></span>
          </summary>
          <p class="ctext">{{ c.text }}</p>
        </details>
      </div>
      <p class="stat mono">知识库 {{ r.stats.chunks }} 条片段 · {{ r.stats.pests }} 类害虫 · {{ r.stats.aliases }} 个别名 · {{ r.stats.vectorizer }}</p>
    </template>
    <p v-else class="empty">提问后这里会显示检索到的知识片段和闸门分。闸门分低于拒答线时，系统直接拒答，不调用大模型。</p>
  </div>
</template>

<style scoped>
.q { font-size: 12px; overflow-wrap: anywhere; }
.gate { display: flex; align-items: baseline; flex-wrap: wrap; gap: 6px 10px; margin-bottom: 8px; font-size: 13px; }
.gv { font-size: 44px; }
.scale { position: relative; }
.track { height: 10px; background: var(--inset); }
.fill { height: 100%; background: var(--brand); transition: width .3s; }
.fill.low { background: var(--risk-mid); }
.line { position: absolute; top: -5px; width: 2px; height: 20px; background: var(--ink); transform: translateX(-1px); }
.axis { position: relative; display: flex; justify-content: space-between; height: 18px; margin-top: 4px; font-size: 11px; color: var(--ink-3); }
.ax-mid { position: absolute; transform: translateX(-50%); white-space: nowrap; }
.pests { margin-top: 10px; font-size: 12.5px; color: var(--ink-2); }
.chunks { margin-top: 12px; display: flex; flex-direction: column; }
.chunk { border-top: 1px solid var(--inset); }
.chunk summary {
  display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 6px 10px; padding: 10px 0;
  cursor: pointer; list-style: none; font-size: 13px;
}
.chunk summary::-webkit-details-marker { display: none; }
.ct { overflow-wrap: anywhere; }
.cb { grid-column: 1 / -1; height: 4px; background: var(--inset); }
.cb span { display: block; height: 100%; background: var(--signal-ink); }
.ctext { padding: 0 0 12px; font-size: 12.5px; line-height: 1.75; color: var(--body-ink); }
.stat { margin-top: 12px; font-size: 11px; color: var(--ink-3); }
</style>
