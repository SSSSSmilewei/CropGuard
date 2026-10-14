<script setup lang="ts">
// 手机端外壳：顶部连接状态 + 底部四个标签（识别 / 问答 / 喷洒 / 记录）。标签状态记在地址栏 hash 里，刷新不丢。
import { computed, ref, watch } from 'vue'
import { useStation } from '../composables/station'
import BrandMark from '../components/BrandMark.vue'
import ChatThread from '../components/ChatThread.vue'
import CommandBox from '../components/CommandBox.vue'
import HistoryList from '../components/HistoryList.vue'
import Icon from '../components/Icon.vue'
import SprayControl from '../components/SprayControl.vue'
import ThemeButton from '../components/ThemeButton.vue'
import MobileDetect from './mobile/MobileDetect.vue'

type Tab = 'detect' | 'chat' | 'spray' | 'hist'
const TABS: { id: Tab; label: string; icon: string }[] = [
  { id: 'detect', label: '识别', icon: 'scan' },
  { id: 'chat', label: '问答', icon: 'chat' },
  { id: 'spray', label: '喷洒', icon: 'drop' },
  { id: 'hist', label: '记录', icon: 'list' },
]
const initial = location.hash.replace('#', '') as Tab
const tab = ref<Tab>(TABS.some((t) => t.id === initial) ? initial : 'detect')
watch(tab, (t) => {
  history.replaceState(null, '', `#${t}`)
  window.scrollTo(0, 0)
})

const { state, maxSpray } = useStation({ history: true })
const status = computed(() => {
  if (state.online === false) return { tone: 'bad', text: '连不上服务器' }
  if (!state.health) return { tone: '', text: '正在连接…' }
  return { tone: 'ok', text: `已连接 ${location.hostname}` }
})
const TITLES: Record<Tab, string> = { detect: '农智云', chat: '农技问答', spray: '喷洒控制', hist: '联动记录' }
</script>

<template>
  <div class="m-app">
    <header class="m-top">
      <BrandMark v-if="tab === 'detect'" :size="26" />
      <span class="m-title">{{ TITLES[tab] }}</span>
      <span v-if="tab === 'spray'" class="mono m-status">{{ state.spray?.transport?.toUpperCase() }} · 上限 {{ maxSpray }} s</span>
      <span v-else class="mono m-status"><span class="dot" :class="status.tone" />{{ status.text }}</span>
      <ThemeButton />
    </header>

    <main class="m-body" :class="{ chat: tab === 'chat' }">
      <KeepAlive>
        <MobileDetect v-if="tab === 'detect'" />
      </KeepAlive>
      <div v-if="tab === 'chat'" class="m-chat panel">
        <ChatThread dense :suggestions="['这个虫怎么防治？', '蚜虫用什么药？', '有什么危害？']" />
      </div>
      <template v-if="tab === 'spray'">
        <section class="panel panel-pad">
          <div class="panel-head"><h2>说一句话</h2></div>
          <CommandBox />
        </section>
        <section class="panel panel-pad">
          <div class="panel-head"><h2>手动喷洒</h2></div>
          <SprayControl via="phone" />
        </section>
      </template>
      <section v-if="tab === 'hist'" class="panel panel-pad">
        <HistoryList />
      </section>
    </main>

    <nav class="m-tabs" aria-label="手机导航">
      <button
        v-for="t in TABS"
        :key="t.id"
        type="button"
        :class="{ on: tab === t.id }"
        :aria-current="tab === t.id ? 'page' : undefined"
        @click="tab = t.id"
      >
        <Icon :name="t.icon" :size="22" :stroke="tab === t.id ? 2 : 1.8" />{{ t.label }}
      </button>
    </nav>
  </div>
</template>

<style scoped>
.m-app { min-height: 100vh; min-height: 100dvh; display: flex; flex-direction: column; }
.m-top {
  position: sticky; top: 0; z-index: 20; display: flex; align-items: center; gap: 10px;
  padding: calc(10px + env(safe-area-inset-top, 0px)) 12px 10px 16px;
  background: var(--panel); border-bottom: 1px solid var(--line);
}
.m-title { font-family: var(--font-serif); font-size: 18px; font-weight: 700; }
.m-status { margin-left: auto; display: inline-flex; align-items: center; gap: 6px; font-size: 11.5px; color: var(--ink-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.m-body {
  flex: 1; display: flex; flex-direction: column; gap: 12px;
  padding: 14px 16px calc(92px + env(safe-area-inset-bottom, 0px));
  width: 100%; max-width: 640px; margin: 0 auto;
}
.m-body.chat { padding-bottom: calc(76px + env(safe-area-inset-bottom, 0px)); }
.m-chat { height: calc(100dvh - 150px - env(safe-area-inset-bottom, 0px) - env(safe-area-inset-top, 0px)); min-height: 380px; overflow: hidden; }
.m-tabs {
  position: fixed; left: 0; right: 0; bottom: 0; z-index: 20;
  display: grid; grid-template-columns: repeat(4, minmax(0, 1fr));
  padding: 6px 4px calc(8px + env(safe-area-inset-bottom, 0px));
  background: var(--panel); border-top: 1px solid var(--line);
}
.m-tabs button {
  display: flex; flex-direction: column; align-items: center; gap: 2px; min-height: 48px;
  border: 0; background: none; color: var(--ink-2); font-size: 11.5px; cursor: pointer;
}
.m-tabs button.on { color: var(--brand); font-weight: 700; }
:root[data-theme="dark"] .m-tabs button.on { color: var(--signal-ink); }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) .m-tabs button.on { color: var(--signal-ink); } }
</style>
