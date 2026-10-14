<script setup lang="ts">
// 检测台：一次可以放进多张样本，按顺序识别并计时（对应现场"20 张 / 180 秒"评测）。
// 原图 + 前端叠框；右侧是风险判定、标本签、防治建议（知识库秒出，本地大模型生成后替换）。
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { api, type DetectResult } from '../lib/api'
import { areaRatio, clock, groupLabel, riskKey, sortByConf, timeOf } from '../lib/format'
import { setChatContext } from '../composables/chat'
import { toast, useStation } from '../composables/station'
import AdviceBody from '../components/AdviceBody.vue'
import DetectionStage from '../components/DetectionStage.vue'
import HoldButton from '../components/HoldButton.vue'
import Icon from '../components/Icon.vue'
import RiskMeter from '../components/RiskMeter.vue'
import SpecimenCard from '../components/SpecimenCard.vue'

interface Sample {
  id: number
  no: string
  name: string
  file: File
  url: string
  w: number
  h: number
  status: 'queued' | 'running' | 'done' | 'error'
  result?: DetectResult
  error?: string
  advice?: string
  adviceSource?: string
  adviceState: 'idle' | 'loading' | 'done'
}

const { state, zoneOf, refreshHistory } = useStation()

const samples = ref<Sample[]>([])
const currentId = ref<number | null>(null)
const activeDet = ref<number | null>(null)
const conf = ref(0.4)
const dragging = ref(false)
const fileInput = ref<HTMLInputElement | null>(null)
let seq = 0

const target = computed(() => state.config?.eval_target || 20)
const limit = computed(() => state.config?.eval_time_limit || 180)
watch(() => state.config?.conf_default, (v) => { if (v) conf.value = v }, { immediate: true })

const current = computed(() => samples.value.find((s) => s.id === currentId.value) || null)
const dets = computed(() => sortByConf(current.value?.result?.detections || []))
const top = computed(() => dets.value[activeDet.value ?? 0] || dets.value[0] || null)
const risk = computed(() => current.value?.result?.risk || null)
const area = computed(() => (current.value ? areaRatio(dets.value, current.value.w, current.value.h) : 0))
const plan = computed(() => {
  const m = state.config?.risk_map?.[risk.value?.level || '']
  return m && m.group && m.duration > 0 ? m : null
})

/* ---------------- 计时：从第一张开始识别算起，到最后一张出结果为止 ---------------- */
const session = reactive({ start: 0, last: 0, now: 0 })
let ticker = 0
const running = computed(() => samples.value.some((s) => s.status === 'running' || s.status === 'queued'))
const elapsed = computed(() => (session.start ? ((running.value ? session.now : session.last) - session.start) / 1000 : 0))
const doneCount = computed(() => samples.value.filter((s) => s.status === 'done').length)
const avg = computed(() => {
  const d = samples.value.filter((s) => s.result)
  return d.length ? d.reduce((a, s) => a + (s.result!.inference_time || 0), 0) / d.length : 0
})
watch(running, (r) => {
  window.clearInterval(ticker)
  if (r) ticker = window.setInterval(() => { session.now = performance.now() }, 200)
})

/* ---------------- 选图 ---------------- */
function readSize(url: string) {
  return new Promise<{ w: number; h: number }>((resolve) => {
    const img = new Image()
    img.onload = () => resolve({ w: img.naturalWidth, h: img.naturalHeight })
    img.onerror = () => resolve({ w: 0, h: 0 })
    img.src = url
  })
}
async function addFiles(files: FileList | File[] | null | undefined) {
  const list = Array.from(files || []).filter((f) => f.type.startsWith('image/'))
  if (!list.length) { toast('请选择图片文件（JPG / PNG）', 'bad'); return }
  for (const f of list) {
    const url = URL.createObjectURL(f)
    const { w, h } = await readSize(url)
    seq += 1
    samples.value.push({
      id: seq, no: String(seq).padStart(2, '0'), name: f.name || `粘贴的图片 ${seq}`, file: f, url, w, h,
      status: 'queued', adviceState: 'idle',
    })
    if (currentId.value == null || list.length === 1) currentId.value = seq
  }
  pump()
}
function onPick(e: Event) {
  const input = e.target as HTMLInputElement
  addFiles(input.files)
  input.value = ''
}
function onDrop(e: DragEvent) {
  dragging.value = false
  addFiles(e.dataTransfer?.files)
}
function onPaste(e: ClipboardEvent) {
  const files = Array.from(e.clipboardData?.items || [])
    .filter((i) => i.type.startsWith('image/'))
    .map((i) => i.getAsFile())
    .filter((f): f is File => !!f)
  if (files.length) addFiles(files)
}

