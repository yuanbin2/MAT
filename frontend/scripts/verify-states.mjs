// 真实页面状态验证（可视化辅助 + 关键断言）。
// 覆盖：正常（默认最近完整月）、筛选、无数据、快速连续查询。
// 数据口径正确性由 starter/tests 的 pytest 负责，这里验证的是页面状态一致性。
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { launch } from './browser.mjs'

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const APP = process.env.APP_URL || 'http://localhost:5173/'
const API = process.env.API_URL || 'http://localhost:8001'

async function apiSummary(start, end) {
  const r = await fetch(`${API}/api/metrics/summary?start=${start}&end=${end}`)
  return r.json()
}

const shot = (name) => join(PROJECT_ROOT, 'docs', 'screenshots', name)

const browser = await launch(true)
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
const errors = []
page.on('pageerror', (e) => errors.push(e.message))

const readNet = () =>
  page.evaluate(() => document.querySelectorAll('.metric__value')[0]?.textContent.trim())
const readApplied = () =>
  page.evaluate(() => document.body.innerText.match(/当前报表区间\s*([^\n·]+)/)?.[1]?.trim())
const canvasExists = () =>
  page.evaluate(() => {
    const c = document.querySelector('.trend__chart canvas')
    return c ? c.width > 0 && c.height > 0 : false
  })

await page.goto(APP, { waitUntil: 'networkidle' })
await page.waitForTimeout(1200)

// 1) 正常态：默认最近完整月（数据到 2026-08-31 → 8 月）
console.log('--- 正常态（默认 8 月）---')
console.log('applied:', await readApplied())
console.log('canvas:', await canvasExists())
console.log('net:', await readNet())
await page.screenshot({ path: shot('normal.png') })

// 2) 筛选态：切到 7 月
const july = await apiSummary('2026-07-01', '2026-07-31')
await page.fill('input#start', '2026-07-01')
await page.fill('input#end', '2026-07-31')
await page.click('button.btn--primary')
await page.waitForTimeout(1200)
console.log('--- 筛选态（7 月）---')
console.log('applied:', await readApplied())
console.log('canvas:', await canvasExists())
console.log('net:', await readNet(), '期望', '¥' + july.net_revenue.toLocaleString('zh-CN', { minimumFractionDigits: 2 }))
await page.screenshot({ path: shot('filtered.png') })

// 3) 无数据态：切到 9 月（数据范围外）
await page.fill('input#start', '2026-09-01')
await page.fill('input#end', '2026-09-30')
await page.click('button.btn--primary')
await page.waitForTimeout(1200)
console.log('--- 无数据态（9 月）---')
console.log('applied:', await readApplied())
console.log('net:', await readNet())
console.log('top empty:', await page.evaluate(() => document.querySelector('.top__empty')?.textContent?.trim() ?? '无'))
await page.screenshot({ path: shot('empty.png') })

// 4) 快速连续查询：最后停在 6 月，最终结果应等于 6 月
const june = await apiSummary('2026-06-01', '2026-06-30')
await page.fill('input#start', '2026-07-01')
await page.fill('input#end', '2026-07-31')
await page.click('button.btn--primary')
await page.fill('input#start', '2026-08-01')
await page.fill('input#end', '2026-08-31')
await page.click('button.btn--primary')
await page.fill('input#start', '2026-06-01')
await page.fill('input#end', '2026-06-30')
await page.click('button.btn--primary')
await page.waitForTimeout(1500)
console.log('--- 快速连续查询（最终 6 月）---')
console.log('applied:', await readApplied())
console.log('net:', await readNet(), '期望', '¥' + june.net_revenue.toLocaleString('zh-CN', { minimumFractionDigits: 2 }))
await page.screenshot({ path: shot('rapid.png') })

await browser.close()
console.log('page errors:', errors.length ? errors : '无')
