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

// 返回某月最后一天的日期字符串（YYYY-MM-DD）。
function monthEnd(year: number, month: number): string {
  const last = new Date(year, month, 0).getDate()
  return `${year}-${String(month).padStart(2, '0')}-${String(last).padStart(2, '0')}`
}

/**
 * 最近一个“完整数据月”：以数据覆盖范围的最后一天为准。
 * 若最后一天正好是当月月末，则取当月；否则退回上一个完整月。
 * 结果不会早于数据覆盖范围起点（min）。
 */
export function lastFullMonth(end: string, min: string): { start: string; end: string } {
  const [y, m] = end.split('-').map(Number)
  const lastDay = Number(monthEnd(y, m).slice(8, 10))
  const endDay = Number(end.slice(8, 10))
  let yy = y
  let mm = m
  if (endDay !== lastDay) {
    mm -= 1
    if (mm === 0) {
      mm = 12
      yy -= 1
    }
  }
  const start = `${yy}-${String(mm).padStart(2, '0')}-01`
  const finish = monthEnd(yy, mm)
  // 不早于数据覆盖起点。
  return {
    start: start < min ? min : start,
    end: finish,
  }
}
