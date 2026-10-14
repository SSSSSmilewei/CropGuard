<script setup lang="ts">
// 实时监测：服务器相机（共享采集源）→ /ws/stream 推帧 + 检测结果；框由前端叠加。
// 右侧：当前片区风险、手动喷淋（按住确认）、联动记录。底部：近 60 秒风险时间线。
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api, wsUrl, type CameraState, type Detection, type Risk } from '../lib/api'
import { RISK_ORDER, latinName, riskKey, sortByConf, type RiskKey } from '../lib/format'
import { toast, useStation } from '../composables/station'
import DetectionStage from '../components/DetectionStage.vue'
import HistoryList from '../components/HistoryList.vue'
import Icon from '../components/Icon.vue'
import SprayControl from '../components/SprayControl.vue'

interface StreamMsg {
  success?: boolean
  error?: string
  warning?: string
  detections?: Detection[]
  risk?: Risk
  result_image?: string
  image_size?: [number, number]
  zone?: string
  camera?: CameraState
  result_age?: number | null
}

const route = useRoute()
const router = useRouter()
const { state } = useStation({ history: true })

const zones = computed(() => state.spray?.zones || [])
const zone = ref<string>(String(route.query.cam || ''))
const zoneGroup = computed(() => zones.value.find((z) => String(z.id) === zone.value)?.group || null)
watch(zones, (zs) => { if (!zone.value && zs.length) zone.value = String(zs[0].id) }, { immediate: true })

const conn = ref<'wait' | 'on' | 'off' | 'error'>('wait')
const frame = ref<string | null>(null)
const size = ref<[number, number]>([1280, 720])
const dets = ref<Detection[]>([])
const risk = ref<Risk | null>(null)
const cam = ref<CameraState | null>(null)
const age = ref<number | null>(null)
const errorMsg = ref('')
const warnMsg = ref('')
const restarting = ref(false)
const activeDet = ref<number | null>(null)

let ws: WebSocket | null = null
let gen = 0
let retryT = 0
let objUrl: string | null = null

function b64ToUrl(b64: string) {
  const bin = atob(b64)
  const buf = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i)
  if (objUrl) URL.revokeObjectURL(objUrl)
  objUrl = URL.createObjectURL(new Blob([buf], { type: 'image/jpeg' }))
  return objUrl
}

function connect() {
  gen += 1
  const my = gen
  window.clearTimeout(retryT)
  if (ws) { ws.onclose = null; try { ws.close() } catch { /* 已关闭 */ } }
  conn.value = 'wait'
  errorMsg.value = ''
  ws = new WebSocket(wsUrl('/ws/stream' + (zone.value ? `?cam=${encodeURIComponent(zone.value)}` : '')))
  ws.onopen = () => { if (my === gen) conn.value = 'on' }
  ws.onmessage = (ev) => {
    if (my !== gen) return
    let d: StreamMsg
    try { d = JSON.parse(ev.data) } catch { return }
    onMsg(d)
  }
  ws.onclose = () => {
    if (my !== gen) return
    if (conn.value !== 'error') conn.value = 'off'
    retryT = window.setTimeout(connect, errorMsg.value ? 5000 : 2000)
  }
  ws.onerror = () => { try { ws?.close() } catch { /* 忽略 */ } }
}

function onMsg(d: StreamMsg) {
  if (d.error) {
    errorMsg.value = d.error
    cam.value = d.camera || cam.value
    conn.value = 'error'
    frame.value = null
    return
  }
  if (d.warning) {
    warnMsg.value = d.warning + (d.camera?.last_error ? `（${d.camera.last_error}）` : '')
    cam.value = d.camera || cam.value
    return
  }
  warnMsg.value = ''
  errorMsg.value = ''
  conn.value = 'on'
  if (d.result_image) frame.value = b64ToUrl(d.result_image)
  if (d.image_size) size.value = d.image_size
  else if (d.camera?.size) {
    const [w, h] = d.camera.size.split('x').map(Number)
    if (w && h) size.value = [w, h]
  }
  dets.value = sortByConf(d.detections || [])
  risk.value = d.risk || null
  cam.value = d.camera || null
  age.value = d.result_age ?? null
  if (d.detections) bucketRisk = maxRisk(bucketRisk, riskKey(d.risk?.level))
}

/* ---------------- 近 60 秒风险时间线（每秒取该秒内最高风险） ---------------- */
const RANK: Record<RiskKey, number> = { none: 0, low: 1, mid: 2, high: 3 }
const maxRisk = (a: RiskKey | null, b: RiskKey) => (!a || RANK[b] > RANK[a] ? b : a)
let bucketRisk: RiskKey | null = null
const timeline = ref<(RiskKey | null)[]>(Array(60).fill(null))
const tlStart = ref(new Date())
let tlTimer = 0
function tickTimeline() {
  timeline.value = [...timeline.value.slice(1), conn.value === 'on' ? bucketRisk : null]
  bucketRisk = null
  tlStart.value = new Date(Date.now() - 59_000)
}
const hhmmss = (d: Date) => d.toLocaleTimeString('zh-CN', { hour12: false })

