import type {
  DataQuality,
  DailyMetrics,
  MetricsSummary,
  Store,
  TopProduct,
} from './types'

const BASE = ''

async function request<T>(path: string, params?: Record<string, string | number>): Promise<T> {
  const url = new URL(BASE + path, window.location.origin)
  if (params) {
    Object.entries(params).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== '') {
        url.searchParams.set(key, String(value))
      }
    })
  }
  const resp = await fetch(url.toString())
  if (!resp.ok) {
    let detail = `HTTP ${resp.status}`
    try {
      const body = await resp.json()
      if (body && body.error) detail = body.error
    } catch {
      /* ignore */
    }
    throw new Error(detail)
  }
  return (await resp.json()) as T
}

export function fetchStores(): Promise<{ stores: Store[] }> {
  return request('/api/stores')
}

export function fetchSummary(params: {
  start: string
  end: string
  store_id?: string
}): Promise<MetricsSummary> {
  return request('/api/metrics/summary', params)
}

export function fetchDaily(params: {
  start: string
  end: string
  store_id?: string
}): Promise<DailyMetrics> {
  return request('/api/metrics/daily', params)
}

export function fetchTopProducts(params: {
  start: string
  end: string
  store_id?: string
  limit?: number
}): Promise<{ products: TopProduct[] }> {
  return request('/api/products/top', { ...params, limit: params.limit ?? 10 })
}

export function fetchDataQuality(): Promise<DataQuality> {
  return request('/api/data_quality')
}
