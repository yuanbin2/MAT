// 手动交互验证：刷新页面后 AI 助手续得上原会话（session_id + 消息记录）。
// 这是“可视化辅助”，不是自动化的功能测试——回答口径的正确性由 starter/tests 的
// pytest 与 eval/ 的题库覆盖。浏览器用 BROWSER_PATH 指定，否则按平台自动探测。
//
// 验证四件事：
//   ① 提问后 sessionStorage 里留下 session_id 与消息记录；
//   ② 刷新页面，历史消息还在（不是回到欢迎页）；
//   ③ 刷新后问「那 7 月呢？」能被补全（证明后端认出了同一个 session_id）；
//   ④ 点「新建会话」后记录被清空、回到欢迎页。
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'
import { launch } from './browser.mjs'

const APP_URL = process.env.APP_URL || 'http://localhost:5174/'

const browser = await launch(true)
const page = await browser.newPage({ viewport: { width: 1440, height: 960 } })
const results = []

function check(name, ok, detail = '') {
  results.push({ name, ok, detail })
  console.log(`${ok ? 'PASS' : 'FAIL'} ${name}${detail ? ' — ' + detail : ''}`)
}

const openAssistant = async () => {
  await page.goto(APP_URL, { waitUntil: 'networkidle' })
  // 侧栏导航是 <a>，不是 button
  await page.getByRole('link', { name: /AI\s*助手/ }).click()
  await page.waitForSelector('.chat__input')
}

const stored = (key) =>
  page.evaluate((k) => window.sessionStorage.getItem(k), key)

const ask = async (question) => {
  // 先记住现在有几轮带徽标的回答：刷新后恢复的历史会让"有徽标"立刻成立，
  // 必须等"比之前多一轮"，否则读到的是上一条回答。
  const before = await page.evaluate(
    () => document.querySelectorAll('.chat__row--bot .tag').length,
  )
  await page.fill('.chat__input', question)
  // 发送按钮在没输入时是 disabled 的，填完才会亮起来
  await page.locator('.chat__inputbar .btn--primary').click()
  await page.waitForFunction(
    (n) => document.querySelectorAll('.chat__row--bot .tag').length > n,
    before,
    { timeout: 180000 },
  )
  return page.evaluate(() => {
    const rows = [...document.querySelectorAll('.chat__row--bot')]
    const last = rows[rows.length - 1]
    return {
      type: last.querySelector('.tag')?.textContent?.trim() ?? '',
      text: last.querySelector('.chat__answer')?.textContent?.trim() ?? '',
    }
  })
}

try {
  // ① 提问并落盘
  await openAssistant()
  const first = await ask('6 月的净营业额是多少？')
  check('提问后有回答', first.type.length > 0, `类型=${first.type}`)
  const sid = await stored('moneki.chat.session_id')
  check('session_id 已写入 sessionStorage', !!sid, sid || '（空）')
  const msgs = await stored('moneki.chat.messages')
  check(
    '消息记录已写入 sessionStorage',
    !!msgs && msgs.includes('156') && msgs.includes('assistant'),
    `共 ${msgs ? JSON.parse(msgs).length : 0} 条`,
  )

  // ② 刷新后续上
  await page.reload({ waitUntil: 'networkidle' })
  await page.getByRole('link', { name: /AI\s*助手/ }).click()
  await page.waitForSelector('.chat__input')
  const restored = await page.evaluate(() => ({
    rows: document.querySelectorAll('.chat__row').length,
    hasWelcome: !!document.querySelector('.chat__welcome'),
    sid: window.sessionStorage.getItem('moneki.chat.session_id'),
  }))
  check('刷新后历史消息仍在', restored.rows >= 2 && !restored.hasWelcome, `${restored.rows} 条气泡`)
  check('刷新后 session_id 不变', restored.sid === sid, restored.sid || '（空）')

  // ③ 刷新后追问能被补全（后端认得出这是同一段对话）
  const follow = await ask('那 7 月呢？')
  const resolved = follow.text.includes('7 月') && !follow.text.includes('没有上文')
  check('刷新后追问被补全', resolved, follow.text.slice(0, 60))

  // ④ 新建会话清空记录
  await page.getByRole('button', { name: '新建会话' }).click()
  await page.waitForFunction(() => !!document.querySelector('.chat__welcome'), { timeout: 10000 })
  const afterNew = await page.evaluate(() => ({
    hasWelcome: !!document.querySelector('.chat__welcome'),
    sid: window.sessionStorage.getItem('moneki.chat.session_id'),
    msgs: window.sessionStorage.getItem('moneki.chat.messages'),
  }))
  check(
    '新建会话后回到欢迎页且记录清空',
    afterNew.hasWelcome && !afterNew.sid && !afterNew.msgs,
    `sid=${afterNew.sid} msgs=${afterNew.msgs}`,
  )
} catch (e) {
  check('脚本执行', false, `${e?.name ?? 'Error'}: ${e?.message ?? e}`)
} finally {
  await browser.close()
}

const failed = results.filter((r) => !r.ok)
console.log(`\n${results.length - failed.length}/${results.length} 项通过`)
process.exit(failed.length ? 1 : 0)
