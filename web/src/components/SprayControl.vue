<script setup lang="ts">
// 手动喷淋：选片区 → 选时长（1~上限秒，刻度块）→ 按住 1 秒下发；紧急停止单独一个大按钮。
// "已下发"只在节点真的回了 2xx 才提示（后端同步等待节点应答）。
import { computed, ref, watch } from 'vue'
import { api } from '../lib/api'
import { groupLabel } from '../lib/format'
import { toast, useStation } from '../composables/station'
import HoldButton from './HoldButton.vue'

const props = withDefaults(defineProps<{ via?: string; preset?: string | null; stopLabel?: string }>(), {
  via: 'web', preset: null, stopLabel: '紧急停止全部',
})
const { state, zoneOf, maxSpray, refreshHistory } = useStation()

const group = ref<string>(props.preset || 'all')
const duration = ref(2)
const sending = ref(false)
watch(() => props.preset, (g) => { if (g) group.value = g })
watch(maxSpray, (m) => { if (duration.value > m) duration.value = m })

const zones = computed(() => {
  const groups = state.spray?.groups || []
  const nodes = state.spray?.nodes || []
  const list = groups.map((g) => {
    const n = nodes.find((x) => x.group === g)
    let note = g
    let tone = ''
    if (n) {
      note = n.online ? `${g} · 在线` : `${g} · 离线`
      tone = n.online ? 'ok' : 'bad'
    }
    return { g, name: groupLabel(g, zoneOf.value), note, tone }
  })
  return [{ g: 'all', name: '全体', note: 'all', tone: '' }, ...list]
})
const ticks = computed(() => Array.from({ length: maxSpray.value }, (_, i) => i + 1))

async function fire() {
  if (sending.value) return
  sending.value = true
  try {
    const r = await api.spray(group.value, duration.value, props.via)
    if (r.success) toast(`已下发：${groupLabel(group.value, zoneOf.value)} 喷淋 ${r.duration} 秒`)
    else toast(r.reason || '节点没有应答，指令未送达。检查节点供电和 WiFi', 'bad')
  } catch (e) {
    toast(`下发失败：${(e as Error).message}`, 'bad')
  } finally {
    sending.value = false
    refreshHistory()
  }
}
async function stopAll() {
  try {
    const r = await api.stop('all', props.via)
    toast(r.success ? '已发送停止指令' : '停止指令未送达：喷淋链路不可用', r.success ? 'ok' : 'bad')
  } catch (e) {
    toast(`停止失败：${(e as Error).message}`, 'bad')
  }
  refreshHistory()
}
</script>

<template>
  <div class="spray">
    <div class="zones" role="radiogroup" aria-label="喷淋片区" :style="{ gridTemplateColumns: `repeat(${Math.min(zones.length, 3)}, minmax(0, 1fr))` }">
      <button
        v-for="z in zones"
        :key="z.g"
        type="button"
        role="radio"
        class="zone"
        :class="{ on: group === z.g }"
        :aria-checked="group === z.g"
        @click="group = z.g"
      >
        <span class="zn">{{ z.name }}</span>
        <span class="zs mono"><span v-if="z.tone" class="dot" :class="z.tone" />{{ z.note }}</span>
      </button>
    </div>

    <div class="dur">
      <div class="dur-head">
        <span class="muted">时长</span>
        <span class="num dur-val">{{ duration }} s</span>
      </div>
      <div class="ticks" role="radiogroup" aria-label="喷淋时长（秒）">
        <button
          v-for="t in ticks"
          :key="t"
          type="button"
          role="radio"
          class="tick"
          :class="{ lit: t <= duration }"
          :aria-checked="t === duration"
          :aria-label="`${t} 秒`"
          @click="duration = t"
        />
      </div>
      <div class="tick-labels mono"><span v-for="t in ticks" :key="t">{{ t }}</span></div>
    </div>

    <HoldButton :disabled="sending || !state.spray?.available" @fire="fire">
      {{ sending ? '正在等待节点应答…' : `按住 1 秒，给${groupLabel(group, zoneOf)}喷淋 ${duration} 秒` }}
    </HoldButton>
    <button type="button" class="btn btn-lg btn-block btn-danger-outline" @click="stopAll">{{ stopLabel }}</button>
    <p v-if="state.spray && !state.spray.available" class="hint">喷淋链路未配置：在 config/configs.yaml 的 SPRAY 段填写节点地址或串口。</p>
    <p v-else class="hint">雾化片单次通电上限 {{ maxSpray }} 秒，服务器和节点固件都会再钳一次。</p>
  </div>
</template>

<style scoped>
.spray { display: flex; flex-direction: column; gap: 12px; }
.zones { display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr)); gap: 8px; }
.zone {
  min-height: 64px; padding: 10px 12px; text-align: left; border-radius: var(--r);
  border: 1px solid var(--line-strong); background: var(--panel); cursor: pointer;
  display: flex; flex-direction: column; justify-content: center; gap: 2px;
}
.zone:hover { border-color: var(--brand); }
.zone.on { border: 2px solid var(--brand); background: var(--brand-soft); padding: 9px 11px; }
.zn { font-weight: 700; }
.zs { display: flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-2); }
.dur { margin-top: 4px; }
.dur-head { display: flex; justify-content: space-between; align-items: baseline; font-size: 13px; margin-bottom: 8px; }
.dur-val { font-size: 22px; }
.ticks, .tick-labels { display: grid; grid-auto-flow: column; grid-auto-columns: minmax(0, 1fr); gap: 4px; }
.tick { height: 30px; border: 0; padding: 0; background: var(--inset); cursor: pointer; }
.tick.lit { background: var(--brand); }
.tick:hover:not(.lit) { background: var(--line-strong); }
.tick-labels { margin-top: 4px; font-size: 11px; color: var(--ink-3); text-align: center; }
.hint { font-size: 12px; color: var(--ink-3); }
</style>
