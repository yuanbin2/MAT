export function formatMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  return '¥' + formatNumber(value, 2)
}

export function formatNumber(value: number, digits = 0): string {
  return value.toLocaleString('zh-CN', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })
}

export function formatQty(value: number): string {
  return formatNumber(value, 0) + ' 份'
}

export function formatOrders(value: number): string {
  return formatNumber(value, 0) + ' 单'
}

export function shortDate(date: string): string {
  return date.slice(5) // '2026-06-01' -> '06-01'
}
