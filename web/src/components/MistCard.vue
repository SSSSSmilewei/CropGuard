<script setup lang="ts">
// 雾化卡片（手写 sketch 节点）：/api/mist/*。手机端与桌面「喷淋控制」共用。
// 口径提醒：单次时长受 SPRAY.max_duration 钳制；「持续喷雾」固件不会自停，
// 服务器按 direct_max_sec 兜底关闭 —— 页面上把上限直接写出来。
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { api, type MistStatus } from '../lib/api'
import { toast } from '../composables/station'
import Icon from './Icon.vue'

const props = withDefaults(defineProps<{ maxSec?: number; group?: string }>(), {
  maxSec: 5, group: 'all',
})

const st = ref<MistStatus | null>(null)
const seconds = ref(3)
const busy = ref('')
const loadErr = ref('')

const node = computed(() => st.value?.nodes?.[0] || null)
const online = computed(() => !!node.value?.reachable)
const running = computed(() => !!node.value?.running)
const stateText = computed(() => {
  const n = node.value
  if (!st.value) return '读取中…'
  if (!n) return '未配置节点'
  if (!n.reachable) return `连不上（${n.error || '检查节点是否上电 / 网段'}）`
  if (n.running) return n.mode === 'direct' ? '持续喷雾中（需手动停）' : `定时喷雾中 · 剩 ${n.remain ?? '?'} 秒`
  return '空闲'
})

async function refresh() {
  try {
    st.value = await api.mistStatus(props.group)
    loadErr.value = ''
  } catch (e) {
    loadErr.value = (e as Error).message
  }
}

async function run(kind: 'start' | 'direct' | 'stop') {
  if (busy.value) return
  busy.value = kind
  try {
    const r = kind === 'start' ? await api.mistStart(seconds.value, props.group)
      : kind === 'direct' ? await api.mistDirect(props.group)
        : await api.mistStop(props.group)
    if (r.success) {
      toast(kind === 'stop' ? '已停止雾化' : `已下发：${kind === 'direct' ? '持续喷雾' : `定时 ${seconds.value} 秒`}`, 'ok')
    } else {
      toast(`没有成功：${(r as { error?: string }).error || '节点没有应答'}`, 'bad')
    }
  } catch (e) {
    toast(`下发失败：${(e as Error).message}`, 'bad')
  } finally {
    busy.value = ''
    window.setTimeout(refresh, 900)      // 固件 /start 要 1.2 秒才回包，稍等再读状态
  }
}

let timer = 0
onMounted(() => { void refresh(); timer = window.setInterval(refresh, 4000) })
onBeforeUnmount(() => window.clearInterval(timer))
</script>

<template>
  <div class="mist">
    <div class="mrow">
      <span class="mnode mono">{{ node?.url || '未配置节点地址' }}</span>
      <span class="chip" :class="{ ok: online, bad: !online && !!node, warn: !node }">{{ online ? '在线' : node ? '离线' : '未配置' }}</span>
    </div>
    <p class="mstate" :class="{ on: running }">{{ stateText }}</p>
    <p v-if="loadErr" class="merr">{{ loadErr }}</p>

    <div class="mctl">
      <label class="msec">单次 <input v-model.number="seconds" type="number" min="1" :max="maxSec" inputmode="numeric"> 秒
        <span class="mono">≤ {{ maxSec }}s</span>
      </label>
      <button type="button" class="btn btn-sm" :disabled="!!busy || !online" @click="run('start')">
        <Icon name="drop" :size="15" />定时喷雾
      </button>
      <button type="button" class="btn btn-sm" :disabled="!!busy || !online" @click="run('direct')">
        持续喷雾
      </button>
      <button type="button" class="btn btn-sm btn-primary" :disabled="!!busy" @click="run('stop')">
        <Icon name="stop" :size="15" />立即停止
      </button>
    </div>
    <p class="mhint">持续喷雾固件不会自停，服务器最多等 {{ st?.direct_max_sec ?? 300 }} 秒兜底关闭。</p>
  </div>
</template>

<style scoped>
.mist { display: flex; flex-direction: column; gap: 8px; }
.mrow { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.mnode { font-size: 12px; color: var(--ink-2); overflow-wrap: anywhere; }
.chip { font-size: 11px; padding: 2px 8px; border-radius: 999px; border: 1px solid var(--line-strong); color: var(--ink-2); }
.chip.ok { color: var(--brand); border-color: var(--brand); background: var(--brand-soft); }
.chip.bad { color: var(--risk-high); border-color: var(--risk-high); }
.mstate { font-size: 13px; color: var(--ink-2); }
.mstate.on { color: var(--brand); font-weight: 500; }
.merr { font-size: 12px; color: var(--risk-high); }
.mctl { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.msec { display: inline-flex; align-items: center; gap: 6px; font-size: 13px; color: var(--ink-2); }
.msec input { width: 64px; padding: 5px 8px; border: 1px solid var(--line-strong); border-radius: var(--r-sm); background: var(--paper); color: var(--ink); }
.mhint { font-size: 12px; color: var(--ink-3); line-height: 1.6; }
</style>
