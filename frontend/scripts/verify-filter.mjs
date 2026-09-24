// 手动交互验证：切日期点查询后，趋势图 canvas 仍在、卡片数值更新。
// 这是“可视化辅助”，不是自动化的功能测试——数据口径的正确性由 starter/tests 的
// pytest 覆盖。浏览器用 BROWSER_PATH 指定，否则按平台自动探测。
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { launch } from './browser.mjs'

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const APP_URL = process.env.APP_URL || 'http://localhost:5173/'
const OUT =
  process.argv[2] ||
  process.env.SCREENSHOT_OUT ||
  join(PROJECT_ROOT, 'docs', 'screenshots', 'filtered.png')

const browser = await launch(true)
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
await page.goto(APP_URL, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

const canvasOf = () =>
  page.evaluate(() => {
    const c = document.querySelector('.trend__chart canvas')
    return c ? { w: c.width, h: c.height } : null
  })

const before = await canvasOf()

await page.fill('input#start', '2026-07-01')
await page.fill('input#end', '2026-07-31')
await page.click('button.btn--primary')
await page.waitForTimeout(2000)

const after = await canvasOf()
const net = await page.evaluate(() => {
  const cards = document.querySelectorAll('.metric__value')
  return cards.length ? cards[0].textContent.trim() : null
})

console.log('initial canvas:', JSON.stringify(before))
console.log('after filter canvas:', JSON.stringify(after))
console.log('净营业额卡片:', net)

await page.screenshot({ path: OUT })
await browser.close()
console.log('screenshot:', OUT)

// 关键断言：切换后 canvas 仍在（否则就是“切换日期趋势图消失”的回归）。
if (!after || after.w === 0 || after.h === 0) {
  console.error('FAIL: 切换日期后趋势图 canvas 丢失')
  process.exitCode = 1
}