/* ---------------- 识别队列（串行，计时才准） ---------------- */
let pumping = false
async function pump() {
  if (pumping) return
  pumping = true
  try {
    for (;;) {
      const s = samples.value.find((x) => x.status === 'queued')
      if (!s) break
      if (!session.start) { session.start = performance.now(); session.now = session.start }
      s.status = 'running'
      try {
        const r = await api.detect(s.file, conf.value, s.name)
        if (!r.success) throw new Error(r.error || '识别失败')
        s.result = r
        s.advice = r.advice
        s.adviceSource = r.advice_source
        s.status = 'done'
        if (r.detections.length) setChatContext(r.detections, r.risk)
      } catch (e) {
        s.status = 'error'
        s.error = (e as Error).message
        toast(`样本 ${s.no} 识别失败：${s.error}`, 'bad')
      }
      session.last = performance.now()
      if (s.id === currentId.value) loadAdvice(s)
    }
  } finally {
    pumping = false
  }
}
async function loadAdvice(s: Sample) {
  if (!s.result?.detections.length || s.adviceState !== 'idle') return
  s.adviceState = 'loading'
  try {
    const a = await api.advice(s.result.detections, s.result.risk)
    // 只有大模型真的生成了才替换：大模型不可用时网关返回的是检索片段原文，
    // 不如检测接口已经给出的结构化知识库方案好读
    if (a.advice && a.source === 'llm') { s.advice = a.advice; s.adviceSource = a.source }
  } catch { /* 大模型不可用：保留知识库版 */ }
  s.adviceState = 'done'
}
watch(currentId, () => {
  activeDet.value = null
  if (current.value?.status === 'done') loadAdvice(current.value)
})

function redetect() {
  const s = current.value
  if (!s) return
  s.status = 'queued'
  s.result = undefined
  s.adviceState = 'idle'
  pump()
}
function resetSession() {
  samples.value.forEach((s) => URL.revokeObjectURL(s.url))
  samples.value = []
  currentId.value = null
  session.start = session.last = session.now = 0
  seq = 0
}

async function sprayPlan() {
  if (!plan.value) return
  try {
    const r = await api.spray(plan.value.group!, plan.value.duration, 'web')
    if (r.success) toast(`已下发：${groupLabel(plan.value.group, zoneOf.value)} 喷淋 ${r.duration} 秒`)
    else toast(r.reason || '节点没有应答，指令未送达', 'bad')
  } catch (e) {
    toast(`下发失败：${(e as Error).message}`, 'bad')
  }
  refreshHistory()
}

const adviceTag = computed(() => {
  const s = current.value
  if (!s?.result?.detections.length) return null
  if (s.adviceState === 'loading') return { text: '知识库 · 离线', note: '本地大模型生成中…' }
  if (s.adviceSource === 'llm') return { text: '本地大模型 · 依据知识库', note: '' }
  return { text: '知识库 · 离线', note: s.adviceState === 'done' ? '本地大模型未启动，显示知识库原文' : '' }
})

function onKey(e: KeyboardEvent) {
  if ((e.target as HTMLElement)?.tagName === 'INPUT') return
  const i = samples.value.findIndex((s) => s.id === currentId.value)
  if (e.key === 'ArrowRight' && i < samples.value.length - 1) currentId.value = samples.value[i + 1].id
  if (e.key === 'ArrowLeft' && i > 0) currentId.value = samples.value[i - 1].id
}
onMounted(() => {
  document.addEventListener('paste', onPaste)
  document.addEventListener('keydown', onKey)
})
onBeforeUnmount(() => {
  document.removeEventListener('paste', onPaste)
  document.removeEventListener('keydown', onKey)
  window.clearInterval(ticker)
})
</script>

