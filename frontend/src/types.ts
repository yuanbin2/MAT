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
