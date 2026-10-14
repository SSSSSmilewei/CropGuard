<script setup lang="ts">
import { computed } from 'vue'
import { useRoute } from 'vue-router'
import AppHeader from './components/AppHeader.vue'
import ToastHost from './components/ToastHost.vue'

const route = useRoute()
const mobile = computed(() => !!route.meta.mobile)
</script>

<template>
  <AppHeader v-if="!mobile" />
  <RouterView />
  <ToastHost />
</template>
