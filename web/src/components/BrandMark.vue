<script setup lang="ts">
withDefaults(defineProps<{ size?: number }>(), { size: 30 })
</script>

<template>
  <!-- 标识：叶片 + 斜向探针（检测）。叶脉用稻穗金。 -->
  <svg :width="size" :height="size" viewBox="0 0 30 30" aria-hidden="true">
    <rect x="1" y="1" width="28" height="28" rx="4" fill="var(--brand)" />
    <path d="M9 21c0-7 5-12 13-12-1 8-6 12-13 12z" fill="none" stroke="var(--brand-ink)" stroke-width="1.8" stroke-linejoin="round" />
    <path d="M9 21l7-7" stroke="var(--signal)" stroke-width="1.8" stroke-linecap="round" />
  </svg>
</template>
