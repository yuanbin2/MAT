// 用系统 Edge（Chromium）给看板截图，供 DEMO/README 使用。
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import puppeteer from 'puppeteer-core'

const EDGE =
  'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const url = process.argv[2] || 'http://localhost:5173/'
const out = process.argv[3] || 'E:\\Desktop\\MyProject\\MAT\\moneki-ai-takehome\\docs\\screenshots\\dashboard.png'

const browser = await puppeteer.launch({
  executablePath: EDGE,
  headless: 'new',
  // 独立临时 profile：Edge 已有实例在跑时，复用默认 profile 会直接退出。
  userDataDir: mkdtempSync(join(tmpdir(), 'edge-shot-')),
  args: ['--no-proxy-server', '--disable-gpu', '--hide-scrollbars'],
})

const page = await browser.newPage()
await page.setViewport({ width: 1440, height: 960, deviceScaleFactor: 2 })

const errors = []
page.on('pageerror', (e) => errors.push('pageerror: ' + e.message))
page.on('console', (m) => {
  if (m.type() === 'error') errors.push('console: ' + m.text())
})

await page.goto(url, { waitUntil: 'networkidle0', timeout: 30000 })
// 等一帧，确保图表动画与数据渲染完成。
await new Promise((r) => setTimeout(r, 1500))

await page.screenshot({ path: out, fullPage: false })
await browser.close()

console.log('screenshot saved:', out)
if (errors.length) {
  console.log('page errors:')
  errors.forEach((e) => console.log('  ' + e))
}
