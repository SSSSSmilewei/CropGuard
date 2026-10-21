<script setup lang="ts">
// 防治建议正文：把知识库/大模型的纯文本解析成"小标题 + 字段 + 条目"，解析不出结构时按段落显示。
import { computed } from 'vue'
import { parseAdvice, splitMeasures } from '../lib/format'
const props = withDefaults(defineProps<{ text: string; skipDiagnosis?: boolean }>(), { skipDiagnosis: true })
const blocks = computed(() =>
  parseAdvice(props.text, { skipDiagnosis: props.skipDiagnosis }).map((b) => ({
    ...b,
    measures: b.kind === 'field' ? splitMeasures(b.text || '') : null,
  })),
)
</script>

<template>
  <div class="advice">
    <template v-for="(b, i) in blocks" :key="i">
      <h3 v-if="b.kind === 'heading'" class="h">{{ b.text }}</h3>
      <div v-else-if="b.kind === 'subhead'" class="sub">{{ b.text }}</div>
      <div v-else-if="b.kind === 'field'" class="field">
        <div class="fk">{{ b.label }}</div>
        <ul v-if="b.measures" class="ul">
          <li v-for="m in b.measures" :key="m">{{ m }}</li>
        </ul>
        <div v-else class="fv">{{ b.text }}</div>
      </div>
      <ul v-else-if="b.kind === 'list'" class="ul">
        <li v-for="m in b.items" :key="m">{{ m }}</li>
      </ul>
      <p v-else class="p">{{ b.text }}</p>
    </template>
  </div>
</template>

<style scoped>
.advice { display: flex; flex-direction: column; gap: 10px; font-size: 13.5px; line-height: 1.75; color: var(--body-ink); }
.h { font-size: 12px; font-weight: 400; letter-spacing: 0.08em; color: var(--ink-3); margin-top: 6px; }
.h:first-child { margin-top: 0; }
.sub { font-family: var(--font-serif); font-weight: 700; color: var(--ink); }
.field { display: grid; grid-template-columns: 44px minmax(0, 1fr); gap: 10px; }
.fk { font-weight: 700; color: var(--ink); }
.fv { overflow-wrap: anywhere; }
.ul { margin: 0; padding-left: 18px; }
.ul li::marker { color: var(--signal-ink); }
.p { overflow-wrap: anywhere; }
</style>
