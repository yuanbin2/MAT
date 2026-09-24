import { chromium } from 'playwright-core'

const EDGE = 'C://Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe'
const OUT = process.argv[2] || 'E://Desktop//MyProject//MAT//moneki-ai-takehome//docs//screenshots//filtered.png'

const browser = await chromium.launch({
  executablePath: EDGE,
  headless: true,
  args: ['--no-proxy-server', '--disable-gpu'],
})
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
await page.goto('http://localhost:5173/', { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

// 记下初始趋势图容器里是否有 canvas
const before = await page.evaluate(() => {
  const c = document.querySelector('.trend__chart canvas')
  return c ? { w: c.width, h: c.height } : null
})

// 切换日期范围：把开始日期改成 2026-07-01，结束日期 2026-07-31，点查询
await page.fill('input#start', '2026-07-01')
await page.fill('input#end', '2026-07-31')
await page.click('button.btn--primary')
await page.waitForTimeout(2000)

const after = await page.evaluate(() => {
  const c = document.querySelector('.trend__chart canvas')
  return c ? { w: c.width, h: c.height } : null
})

// 顺带读取切换后的净营业额卡片，验证数据确实更新了
const net = await page.evaluate(() => {
  const cards = document.querySelectorAll('.metric__value')
  return cards.length ? cards[0].textContent.trim() : null
})

console.log('initial canvas:', JSON.stringify(before))
console.log('after filter canvas:', JSON.stringify(after))
console.log('净营业额卡片(应≈¥129,510 或该区间值):', net)

await page.screenshot({ path: OUT })
await browser.close()
console.log('screenshot:', OUT)
