export interface Store {
  store_id: string
  store_name: string
  category: string
  district: string
}

export interface MetricsSummary {
  start: string
  end: string
  store_id: string | null
  product_id: string | null
  net_revenue: number
  refund_amount: number
  orders: number
  aov: number | null
  qty: number
}

export interface DailyPoint {
  date: string
  net_revenue: number
  orders: number
  aov: number | null
}

export interface DailyMetrics {
  days: DailyPoint[]
}

export interface TopProduct {
  product_id: string
  product_name: string
  product_category: string
  net_revenue: number
  orders: number
  qty: number
}

export interface CleaningReport {
  raw_rows: number
  kept_rows: number
  kept_sales_rows: number
  kept_refund_rows: number
  removed: Record<string, number>
  normalized?: Record<string, number>
}

export interface DataQuality {
  cleaning_report: CleaningReport
  data_period: { start: string | null; end: string | null }
  kb_warnings: string[]
}

export type AnswerType = 'data' | 'doc' | 'hybrid' | 'refusal' | 'clarify'

export interface Citation {
  doc_id: string
  quote: string
}

export interface DataEvidence {
  tool?: string
  params?: Record<string, unknown>
  result?: unknown
  sql?: string
  [key: string]: unknown
}

export interface ChatResponse {
  answer: string
  answer_type: AnswerType
  citations: Citation[]
  data_evidence: DataEvidence[]
  trace_id: string
}

export interface HealthInfo {
  status: string
  llm_mode: string
  kb_docs: number
  valid_sales_rows: number
  today: string
  data_period: { start: string | null; end: string | null }
  [key: string]: unknown
}

// ---- 调试 trace（第四关）----

export interface TraceHit {
  doc_id: string
  chunk_id: string
  score: number
  padded: boolean
  kind?: string
  preview?: string
}

export interface TraceRetrieval {
  query: string
  expansions?: string[]
  coverage?: number
  as_of?: string | null
  store_id?: string | null
  year?: number | null
  window?: string[] | null
  historical?: boolean | null
  hits: TraceHit[]
  filtered?: { doc_id: string; reason: string }[]
}

export interface TraceTool {
  tool: string
  params?: Record<string, unknown>
  status: 'ok' | 'error' | 'rejected' | string
  took_ms: number | null
  accepted: boolean
  /** 采纳状态待回答定稿后核对（正常收尾后不会再出现）。 */
  pending?: boolean
  entered?: string
  reject_reason?: string
  result_bytes?: number
  result_preview?: string
  source?: string
}

export interface TraceStep {
  step: string
  at_ms: number
  took_ms: number | null
  detail?: unknown
}

export interface TraceError {
  where: string
  type: string
  message: string
  traceback?: string
}

export interface TraceLlmCall {
  endpoint?: string
  model?: string
  status?: number
  error?: string
  detail?: string
  finish_reason?: string
  took_ms?: number
  request?: string
  response?: string
  raw_content?: string
  raw_reasoning?: string
  usage?: unknown
}

export interface TracePayload {
  trace_id: string
  session_id: string | null
  question: string
  mode: string
  started_at: string
  total_ms: number
  plan: Record<string, unknown>
  retrievals: TraceRetrieval[]
  tools: TraceTool[]
  answer: {
    type?: string
    answer_preview?: string
    answer_length?: number
    citations?: { doc_id: string; quote_preview: string }[]
    evidence_count?: number
    notes?: string[]
  }
  model_called: boolean
  llm_calls: TraceLlmCall[]
  steps: TraceStep[]
  errors: TraceError[]
}
