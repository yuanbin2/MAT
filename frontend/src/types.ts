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