watch(zone, (z) => {
  router.replace({ query: z ? { cam: z } : {} })
  timeline.value = Array(60).fill(null)
  connect()
})

async function restart() {
  restarting.value = true
  try {
    const r = await api.restartCamera(zone.value || null)
    toast(r.success ? '相机已重启' : `重启没有成功：${r.state?.last_error || '设备无响应'}`, r.success ? 'ok' : 'bad')
    if (r.success) connect()
  } catch (e) {
    toast(`重启失败：${(e as Error).message}`, 'bad')
  } finally {
    restarting.value = false
  }
}

function onVisibility() {
  if (document.hidden) {
    gen += 1
    window.clearTimeout(retryT)
    if (ws) { ws.onclose = null; ws.close(); ws = null }
    conn.value = 'off'
  } else {
    connect()
  }
}
onMounted(() => {
  if (!zones.value.length || zone.value) connect()
  tlTimer = window.setInterval(tickTimeline, 1000)
  document.addEventListener('visibilitychange', onVisibility)
})
onBeforeUnmount(() => {
  gen += 1
  window.clearTimeout(retryT)
  window.clearInterval(tlTimer)
  if (ws) { ws.onclose = null; ws.close() }
  if (objUrl) URL.revokeObjectURL(objUrl)
  document.removeEventListener('visibilitychange', onVisibility)
})

const camLabel = computed(() => {
  const c = cam.value
  if (!c) return ''
  if (c.device) return c.device
  return /^\d+$/.test(String(c.name ?? '')) ? `相机 ${c.name}` : String(c.name || '')
})
const zoneName = computed(() => zones.value.find((z) => String(z.id) === zone.value)?.name || '默认相机')
const connText = computed(() => ({ wait: '正在打开相机…', on: '已连接', off: '已断开，2 秒后重连', error: '相机不可用' })[conn.value])
</script>

<template>
  <main class="page">
    <section class="main-col">
      <div class="bar">
        <div v-if="zones.length" class="zones" role="tablist" aria-label="片区">
          <button
            v-for="z in zones"
            :key="z.id"
            type="button"
            role="tab"
            class="btn"
            :class="{ 'btn-primary': String(z.id) === zone }"
            :aria-selected="String(z.id) === zone"
            @click="zone = String(z.id)"
          >{{ z.name }} · {{ z.group }}</button>
        </div>
        <span class="conn"><span class="dot" :class="{ ok: conn === 'on', warn: conn === 'wait', bad: conn === 'error' || conn === 'off' }" />{{ connText }}</span>
        <span class="mono cam-meta">{{ camLabel }}{{ cam?.size ? ` · ${cam.size}` : '' }}{{ cam?.fps != null ? ` · ${cam.fps} fps` : '' }}</span>
      </div>

      <div class="viewer">
        <DetectionStage
          v-if="frame"
          v-model:active="activeDet"
          :src="frame"
          :width="size[0]"
          :height="size[1]"
          :detections="dets"
          variant="dark"
          max-height="min(620px, 64vh)"
        />
        <div v-else class="viewer-empty">
          <Icon name="live" :size="36" :stroke="1.4" />
          <template v-if="errorMsg">
            <p class="ve-t">{{ errorMsg }}</p>
            <p class="ve-s">检查相机是否插好、是否被桌面 GUI 占用；也可以运行 <span class="mono">python tool/camera_probe.py</span> 重新认索引。</p>
            <button type="button" class="btn" :disabled="restarting" @click="restart"><Icon name="refresh" :size="16" />{{ restarting ? '正在重启…' : '重启相机' }}</button>
          </template>
          <p v-else class="ve-t">正在打开相机（冷启动最长约 8 秒）…</p>
        </div>
        <div v-if="frame" class="hud mono">
          <span class="hc"><span class="live" />LIVE {{ zoneName }}</span>
          <span class="hc">{{ cam?.fps ?? '--' }} fps</span>
          <span class="hc" :class="{ stale: age != null && age > 3 }">{{ age == null ? '推理中…' : `推理 ${age.toFixed(1)} s 前` }}</span>
        </div>
        <div v-if="warnMsg && frame" class="warn">
          <span>{{ warnMsg }}</span>
          <button type="button" class="btn btn-sm" :disabled="restarting" @click="restart">重启相机</button>
        </div>
      </div>

      <div class="panel panel-pad">
        <div class="panel-head">
          <h2>风险时间线</h2>
          <span class="muted small">近 60 秒 · 每格 1 秒</span>
          <span class="legend">
            <span v-for="r in RISK_ORDER.slice().reverse()" :key="r.key"><i :class="`bg-${r.key}`" />{{ r.short }}</span>
          </span>
        </div>
        <div class="tl" role="img" :aria-label="`近 60 秒风险：最高 ${timeline.filter(Boolean).length ? '已记录' : '暂无数据'}`">
          <span v-for="(k, i) in timeline" :key="i" :class="k ? `bg-${k}` : 'gap'" />
        </div>
        <div class="tl-axis mono"><span>{{ hhmmss(tlStart) }}</span><span>现在</span></div>
      </div>
    </section>

    <aside class="side-col">
      <div class="panel panel-pad">
        <div class="eyebrow">{{ zoneName }} 当前</div>
        <div class="risk-line">
          <span class="risk-lv" :class="risk ? `risk-${riskKey(risk.level)}` : 'muted'">{{ risk?.level || '--' }}</span>
          <span class="risk-dt">{{ dets.length ? `${dets.length} 个目标` : risk?.detail || '等待推理结果' }}</span>
        </div>
        <div v-if="dets.length" class="det-list">
          <div
            v-for="(d, i) in dets"
            :key="i"
            class="det"
            :class="{ on: activeDet === i }"
            @mouseenter="activeDet = i"
            @mouseleave="activeDet = null"
          >
            <span>{{ d.chinese_name }} <span class="latin small">{{ latinName(d.class_name) }}</span></span>
            <span class="mono">{{ (d.confidence * 100).toFixed(0) }}%</span>
          </div>
        </div>
        <p v-else class="empty">画面里没有检出害虫。高、中风险会自动按预案喷淋并语音播报。</p>
      </div>

      <div class="panel panel-pad">
        <div class="panel-head"><h2>手动喷淋</h2></div>
        <SprayControl via="web" :preset="zoneGroup" />
      </div>

      <div class="panel panel-pad">
        <div class="panel-head"><h2>联动记录</h2></div>
        <HistoryList :limit="8" />
      </div>
    </aside>
  </main>
