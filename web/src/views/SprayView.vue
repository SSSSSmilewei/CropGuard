<script setup lang="ts">
import { computed } from 'vue'
import { groupLabel } from '../lib/format'
import { useStation } from '../composables/station'
import CommandBox from '../components/CommandBox.vue'
import HistoryList from '../components/HistoryList.vue'
import MistCard from '../components/MistCard.vue'
import SprayControl from '../components/SprayControl.vue'

const { state, zoneOf, nodesOnline, refreshStatus } = useStation({ history: true })
const nodes = computed(() => state.spray?.nodes || [])
const plans = computed(() =>
  Object.entries(state.config?.risk_map || {}).map(([level, m]) => ({
    level,
    text: m.group && m.duration > 0 ? `${groupLabel(m.group, zoneOf.value)} 喷淋 ${m.duration} 秒` : '不喷淋',
  })),
)
</script>

<template>
  <main class="page">
    <section class="main-col">
      <div class="panel panel-pad">
        <div class="panel-head">
          <h2>喷洒节点</h2>
          <span class="aside mono">{{ state.spray?.transport?.toUpperCase() || '--' }} · {{ nodesOnline }}/{{ nodes.length }} 在线</span>
          <button type="button" class="btn btn-sm" @click="refreshStatus">重新探测</button>
        </div>
        <div v-if="nodes.length" class="table-wrap">
          <table class="tbl">
            <thead>
              <tr><th>片区</th><th>分组</th><th>状态</th><th>地址</th><th class="r">延迟</th><th class="r">信号</th><th class="r">累计执行</th></tr>
            </thead>
            <tbody>
              <tr v-for="n in nodes" :key="n.group + n.url">
                <td class="strong">{{ n.name || groupLabel(n.group, zoneOf) }}</td>
                <td class="mono">{{ n.group }}</td>
                <td>
                  <span class="st"><span class="dot" :class="n.online ? 'ok' : 'bad'" />{{ n.online ? (n.spraying ? '喷淋中' : '待机') : '离线' }}</span>
                  <div v-if="!n.online && n.error" class="err">{{ n.error }}</div>
                </td>
                <td class="mono addr">{{ n.ip || n.url }}</td>
                <td class="mono r">{{ n.latency_ms != null ? `${n.latency_ms} ms` : '--' }}</td>
                <td class="mono r">{{ n.rssi != null ? `${n.rssi} dBm` : '--' }}</td>
                <td class="mono r">{{ n.count ?? '--' }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <p v-else class="empty">没有配置喷洒节点。在 config/configs.yaml 的 SPRAY.http_targets 里按节点串口打印的 IP 填写。</p>
        <p class="hint">节点每 8 秒探测一次（GET /status）。离线时手动喷淋会提示"未送达"，不会假装成功。</p>
      </div>

      <div class="panel panel-pad">
        <div class="panel-head"><h2>联动记录</h2></div>
        <HistoryList />
      </div>
    </section>

    <aside class="side-col">
      <div class="panel panel-pad">
        <div class="panel-head"><h2>手动喷淋</h2></div>
        <SprayControl via="web" />
      </div>
      <div class="panel panel-pad">
        <div class="panel-head"><h2>雾化（ESP32 直连）</h2><span class="aside">手写 sketch · /api/mist</span></div>
        <MistCard :max-sec="state.spray?.max_duration || state.config?.max_spray || 5" />
      </div>
      <div class="panel panel-pad">
        <div class="panel-head"><h2>一句话控制</h2></div>
        <CommandBox />
      </div>
      <div v-if="plans.length" class="panel panel-pad">
        <div class="panel-head"><h2>自动联动预案</h2><span class="aside">实时监测与手机实时识别生效</span></div>
        <div v-for="p in plans" :key="p.level" class="plan">
          <span class="strong">{{ p.level }}</span><span>{{ p.text }}</span>
        </div>
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
.table-wrap { overflow-x: auto; }
.tbl { width: 100%; border-collapse: collapse; font-size: 13px; }
.tbl th { text-align: left; font-weight: 400; font-size: 12px; color: var(--ink-3); padding: 0 12px 8px 0; white-space: nowrap; }
.tbl td { padding: 12px 12px 12px 0; border-top: 1px solid var(--line); vertical-align: top; }
.tbl .r { text-align: right; }
.strong { font-family: var(--font-serif); font-weight: 700; }
.st { display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; }
.err { font-size: 12px; color: var(--ink-3); margin-top: 2px; }
.addr { font-size: 12px; overflow-wrap: anywhere; }
.hint { margin-top: 12px; font-size: 12px; color: var(--ink-3); }
.plan { display: flex; justify-content: space-between; gap: 10px; padding: 9px 0; border-top: 1px solid var(--inset); font-size: 13px; }
.plan:first-of-type { border-top: 0; }
@media (max-width: 640px) { .page { padding: 16px; gap: 16px; } }
</style>
