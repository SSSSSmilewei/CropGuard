// 看板快照（scripts/build_dashboard.py 生成）的类型。每个区块都可能 available=false（附 reason）。

export interface Missing { available: false; reason: string }

export interface Training {
  available: true
  source: string
  epoch: number[]
  map50: number[]
  map50_95: number[]
  precision: number[]
  recall: number[]
  train_box: number[]
  train_cls: number[]
  train_dfl: number[]
  val_box: number[]
  val_cls: number[]
  val_dfl: number[]
  best_epoch: number | null
}

export interface ClassAP { id: number; name: string; ap50: number; ap50_95: number; p: number; r: number }

export interface Validation {
  available: true
  map50: number
  map50_95: number
  precision: number
  recall: number
  classes: ClassAP[]
  num_classes: number
  train_images: number
  val_images: number
  elapsed_s: number
}

export interface SampleItem {
  no: number
  file: string
  thumb: string
  expected: string | null
  expected_cn: string | null
  pred: string | null
  pred_cn: string | null
  conf: number
  boxes: number
  ms: number
  correct: boolean
}

export interface Samples {
  available: true
  count: number
  labeled: number
  correct: number
  avg_ms: number
  total_s: number
  conf: number
  imgsz: number
  device: string
  items: SampleItem[]
}

export interface Rag {
  available: true
  in_domain_hit: number
  in_domain_total: number
  out_domain_refused: number
  out_domain_total: number
  unsafe_blocked: number
  unsafe_total: number
  threshold: number
  kb?: { chunks?: number; pests?: number; aliases?: number; vectorizer?: string }
}

export interface Tests { available: true; passed: number; failed: number; skipped: number }

export interface Snapshot {
  available: boolean
  reason?: string
  generated_at: string
  model: { weights: string; run: string; num_classes: number; imgsz: number; conf: number; device: string; chinese: Record<string, string> }
  training: Training | Missing
  validation: Validation | Missing
  samples: Samples | Missing
  rag: Rag | Missing
  tests: Tests | Missing
}

export async function fetchSnapshot(): Promise<Snapshot> {
  const r = await fetch('/api/dashboard')
  if (!r.ok) throw new Error(`服务器返回 ${r.status}`)
  return r.json()
}
