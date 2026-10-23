<script setup lang="ts">
import { useToasts } from '../composables/station'
import Icon from './Icon.vue'
const toasts = useToasts()
</script>

<template>
  <div class="toasts" role="status" aria-live="polite">
    <TransitionGroup name="toast">
      <div v-for="t in toasts" :key="t.id" class="toast" :class="t.tone">
        <Icon :name="t.tone === 'ok' ? 'check' : 'info'" :size="16" />
        <span>{{ t.text }}</span>
      </div>
    </TransitionGroup>
  </div>
</template>

<style scoped>
.toasts {
  position: fixed; z-index: 60; left: 50%; transform: translateX(-50%);
  bottom: calc(24px + env(safe-area-inset-bottom, 0px));
  display: flex; flex-direction: column; align-items: center; gap: 8px;
  width: max-content; max-width: calc(100vw - 32px); pointer-events: none;
}
.toast {
  display: flex; align-items: center; gap: 8px; padding: 10px 14px; border-radius: var(--r);
  background: var(--ink); color: var(--panel); font-size: 13px;
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.25);
}
.toast.bad { background: var(--risk-high); color: #fff; }
.toast.warn { background: var(--warn-ink); color: #fff; }
.toast-enter-active, .toast-leave-active { transition: opacity .2s, transform .2s; }
.toast-enter-from, .toast-leave-to { opacity: 0; transform: translateY(8px); }
</style>
