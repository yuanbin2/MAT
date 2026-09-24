// 给看板截图（可视化辅助，非功能测试）。
// 用法：node scripts/screenshot.mjs [url] [out]
// 浏览器用 BROWSER_PATH 指定，否则按平台自动探测；输出路径默认写到仓库 docs/screenshots。
import { fileURLToPath } from 'node:url'
import { dirname, join, resolve } from 'node:path'
import { launch } from './browser.mjs'

const PROJECT_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..', '..')
const url = process.argv[2] || process.env.APP_URL || 'http://localhost:5173/'
const out =
  process.argv[3] ||
  process.env.SCREENSHOT_OUT ||
  join(PROJECT_ROOT, 'docs', 'screenshots', 'dashboard.png')

const browser = await launch(true)
const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 960, deviceScaleFactor: 2 })

const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('console: ' + m.text())
})

await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 })
await new Promise((r) => setTimeout(r, 1500))

await page.screenshot({ path: out, fullPage: false })
await browser.close()

console.log('screenshot saved:', out)
if (errors.length) {
  console.log('page errors:')
  errors.forEach((e) => console.log('  ' + e))
  process.exitCode = 1
}
