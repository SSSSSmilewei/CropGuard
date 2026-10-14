<script setup lang="ts">
// 一句话控制喷洒：先只解析（/api/ask_command execute=false），人工确认后才执行。
// 大模型/自由文本永远不直接驱动硬件；分组白名单与时长钳制由后端负责。
import { ref } from 'vue'
import { api, type CommandParse } from '../lib/api'
import { groupLabel } from '../lib/format'
import { toast, useStation } from '../composables/station'

const props = withDefaults(defineProps<{ placeholder?: string }>(), { placeholder: '例如：给 A 片区喷 3 秒' })
const { zoneOf, refreshHistory } = useStation()

const text = ref('')
const parsed = ref<CommandParse | null>(null)
const parsedText = ref('')
const busy = ref(false)
const error = ref('')

async function parse() {
  const t = text.value.trim()
  if (!t || busy.value) return
  busy.value = true
  error.value = ''
  try {
    parsed.value = await api.parseCommand(t, false)
    parsedText.value = t
  } catch (e) {
    parsed.value = null
    error.value = (e as Error).message
  } finally {
    busy.value = false
  }
}
async function execute() {
  if (!parsed.value || busy.value) return
  busy.value = true
  try {
    const r = await api.parseCommand(parsedText.value, true)
    if (r.executed) {
      toast(r.intent === 'stop'
        ? `已停止 ${groupLabel(r.group, zoneOf.value)}`
        : `已下发：${groupLabel(r.group, zoneOf.value)} 喷淋 ${r.duration} 秒`)
      parsed.value = null
      text.value = ''
    } else {
      toast(r.available ? (r.reply || '执行失败') : '节点没有应答，指令未送达', 'bad')
    }
  } catch (e) {
    toast(`下发失败：${(e as Error).message}`, 'bad')
  } finally {
    busy.value = false
    refreshHistory()
  }
}
</script>

<template>
  <div class="cmd">
    <form class="row" @submit.prevent="parse">
      <label class="sr-only" for="cmd-input">喷洒指令</label>
      <input id="cmd-input" v-model="text" class="input grow" type="text" :placeholder="props.placeholder" autocomplete="off">
      <button class="btn btn-outline-brand" type="submit" :disabled="busy || !text.trim()">解析</button>
    </form>
    <div v-if="error" class="notice">解析失败：{{ error }}</div>
    <div v-else-if="parsed && !parsed.valid" class="notice">
      <div>不会执行：{{ parsed.reply || parsed.reason || '没有听懂这句指令' }}</div>
      <div class="sub">可以这样说：给 A 片区喷 3 秒 / 停止 B 片区</div>
    </div>
    <div v-else-if="parsed" class="notice">
      <div>
        解析为：
        <template v-if="parsed.intent === 'stop'">停止 <b>{{ groupLabel(parsed.group, zoneOf) }}</b></template>
        <template v-else><b>{{ groupLabel(parsed.group, zoneOf) }}</b>（{{ parsed.group }}）喷洒 <b>{{ parsed.duration }} 秒</b></template>
      </div>
      <div v-if="parsed.reply.includes('钳制')" class="sub">{{ parsed.reply.replace(/^解析为：[^（]*/, '').replace(/。?请确认后执行。?$/, '') }}</div>
      <div class="row actions">
        <button class="btn btn-primary grow" type="button" :disabled="busy" @click="execute">确认下发</button>
        <button class="btn" type="button" @click="parsed = null">取消</button>
      </div>
    </div>
    <p class="hint">指令只会被解析，必须点"确认下发"才会执行。</p>
  </div>
</template>

<style scoped>
.cmd { display: flex; flex-direction: column; gap: 10px; }
.row { display: flex; gap: 8px; }
.grow { flex: 1; }
.actions { margin-top: 10px; }
.hint { font-size: 12px; color: var(--ink-3); }
</style>
