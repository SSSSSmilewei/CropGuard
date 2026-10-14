// 后端接口的类型与请求封装。接口一律同源调用：HTTP(8080) 与 HTTPS(8443) 共用同一个 app，
// https 页面跨协议调 http 接口会被手机浏览器按"混合内容"拦截。

export type RiskLevel = '高风险' | '中风险' | '低风险' | '无风险'

export interface Detection {
  class_name: string
  chinese_name: string
  confidence: number
  bbox: [number, number, number, number]
}

export interface Risk {
  level: RiskLevel | string
  detail: string
}

export interface DetectResult {
  success: boolean
  count: number
  detections: Detection[]
  risk: Risk
  inference_time: number
  result_image: string
  timestamp: string
  advice?: string
  advice_source?: string
  error?: string
}

export interface Health {
  status: string
  model_loaded: boolean
  classes: number
  device: string
}

export interface ClientConfig {
  http_port: number
  https_port: number | null
  frame_interval_ms: number
  upload_max_side: number
  conf_default: number
  imgsz: number
  model: string
  max_spray: number
  eval_target: number
  eval_time_limit: number
  refuse_below: number
  risk_map: Record<string, { group: string | null; duration: number }>
}

export interface SprayNode {
  group: string
  name?: string
  url: string
  online: boolean
  latency_ms?: number | null
  rssi?: number | null
  ip?: string
  spraying?: boolean
  count?: number
  error?: string
}

export interface SprayStatus {
  success: boolean
  available: boolean
  transport: string
  groups: string[]
  max_duration: number
  zones: { id: string; name: string; group: string }[]
  nodes: SprayNode[]
}

export interface HistoryItem {
  ts: string
  source: string
  via: string
  risk: string
  group: string | null
  duration: number | null
  detections: string[]
}

export interface Citation {
  id?: string
  title: string
  score?: number
  source?: string
}

export interface AskResult {
  success: boolean
  answer: string
  source: 'llm' | 'knowledge_base' | 'refused' | 'error' | string
  citations?: Citation[]
  engine?: string
  elapsed?: number
  guard?: { unsupported?: string[]; dosage_unsupported?: string[] }
  error?: string
}

export interface KbChunk {
  id: string
  title: string
  type: string
  cn: string
  score: number
  raw_score: number
  gate_score: number
  text: string
  source: string
}

export interface KbSearch {
  success: boolean
  question: string
  rewritten: string
  detected_pests: string[]
  refuse_below: number
  gate_score: number
  will_refuse: boolean
  chunks: KbChunk[]
  stats: { chunks: number; pests: number; aliases: number; vectorizer: string }
}

export interface CommandParse {
  success: boolean
  intent: 'spray' | 'stop' | string | null
  group: string | null
  duration: number | null
  valid: boolean
  needs_confirm?: boolean
  max_duration: number
  reason: string
  reply: string
  executed: boolean
  available: boolean
}

export interface CameraState {
  name?: string
  device?: string | null
  state?: string
  ok?: boolean
  fps?: number | null
  size?: string | null
  frame_age?: number | null
  reopens?: number
  hard_reopens?: number
  last_error?: string | null
}

export interface FeedbackStatus {
  success: boolean
  feedback: {
    enabled?: boolean
    serial?: boolean
    tts?: { enabled?: boolean; engine?: string | null; ready?: boolean; spoken?: number; failed?: number; init_errors?: string[] }
  }
}

export interface LanInfo {
  hosts: string[]
  http_port: number
  https_port: number
  phone_urls: string[]
  phone_urls_https: string[]
}

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response
  try {
    res = await fetch(path, init)
  } catch {
    throw new ApiError('连不上服务器，检查本机服务是否在运行、手机是否与电脑在同一网络', 0)
  }
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    /* 非 JSON 响应 */
  }
  if (!res.ok) {
    const d = (data || {}) as { detail?: unknown; error?: unknown }
    const msg = d.detail ?? d.error ?? `服务器返回 ${res.status}`
    throw new ApiError(typeof msg === 'string' ? msg : JSON.stringify(msg), res.status)
  }
  return (data ?? {}) as T
}

const postJSON = <T>(path: string, body: unknown) =>
  request<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })

export const api = {
  health: () => request<Health>('/api/health'),
  clientConfig: () => request<ClientConfig>('/api/client_config'),
  feedback: () => request<FeedbackStatus>('/api/feedback/status'),
  lan: () => request<LanInfo>('/api/lan'),
  history: () => request<{ history: HistoryItem[] }>('/api/history'),
  sprayStatus: () => request<SprayStatus>('/api/spray/status'),
  cameraHealth: () => request<{ success: boolean; pool: Record<string, CameraState>; camera_num: number; configured_zones: string[] }>('/api/camera/health'),

  detect(file: Blob, conf?: number, filename = 'upload.jpg') {
    const form = new FormData()
    form.append('file', file, filename)
    if (conf != null) form.append('conf', String(conf))
    return request<DetectResult>('/api/detect', { method: 'POST', body: form })
  },
  advice: (detections: Detection[], risk: Risk) =>
    postJSON<AskResult & { advice: string }>('/api/advice', { detections, risk }),
  ask: (question: string, history: { role: string; content: string }[], context: unknown) =>
    postJSON<AskResult>('/api/ask', { question, history, context }),
  kbSearch: (q: string) => request<KbSearch>(`/api/kb/search?q=${encodeURIComponent(q)}`),
  parseCommand: (text: string, execute = false) =>
    postJSON<CommandParse>('/api/ask_command', { text, execute }),
  spray: (group: string, duration: number, via: string) =>
    postJSON<{ success: boolean; delivered?: boolean; group: string; duration: number; reason?: string }>(
      '/api/spray', { group, duration, via }),
  stop: (group: string, via: string) =>
    postJSON<{ success: boolean; group: string }>('/api/spray/stop', { group, via }),
  restartCamera: (cam: string | null) =>
    postJSON<{ success: boolean; state: CameraState }>('/api/camera/restart', { cam }),
}

export function wsUrl(path: string) {
  const proto = location.protocol === 'https:' ? 'wss://' : 'ws://'
  return proto + location.host + path
}
