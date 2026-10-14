<script setup lang="ts">
import { computed } from 'vue'
import { useTheme } from '../composables/station'
import Icon from './Icon.vue'
const { theme, cycle, label } = useTheme()
const icon = computed(() => ({ system: 'auto', light: 'sun', dark: 'moon' })[theme.value])
</script>

<template>
  <button type="button" class="theme-btn" :title="`外观：${label}（点击切换）`" :aria-label="`外观：${label}，点击切换`" @click="cycle">
    <Icon :name="icon" :size="17" />
  </button>
</template>

<style scoped>
.theme-btn {
  display: grid; place-items: center; width: 36px; height: 36px; border-radius: var(--r);
  border: 1px solid transparent; background: transparent; color: var(--ink-2); cursor: pointer;
}
.theme-btn:hover { background: var(--inset); color: var(--ink); }
</style>
