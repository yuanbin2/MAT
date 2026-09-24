// 跨平台的 Chromium 系浏览器探测与启动。
// 仅供截图/手动验证辅助脚本使用，不作为功能测试（功能测试见 starter/tests）。
import { existsSync } from 'node:fs'
import { chromium } from 'playwright-core'

const CANDIDATES = {
  win32: [
    'C:\\Program Files (x86)\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Microsoft\\Edge\\Application\\msedge.exe',
    'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
    'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
  ],
  darwin: [
    '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    '/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge',
  ],
  linux: [
    '/usr/bin/google-chrome',
    '/usr/bin/google-chrome-stable',
    '/usr/bin/chromium',
    '/usr/bin/chromium-browser',
    '/usr/bin/microsoft-edge',
  ],
}

export function resolveBrowserPath() {
  if (process.env.BROWSER_PATH) return process.env.BROWSER_PATH
  for (const p of CANDIDATES[process.platform] ?? []) {
    if (existsSync(p)) return p
  }
  throw new Error(
    '未找到 Chromium 系浏览器。请用环境变量 BROWSER_PATH 指定浏览器可执行文件路径。',
  )
}

export async function launch(headless = true) {
  return chromium.launch({
    executablePath: resolveBrowserPath(),
    headless,
    args: ['--no-proxy-server', '--disable-gpu'],
  })
}
