// 服务器相机的实时画面：`/ws/stream` 的连接、断线重连、消息解析都收在这里。
//
// 为什么单独抽出来：/stream（实时监测·自动喷洒）和检测台的「摄像头」输入用的是
// **同一路相机、同一个 WS 协议**（推原始帧 + 检测框 + 相机状态）。以前只有 /stream 有，
// 现在两处共用一份实现，不会出现"一个页面能重连、另一个卡死"的漂移。
import { onBeforeUnmount, ref, watch, type Ref } from 'vue'
import { wsUrl, type CameraState, type Detection, type Risk } from './../lib/api'
import { sortByConf } from './../lib/format'

export interface StreamMsg {
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

export interface LiveStreamOptions {
  /** 片区 id（多路监测时选相机）；不传就是默认相机 */
  zone?: Ref<string>
  /** 每条有效消息都会回调（时间线、联动记录等页面自己的逻辑） */
  onResult?: (d: StreamMsg) => void
  /** 立即连接（默认 true；实时监测页会先等 zones 就绪再连） */
  autoConnect?: boolean
}

function b64ToBlob(b64: string) {
  const bin = atob(b64)
  const buf = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) buf[i] = bin.charCodeAt(i)
  return new Blob([buf], { type: 'image/jpeg' })
}

export function useLiveStream(opts: LiveStreamOptions = {}) {
  const conn = ref<'wait' | 'on' | 'off' | 'error'>('wait')
  const frameUrl = ref<string | null>(null)
  /** 原始帧（抓拍用）：WS 推的是不带框的原始 JPEG */
  const frameBlob = ref<Blob | null>(null)
  const size = ref<[number, number]>([1280, 720])
  const dets = ref<Detection[]>([])
  const risk = ref<Risk | null>(null)
  const cam = ref<CameraState | null>(null)
  const age = ref<number | null>(null)
  const errorMsg = ref('')
  const warnMsg = ref('')

  let ws: WebSocket | null = null
  let gen = 0
  let retryT = 0
  let objUrl: string | null = null

  function applyFrame(b64: string) {
    if (objUrl) URL.revokeObjectURL(objUrl)
    const blob = b64ToBlob(b64)
    frameBlob.value = blob
    objUrl = URL.createObjectURL(blob)
    frameUrl.value = objUrl
  }

  function onMsg(d: StreamMsg) {
    if (d.error) {
      errorMsg.value = d.error
      cam.value = d.camera || cam.value
      conn.value = 'error'
      frameUrl.value = null
      frameBlob.value = null
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
    if (d.result_image) applyFrame(d.result_image)
    if (d.image_size) size.value = d.image_size
    else if (d.camera?.size) {
      const [w, h] = d.camera.size.split('x').map(Number)
      if (w && h) size.value = [w, h]
    }
    dets.value = sortByConf(d.detections || [])
    risk.value = d.risk || null
    cam.value = d.camera || null
    age.value = d.result_age ?? null
    opts.onResult?.(d)
  }

  function connect() {
    gen += 1
    const my = gen
    window.clearTimeout(retryT)
    if (ws) { ws.onclose = null; try { ws.close() } catch { /* 已关闭 */ } }
    conn.value = 'wait'
    errorMsg.value = ''
    const zone = opts.zone?.value || ''
    ws = new WebSocket(wsUrl('/ws/stream' + (zone ? `?cam=${encodeURIComponent(zone)}` : '')))
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

  function disconnect() {
    gen += 1
    window.clearTimeout(retryT)
    if (ws) { ws.onclose = null; try { ws.close() } catch { /* 已关闭 */ } ws = null }
    conn.value = 'off'
  }

  function onVisibility() {
    if (document.hidden) disconnect()
    else connect()
  }

  if (opts.zone) {
    watch(opts.zone, () => connect())
  }
  if (opts.autoConnect !== false) connect()
  document.addEventListener('visibilitychange', onVisibility)
  onBeforeUnmount(() => {
    disconnect()
    if (objUrl) URL.revokeObjectURL(objUrl)
    document.removeEventListener('visibilitychange', onVisibility)
  })

  return { conn, frameUrl, frameBlob, size, dets, risk, cam, age, errorMsg, warnMsg, connect, disconnect }
}