<template>
  <main class="page">
    <section class="main-col">
      <div
        class="panel stage-panel"
        :class="{ dragging }"
        @dragover.prevent="dragging = true"
        @dragleave.self="dragging = false"
        @drop.prevent="onDrop"
      >
        <div class="toolbar">
          <div class="title">
            <span class="num sample-no">{{ current ? `样本 ${current.no}` : '检测台' }}</span>
            <span class="mono file">{{ current ? `${current.name} · ${current.w} × ${current.h}` : '把样本图片拖进来，或点"选择图片"' }}</span>
          </div>
          <div class="tools">
            <label class="conf" for="conf">置信度阈值
              <input id="conf" v-model.number="conf" type="range" min="0.1" max="0.9" step="0.05">
              <span class="mono">{{ conf.toFixed(2) }}</span>
            </label>
            <button v-if="current && current.status !== 'running'" type="button" class="btn" title="按新阈值重新识别当前样本" @click="redetect">
              <Icon name="refresh" :size="16" />重新识别
            </button>
            <button type="button" class="btn btn-primary" @click="fileInput?.click()">
              <Icon name="image" :size="16" />选择图片
            </button>
            <input ref="fileInput" type="file" accept="image/*" multiple hidden @change="onPick">
          </div>
        </div>

        <DetectionStage
          v-model:active="activeDet"
          :src="current?.url"
          :width="current?.w"
          :height="current?.h"
          :detections="dets"
          :busy="current?.status === 'running' || current?.status === 'queued'"
          max-height="min(560px, 62vh)"
        >
          <template #empty>
            <button type="button" class="drop" @click="fileInput?.click()">
              <Icon name="image" :size="40" :stroke="1.4" />
              <span class="drop-t1">把样本图片拖到这里</span>
              <span class="drop-t2">或点击选择 · 也可以直接 Ctrl+V 粘贴截图<br>一次可以选多张，按顺序识别并计时</span>
            </button>
          </template>
        </DetectionStage>

        <div v-if="current" class="foot mono">
          <template v-if="current.result">
            <span>推理 {{ current.result.inference_time.toFixed(2) }} s</span>
            <span>imgsz {{ state.config?.imgsz || 640 }}</span>
            <span>{{ state.config?.model || 'YOLOv8s' }}</span>
            <span class="push">{{ dets.length ? `${dets.length} 个目标` : '未检出害虫' }}</span>
          </template>
          <span v-else-if="current.status === 'error'" class="risk-high">识别失败：{{ current.error }}</span>
          <span v-else>识别中…</span>
        </div>
      </div>

      <div class="panel panel-pad">
        <div class="session-head">
          <h2>本轮样本</h2>
          <span class="num count">{{ doneCount }} <span class="of">/ {{ target }}</span></span>
          <span class="mono timing">用时 {{ clock(elapsed) }} · 限时 {{ clock(limit) }}<template v-if="avg"> · 平均 {{ avg.toFixed(2) }} s/张</template></span>
          <button v-if="samples.length" type="button" class="btn btn-sm" @click="resetSession">新一轮</button>
        </div>
        <div class="progress" :title="`已完成 ${doneCount} / ${target}`">
          <div class="fill" :style="{ width: `${Math.min(100, (doneCount / target) * 100)}%` }" />
          <div v-if="session.start" class="mark" :class="{ over: elapsed > limit }" :style="{ left: `${Math.min(100, (elapsed / limit) * 100)}%` }" />
        </div>
        <div v-if="samples.length" class="strip">
          <button
            v-for="s in samples"
            :key="s.id"
            type="button"
            class="thumb"
            :class="{ on: s.id === currentId }"
            :aria-label="`样本 ${s.no}`"
            @click="currentId = s.id"
          >
            <span class="ti">
              <img :src="s.url" alt="">
              <span v-if="s.status === 'running' || s.status === 'queued'" class="tq">{{ s.status === 'running' ? '识别中' : '排队' }}</span>
              <span v-if="s.result" class="tr" :class="`bg-${riskKey(s.result.risk.level)}`" />
            </span>
            <span class="tc">
              <span class="tn">{{ s.result ? (s.result.detections[0]?.chinese_name || '未检出') : s.status === 'error' ? '失败' : `样本 ${s.no}` }}</span>
              <span class="mono tv">{{ s.result?.detections[0] ? s.result.detections[0].confidence.toFixed(2) : '' }}</span>
            </span>
          </button>
        </div>
        <p v-else class="empty">还没有样本。选图后从第一张开始计时，满 {{ target }} 张时对照限时看是否达标。←/→ 键切换样本。</p>
      </div>
    </section>

    <aside class="side-col">
      <div class="panel panel-pad">
        <div class="eyebrow">风险判定</div>
        <div class="risk-line">
          <span class="risk-lv" :class="risk ? `risk-${riskKey(risk.level)}` : 'muted'">{{ risk?.level || '等待样本' }}</span>
          <span class="risk-dt">{{ risk?.detail || '识别完成后按数量、置信度和覆盖面积判定' }}</span>
        </div>
        <RiskMeter :level="risk?.level || null" />
        <div v-if="risk" class="link-rows">
          <div class="lr">
            <span class="lk">联动预案</span>
            <span v-if="plan">{{ groupLabel(plan.group, zoneOf) }} 喷淋 {{ plan.duration }} 秒</span>
            <span v-else class="muted">该等级不喷淋</span>
          </div>
          <div class="lr">
            <span class="lk">说明</span>
            <span class="muted">检测台只识别不自动喷淋；实时监测和手机实时识别会按预案自动联动。</span>
          </div>
          <HoldButton v-if="plan" :disabled="!state.spray?.available" @fire="sprayPlan">按住 1 秒，按预案喷淋</HoldButton>
        </div>
      </div>

      <SpecimenCard
        v-if="top && current"
        :det="top"
        :no="String(current.id).padStart(4, '0')"
        origin="检测台"
        :time="timeOf(current.result?.timestamp)"
        :area="dets.length === 1 ? area : null"
        :elapsed="current.result?.inference_time ?? null"
      >
        <div v-if="dets.length > 1" class="others">
          <div class="eyebrow">本图共 {{ dets.length }} 个目标 · 总覆盖 {{ (area * 100).toFixed(1) }}%</div>
          <button
            v-for="(d, i) in dets"
            :key="i"
            type="button"
            class="other"
            :class="{ on: (activeDet ?? 0) === i }"
            @mouseenter="activeDet = i"
            @focus="activeDet = i"
            @click="activeDet = i"
          >
            <span>{{ d.chinese_name }}</span><span class="mono">{{ (d.confidence * 100).toFixed(1) }}%</span>
          </button>
        </div>
      </SpecimenCard>
      <div v-else-if="current?.status === 'done'" class="panel panel-pad">
        <div class="eyebrow">标本签</div>
        <p class="no-det">这张图没有检出害虫目标（阈值 {{ conf.toFixed(2) }}）。可以调低阈值后点"重新识别"。</p>
      </div>

      <div class="panel panel-pad">
        <div class="panel-head">
          <h2>防治建议</h2>
          <span v-if="adviceTag" class="tag">{{ adviceTag.text }}</span>
          <span v-if="adviceTag?.note" class="aside">{{ adviceTag.note }}</span>
        </div>
        <AdviceBody v-if="current?.advice && dets.length" :text="current.advice" />
        <p v-else class="empty">识别到害虫后，先给出知识库方案（离线、秒出），本地大模型就绪时再生成综合方案替换。</p>
        <p v-if="current?.advice && dets.length" class="fine">药剂与剂量以当地植保部门发布为准。</p>
      </div>
    </aside>
  </main>
