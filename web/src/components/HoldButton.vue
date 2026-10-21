<script setup lang="ts">
// 按住确认：按住 hold 毫秒才触发（喷淋这类不可撤销的动作，防误触）。
// 键盘：聚焦后按住空格/回车同样有效。松手即取消。
import { onBeforeUnmount, ref } from 'vue'

const props = withDefaults(defineProps<{ hold?: number; disabled?: boolean; tone?: 'brand' | 'danger' }>(), {
  hold: 1000, disabled: false, tone: 'brand',
})
const emit = defineEmits<{ (e: 'fire'): void }>()
const progress = ref(0)
let raf = 0
let t0 = 0

function tick(now: number) {
  progress.value = Math.min(1, (now - t0) / props.hold)
  if (progress.value >= 1) {
    cancel()
    emit('fire')
    return
  }
  raf = requestAnimationFrame(tick)
}
function start(e?: PointerEvent) {
  if (props.disabled || raf) return
  if (e && e.button !== 0) return
  t0 = performance.now()
  raf = requestAnimationFrame(tick)
}
function cancel() {
  cancelAnimationFrame(raf)
  raf = 0
  progress.value = 0
}
function onKey(e: KeyboardEvent, down: boolean) {
  if (e.key !== ' ' && e.key !== 'Enter') return
  e.preventDefault()
  if (down && !e.repeat) start()
  if (!down) cancel()
}
onBeforeUnmount(cancel)
</script>

<template>
  <button
    type="button"
    class="hold btn btn-lg btn-block"
    :class="tone === 'danger' ? 'btn-danger' : 'btn-primary'"
    :disabled="disabled"
    @pointerdown="start"
    @pointerup="cancel"
    @pointerleave="cancel"
    @pointercancel="cancel"
    @keydown="onKey($event, true)"
    @keyup="onKey($event, false)"
    @contextmenu.prevent
  >
    <span class="fill" :style="{ transform: `scaleX(${progress})` }" />
    <span class="txt"><slot /></span>
  </button>
</template>

<style scoped>
.hold { position: relative; overflow: hidden; touch-action: none; user-select: none; -webkit-user-select: none; }
.fill {
  position: absolute; inset: 0; transform-origin: left center; transform: scaleX(0);
  background: rgba(255, 255, 255, 0.24);
}
.txt { position: relative; }
</style>
