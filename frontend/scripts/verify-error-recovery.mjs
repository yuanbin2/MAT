// 用路由拦截模拟接口失败，验证首屏失败后的恢复流程。
// 1) 元数据接口失败 → 结束加载态 + 指明失败 + 重试拉元数据
// 2) 取消拦截点重试 → 元数据恢复后自动加载指标
// 3) 指标接口失败 → 保留旧结果 + 标注旧条件 + 重试
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { launch } from './browser.mjs'

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const APP = process.env.APP_URL || 'http://localhost:5173/'
const shot = (name) => join(PROJECT_ROOT, 'docs', 'screenshots', name)

const browser = await launch(true)
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })

const readError = () => page.evaluate(() => document.querySelector('.error-banner')?.textContent?.trim() ?? null)
const readNet = () => page.evaluate(() => document.querySelectorAll('.metric__value')[0]?.textContent?.trim())
const skeletonGone = () => page.evaluate(() => document.querySelectorAll('.skeleton').length === 0)

// 1) 元数据接口失败
await page.route('**/api/stores', (r) => r.abort('failed'))
await page.route('**/api/data_quality', (r) => r.abort('failed'))
await page.goto(APP, { waitUntil: 'networkidle' })
await page.waitForTimeout(800)
console.log('--- 元数据失败 ---')
console.log('error:', await readError())
console.log('骨架屏已消失:', await skeletonGone())
await page.screenshot({ path: shot('error-meta.png') })

// 2) 取消拦截，点重试恢复
await page.unroute('**/api/stores')
await page.unroute('**/api/data_quality')
const retryBtn = page.locator('.error-banner button', { hasText: '重试' })
await retryBtn.click()
await page.waitForTimeout(1500)
console.log('--- 重试后恢复 ---')
console.log('error 已消失:', (await readError()) === null)
console.log('net:', await readNet())
await page.screenshot({ path: shot('recovered-meta.png') })

// 3) 指标接口失败（元数据正常），保留旧结果并标注旧条件
// 注意：metrics 请求带 query string，glob 里 `?` 是通配符，须用 `*` 后缀匹配。
await page.route('**/api/metrics/summary*', (r) => r.abort('failed'))
await page.route('**/api/metrics/daily*', (r) => r.abort('failed'))
await page.route('**/api/products/top*', (r) => r.abort('failed'))
const oldNet = await readNet()
await page.fill('input#start', '2026-06-01')
await page.fill('input#end', '2026-06-30')
await page.click('button.btn--primary')
await page.waitForTimeout(800)
console.log('--- 指标失败（保留旧结果）---')
console.log('error:', await readError())
console.log('net 仍是旧值:', (await readNet()) === oldNet, '=', await readNet())
await page.screenshot({ path: shot('error-metrics.png') })

await browser.close()