</template>

<style scoped>
.page {
  display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start;
  max-width: 1440px; margin: 0 auto; padding: 24px 32px 40px;
}
.main-col { flex: 999 1 640px; min-width: 0; display: flex; flex-direction: column; gap: 16px; }
.side-col { flex: 1 1 360px; min-width: 0; max-width: 100%; display: flex; flex-direction: column; gap: 24px; }
@media (min-width: 1100px) { .side-col { max-width: 420px; } }
.bar { display: flex; align-items: center; flex-wrap: wrap; gap: 8px 16px; }
.zones { display: flex; gap: 8px; flex-wrap: wrap; }
.conn { display: inline-flex; align-items: center; gap: 7px; font-size: 13px; color: var(--ink-2); }
.cam-meta { margin-left: auto; font-size: 12px; color: var(--ink-3); }
.viewer { position: relative; background: var(--stage); border-radius: var(--r-lg); overflow: hidden; }
.viewer-empty {
  min-height: min(520px, 56vh); display: flex; flex-direction: column; align-items: center; justify-content: center;
  gap: 10px; padding: 32px; text-align: center; color: #AEB8B0;
}
.ve-t { color: var(--stage-ink); font-size: 15px; max-width: 520px; }
.ve-s { font-size: 13px; max-width: 520px; }
.viewer-empty .btn { background: transparent; color: var(--stage-ink); border-color: #3A453E; }
.hud { position: absolute; left: 14px; top: 14px; display: flex; gap: 6px; flex-wrap: wrap; font-size: 12px; pointer-events: none; }
.hc { display: inline-flex; align-items: center; gap: 6px; padding: 3px 9px; border-radius: var(--r-sm); background: var(--overlay); color: var(--stage-ink); }
.hc.stale { background: rgba(178, 90, 12, 0.88); }
.live { width: 7px; height: 7px; border-radius: 50%; background: #E0503C; animation: blink 1.4s infinite; }
@keyframes blink { 50% { opacity: .3; } }
.warn {
  position: absolute; left: 12px; right: 12px; bottom: 12px; display: flex; align-items: center; gap: 12px;
  padding: 8px 12px; border-radius: var(--r); background: rgba(58, 42, 23, 0.94); color: #FFD9A8; font-size: 13px;
}
.warn span { flex: 1; }
.small { font-size: 12px; }
.legend { margin-left: auto; display: flex; gap: 12px; font-size: 12px; color: var(--ink-2); }
.legend span { display: inline-flex; align-items: center; gap: 5px; }
.legend i { width: 10px; height: 10px; display: inline-block; }
.tl { display: grid; grid-template-columns: repeat(60, minmax(0, 1fr)); gap: 2px; height: 32px; }
.tl .gap { background: var(--inset); opacity: .5; }
.bg-high { background: var(--risk-high); }
.bg-mid { background: var(--risk-mid); }
.bg-low { background: var(--risk-low); }
.bg-none { background: var(--line-strong); }
.tl-axis { display: flex; justify-content: space-between; margin-top: 6px; font-size: 11px; color: var(--ink-3); }
.risk-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; margin: 6px 0 10px; }
.risk-lv { font-size: 30px; font-weight: 700; line-height: 1.15; }
.risk-dt { font-size: 13px; color: var(--ink-2); }
.det-list { display: flex; flex-direction: column; }
.det { display: flex; justify-content: space-between; gap: 10px; padding: 9px 0; border-top: 1px solid var(--line); font-size: 13px; }
.det.on { color: var(--signal-ink); }
@media (max-width: 640px) {
  .page { padding: 16px; gap: 16px; }
  .cam-meta { margin-left: 0; width: 100%; }
}
</style>