</template>

<style scoped>
.page {
  display: flex; flex-wrap: wrap; gap: 24px; align-items: flex-start;
  max-width: 1440px; margin: 0 auto; padding: 24px 32px 40px;
}
.main-col { flex: 999 1 640px; min-width: 0; display: flex; flex-direction: column; gap: 24px; }
.side-col { flex: 1 1 360px; min-width: 0; max-width: 100%; display: flex; flex-direction: column; gap: 24px; }
@media (min-width: 1100px) { .side-col { max-width: 420px; } }

.stage-panel { overflow: hidden; }
.stage-panel.dragging { outline: 2px dashed var(--signal-ink); outline-offset: -6px; }
.toolbar {
  display: flex; align-items: center; flex-wrap: wrap; gap: 12px 20px;
  padding: 14px 20px; border-bottom: 1px solid var(--line);
}
.title { display: flex; align-items: baseline; gap: 12px; min-width: 0; }
.sample-no { font-size: 26px; white-space: nowrap; }
.file { font-size: 12px; color: var(--ink-3); overflow-wrap: anywhere; }
.tools { margin-left: auto; display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.conf { display: flex; align-items: center; gap: 10px; font-size: 13px; color: var(--ink-2); }
.conf input { width: 120px; accent-color: var(--brand); }
.conf .mono { color: var(--ink); }
.drop {
  display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 40px 24px;
  border: 1.5px dashed var(--line-strong); border-radius: var(--r-lg); background: var(--panel);
  color: var(--ink-2); cursor: pointer; text-align: center; max-width: 440px;
}
.drop:hover { border-color: var(--brand); color: var(--brand); }
.drop-t1 { font-family: var(--font-serif); font-size: 17px; font-weight: 700; color: var(--ink); }
.drop-t2 { font-size: 13px; color: var(--ink-3); line-height: 1.7; }
.foot { display: flex; flex-wrap: wrap; gap: 6px 24px; padding: 12px 20px; font-size: 12px; color: var(--ink-2); }
.push { margin-left: auto; }

.session-head { display: flex; align-items: baseline; flex-wrap: wrap; gap: 8px 18px; margin-bottom: 14px; }
.count { font-size: 22px; }
.of { font-size: 16px; color: var(--ink-3); }
.timing { margin-left: auto; font-size: 12px; color: var(--ink-2); }
.progress { position: relative; height: 4px; background: var(--inset); margin-bottom: 16px; }
.progress .fill { height: 100%; background: var(--brand); transition: width .3s; }
.progress .mark { position: absolute; top: -4px; width: 2px; height: 12px; background: var(--signal-ink); transform: translateX(-1px); }
.progress .mark.over { background: var(--risk-high); }
.strip { display: grid; grid-template-columns: repeat(auto-fill, minmax(104px, 1fr)); gap: 12px; }
.thumb { display: flex; flex-direction: column; gap: 6px; padding: 0; border: 0; background: none; cursor: pointer; text-align: left; min-width: 0; }
.ti {
  position: relative; display: block; aspect-ratio: 1 / 1; overflow: hidden; background: var(--inset);
  outline: 2px solid transparent; outline-offset: 2px; transition: outline-color .15s;
}
.thumb:hover .ti { outline-color: var(--line-strong); }
.thumb.on .ti { outline-color: var(--signal); }
.ti img { display: block; width: 100%; height: 100%; object-fit: cover; }
.tq {
  position: absolute; inset: 0; display: grid; place-items: center; font-size: 12px;
  background: rgba(15, 20, 17, 0.55); color: #F2F4EF;
}
.tr { position: absolute; left: 0; right: 0; bottom: 0; height: 4px; }
.bg-high { background: var(--risk-high); }
.bg-mid { background: var(--risk-mid); }
.bg-low { background: var(--risk-low); }
.bg-none { background: var(--risk-none); }
.tc { display: flex; justify-content: space-between; gap: 6px; font-size: 12px; min-width: 0; }
.tn { font-weight: 500; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.tv { color: var(--ink-2); }

.risk-line { display: flex; align-items: baseline; flex-wrap: wrap; gap: 4px 12px; margin: 6px 0 14px; }
.risk-lv { font-family: var(--font-serif); font-size: 30px; font-weight: 700; line-height: 1.2; }
.risk-dt { font-size: 13px; color: var(--ink-2); }
.link-rows { display: flex; flex-direction: column; gap: 8px; margin-top: 16px; padding-top: 14px; border-top: 1px solid var(--line); font-size: 13px; }
.lr { display: flex; gap: 10px; }
.lk { flex: none; width: 56px; color: var(--ink-3); }
.link-rows :deep(.hold) { margin-top: 6px; }

.others { margin-top: 14px; padding-top: 12px; border-top: 1px dashed var(--line-strong); display: flex; flex-direction: column; gap: 2px; }
.others .eyebrow { margin-bottom: 4px; }
.other {
  display: flex; justify-content: space-between; gap: 10px; padding: 6px 8px; margin: 0 -8px;
  border: 0; background: none; cursor: pointer; text-align: left; border-radius: var(--r-sm); font-size: 13px;
}
.other:hover, .other.on { background: var(--inset); }
.no-det { margin-top: 8px; font-size: 13px; color: var(--ink-2); }
.fine { margin-top: 14px; padding-top: 10px; border-top: 1px solid var(--line); font-size: 12px; color: var(--ink-3); }

@media (max-width: 640px) {
  .page { padding: 16px; gap: 16px; }
  .toolbar { padding: 12px 14px; }
  .tools { margin-left: 0; }
}
</style>
