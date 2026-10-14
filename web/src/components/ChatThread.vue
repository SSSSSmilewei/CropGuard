<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useChat } from '../composables/chat'
import Icon from './Icon.vue'

const props = withDefaults(defineProps<{ suggestions?: string[]; dense?: boolean }>(), {
  suggestions: () => ['这个虫怎么防治？', '玉米螟用什么药？', '蝗虫的寄主作物有哪些？'],
  dense: false,
})
const { messages, busy, send } = useChat()
const input = ref('')
const list = ref<HTMLElement | null>(null)

const SOURCE: Record<string, [string, string]> = {
  llm: ['本地大模型 · 依据知识库', 'tag-brand'],
  knowledge_base: ['知识库原文', ''],
  refused: ['已拒答', 'tag-warn'],
  error: ['出错', 'tag-warn'],
}

function submit(q?: string) {
  const text = (q ?? input.value).trim()
  if (!text) return
  input.value = ''
  send(text)
}
watch(() => messages.value.length, async () => {
  await nextTick()
  const el = list.value
  if (el) el.scrollTop = el.scrollHeight
})
</script>

<template>
  <div class="thread" :class="{ dense }">
    <div ref="list" class="msgs" aria-live="polite">
      <div v-if="!messages.length" class="intro">
        <p>只依据本地知识库回答（27 类害虫的寄主、为害、防治、监测）。</p>
        <p>知识库里找不到依据的问题会直接拒答，不会编造。</p>
      </div>
      <template v-for="m in messages" :key="m.id">
        <div v-if="m.role === 'me'" class="me">{{ m.text }}</div>
        <div v-else class="ai-wrap">
          <div class="ai" :class="{ pending: m.pending, refused: m.source === 'refused' || m.source === 'error' }">{{ m.text }}</div>
          <div v-if="!m.pending" class="tags">
            <span v-if="m.source === 'refused' && m.gate" class="tag tag-warn">
              已拒答 · 检索分 {{ m.gate.score.toFixed(3) }} 低于 {{ m.gate.threshold }}
            </span>
            <span v-else-if="SOURCE[m.source || '']" class="tag" :class="SOURCE[m.source || ''][1]">{{ SOURCE[m.source || ''][0] }}</span>
            <span v-if="m.guard?.unsupported?.length" class="tag tag-warn">含库外药名，已标注请核实</span>
            <span v-if="m.guard?.dosage_unsupported?.length" class="tag tag-warn">含库外剂量，已标注请核实</span>
            <span v-for="(c, i) in (m.citations || []).slice(0, 3)" :key="i" class="tag tag-fill">[{{ i + 1 }}] {{ c.title }}</span>
            <span v-if="m.elapsed != null" class="mono el">{{ m.elapsed }} s</span>
          </div>
        </div>
      </template>
    </div>
    <div class="composer">
      <div class="chips">
        <button v-for="s in props.suggestions" :key="s" type="button" class="chip" :disabled="busy" @click="submit(s)">{{ s }}</button>
      </div>
      <form class="row" @submit.prevent="submit()">
        <label class="sr-only" for="chat-input">问题</label>
        <input id="chat-input" v-model="input" class="input grow" type="text" placeholder="输入问题，回车发送" autocomplete="off">
        <button class="btn btn-primary send" type="submit" :disabled="busy || !input.trim()">
          <Icon name="send" :size="16" />发送
        </button>
      </form>
    </div>
  </div>
</template>

<style scoped>
.thread { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.msgs {
  flex: 1; min-height: 0; overflow-y: auto; padding: 24px 20px;
  display: flex; flex-direction: column; gap: 18px;
}
.intro { margin: auto 0; color: var(--ink-3); font-size: 13px; line-height: 1.8; }
.me {
  align-self: flex-end; max-width: 78%; padding: 10px 14px; overflow-wrap: anywhere;
  background: var(--brand); color: var(--brand-ink); border-radius: 6px 6px 2px 6px;
}
.ai-wrap { align-self: flex-start; max-width: 88%; display: flex; flex-direction: column; gap: 8px; }
.ai {
  padding: 12px 16px; background: var(--paper); border: 1px solid var(--line);
  border-radius: 6px 6px 6px 2px; white-space: pre-wrap; line-height: 1.8; overflow-wrap: anywhere;
}
.ai.pending { color: var(--ink-3); }
.ai.refused { background: var(--warn-bg); border-color: var(--warn-line); }
.tags { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.el { font-size: 12px; color: var(--ink-3); padding: 0 4px; }
.composer { padding: 14px 20px 18px; border-top: 1px solid var(--line); display: flex; flex-direction: column; gap: 10px; }
.chips { display: flex; gap: 6px; flex-wrap: wrap; }
.row { display: flex; gap: 8px; }
.grow { flex: 1; }
.send { min-height: 44px; padding: 0 20px; }
.dense .msgs { padding: 16px; }
.dense .composer { padding: 12px 16px; }
.dense .chips { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; }
.dense .chip { white-space: nowrap; }
</style>
