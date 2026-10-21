<script setup lang="ts">
import { computed } from 'vue'
import { useChat } from '../composables/chat'
import { useStation } from '../composables/station'
import ChatThread from '../components/ChatThread.vue'
import RetrievalPanel from '../components/RetrievalPanel.vue'

const { context, messages, clear } = useChat()
const { state } = useStation()
const threshold = computed(() => state.config?.refuse_below ?? 0.18)

const STEPS = computed(() => [
  '在本地知识库里检索，算出闸门分',
  `闸门分低于 ${threshold.value} 直接拒答，不调用大模型`,
  '放行后只凭召回的片段作答，并标出处',
  '回答里出现知识库之外的药名或剂量，标注"请核实"',
])
</script>

<template>
  <main class="page">
    <section class="panel chat-panel">
      <div class="chat-head">
        <h2>对话</h2>
        <span class="muted ctx">{{ context ? `已带入当前检测：${context.label}` : '还没有检测结果；先在检测台识别，问"这个虫怎么防治"会自动带上下文' }}</span>
        <button v-if="messages.length" type="button" class="btn btn-sm" @click="clear">清空对话</button>
      </div>
      <ChatThread />
    </section>
    <aside class="side-col">
      <RetrievalPanel />
      <div class="panel panel-pad">
        <div class="panel-head"><h2>回答怎么来的</h2></div>
        <ol class="steps">
          <li v-for="(s, i) in STEPS" :key="i"><span class="num n">{{ i + 1 }}</span><span>{{ s }}</span></li>
        </ol>
      </div>
    </aside>
  </main>
</template>

<style scoped>
.page {
  display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start;
  max-width: 1440px; margin: 0 auto; padding: 24px 32px 40px;
}
.chat-panel {
  flex: 999 1 600px; display: flex; flex-direction: column;
  height: calc(100vh - var(--header-h) - 64px); min-height: 520px;
}
.chat-head { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 12px; padding: 14px 20px; border-bottom: 1px solid var(--line); }
.ctx { font-size: 12px; }
.chat-head .btn { margin-left: auto; }
.side-col { flex: 1 1 380px; min-width: 0; max-width: 100%; display: flex; flex-direction: column; gap: 24px; }
@media (min-width: 1100px) { .side-col { max-width: 440px; } }
.steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 10px; font-size: 13px; }
.steps li { display: grid; grid-template-columns: 22px minmax(0, 1fr); gap: 10px; }
.n { font-size: 18px; color: var(--signal-ink); line-height: 1.3; }
@media (max-width: 640px) {
  .page { padding: 16px; gap: 16px; }
  .chat-panel { height: 72vh; }
}
</style>
