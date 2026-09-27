<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { fetchChat, fetchHealth } from '../api'
import type { AnswerType, Citation, DataEvidence, HealthInfo } from '../types'
import RichText from './RichText.vue'
import TracePanel from './TracePanel.vue'

type MsgState = 'ok' | 'loading' | 'error'

interface Message {
  id: string
  role: 'user' | 'assistant'
  text: string
  question?: string
  answerType?: AnswerType
  citations: Citation[]
  evidence: DataEvidence[]
  traceId?: string
  state: MsgState
  error?: string
}

const ANSWER_LABELS: Record<AnswerType, string> = {
  data: '数据',
  doc: '文档',
  hybrid: '数据 + 文档',
  refusal: '无法回答',
  clarify: '请补充',
}

const EXAMPLES = [
  '7 月整体的净营业额是多少？',
  '外卖订单多久内可以申请退款？',
  '会员现在单笔充值满 500 送多少？',
  'S03 六月停业几天，什么原因？',
]

const messages = ref<Message[]>([])
const input = ref('')
const sending = ref(false)
const sessionId = ref('')
const mode = ref<'live' | 'mock' | 'unknown'>('unknown')
const healthError = ref('')
const expanded = ref<Record<string, boolean>>({})

// 调试面板
const debugOpen = ref(false)
const debugTraceId = ref('')

function openTrace(traceId: string) {
  debugTraceId.value = traceId
  debugOpen.value = true
}

function openDebugLookup() {
  debugTraceId.value = ''
  debugOpen.value = true
}

const inputEl = ref<HTMLTextAreaElement | null>(null)

function newSessionId(): string {
  if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') {
    return crypto.randomUUID()
  }
  return 's-' + Date.now().toString(36) + '-' + Math.random().toString(36).slice(2, 10)
}

let seq = 0

function nextId(prefix: string): string {
  seq += 1
  return `${prefix}-${Date.now().toString(36)}-${seq}`
}

const canSend = computed(
  () => input.value.trim().length > 0 && !sending.value,
)

function scrollToBottom() {
  nextTick(() => {
    const box = document.querySelector('.chat__scroll')
    if (box) box.scrollTop = box.scrollHeight
  })
}

async function send(questionOverride?: string) {
  const question = (questionOverride ?? input.value).trim()
  if (!question || sending.value) return

  input.value = ''
  sending.value = true

  const userMsg: Message = {
    id: nextId('u'),
    role: 'user',
    text: question,
    question,
    citations: [],
    evidence: [],
    state: 'ok',
  }
  const assistantMsg: Message = {
    id: nextId('a'),
    role: 'assistant',
    text: '正在分析…',
    question,
    citations: [],
    evidence: [],
    state: 'loading',
  }
  messages.value.push(userMsg, assistantMsg)
  scrollToBottom()

  try {
    const resp = await fetchChat(sessionId.value, question)
    assistantMsg.text = resp.answer
    assistantMsg.answerType = resp.answer_type
    assistantMsg.citations = resp.citations ?? []
    assistantMsg.evidence = resp.data_evidence ?? []
    assistantMsg.traceId = resp.trace_id
    assistantMsg.state = 'ok'
  } catch (e) {
    assistantMsg.state = 'error'
    assistantMsg.error = (e as Error).message || '网络请求失败'
    assistantMsg.text = ''
  } finally {
    sending.value = false
    scrollToBottom()
    // 回答是直接改消息对象的属性落定的，那种赋值不会触发 deep watch，
    // 所以这里显式存一次：刷新后要能连回答一起恢复。
    persistMessages()
  }
}

function retry(msg: Message) {
  if (!msg.question || sending.value) return
  // 移除当前 assistant 消息，重发同一问题。
  const idx = messages.value.findIndex((m) => m.id === msg.id)
  if (idx >= 0) messages.value.splice(idx, 1)
  send(msg.question)
}

function newChat() {
  sessionId.value = newSessionId()
  messages.value = []
  expanded.value = {}
  input.value = ''
  // 「新建会话」是真的开新会话：把续聊用的标识与记录一起清掉。
  writeStored(SESSION_KEY, null)
  writeStored(MESSAGES_KEY, null)
  inputEl.value?.focus()
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    send()
  }
}

function toggle(id: string) {
  expanded.value[id] = !expanded.value[id]
}

function resultPreview(result: unknown): { text: string; truncated: boolean } {
  let text = ''
  try {
    text = typeof result === 'string' ? result : JSON.stringify(result, null, 2)
  } catch {
    text = String(result)
  }
  if (text.length > 420) {
    return { text: text.slice(0, 420) + '…', truncated: true }
  }
  return { text, truncated: false }
}

function paramLabel(params: Record<string, unknown> | undefined): string {
  if (!params) return ''
  const parts: string[] = []
  if (params.start || params.end) parts.push(`${params.start ?? ''} ~ ${params.end ?? ''}`)
  if (params.store_id) parts.push(`门店 ${params.store_id}`)
  if (params.product_id) parts.push(`商品 ${params.product_id}`)
  return parts.join(' · ')
}

async function loadHealth() {
  try {
    const h: HealthInfo = await fetchHealth()
    mode.value = h.llm_mode === 'live' ? 'live' : 'mock'
  } catch (e) {
    healthError.value = (e as Error).message || '无法获取服务状态'
    mode.value = 'unknown'
  }
}

// -- 刷新后续聊 -----------------------------------------------------------------
// 会话标识与消息记录放在 sessionStorage（按标签页隔离，不与其它标签页的对话串）。
// 后端 SessionStore 是进程内存、重启即失效，所以这里只保证"刷新/重开这个标签页"续得上；
// 存不进去（隐私模式、超额）时静默降级成原来的行为，不影响问答本身。

const SESSION_KEY = 'moneki.chat.session_id'
const MESSAGES_KEY = 'moneki.chat.messages'

function readStored<T>(key: string): T | null {
  try {
    const raw = window.sessionStorage.getItem(key)
    return raw ? (JSON.parse(raw) as T) : null
  } catch {
    return null
  }
}

function writeStored(key: string, value: unknown): void {
  try {
    if (value === null || value === undefined) {
      window.sessionStorage.removeItem(key)
      return
    }
    window.sessionStorage.setItem(key, JSON.stringify(value))
  } catch {
    /* 存不下就算了：续聊是增强，不是前提 */
  }
}

function persistMessages(): void {
  // 进行中的那条不落盘：刷新后它不可能真的还在跑，恢复了会显示一条没有下文的回答。
  const list = messages.value.filter((m) => m.state !== 'loading')
  // 空列表直接移除键：watch 的 flush 比 newChat() 里的清空晚一步，
  // 若不在这里收口，会把一个空的 "[]" 又写回来。
  writeStored(MESSAGES_KEY, list.length ? list : null)
}

// 数组本身的变更（push/splice）走 deep watch；回答属性的落定在 send() 里显式调
// persistMessages()——直接给消息对象赋值不会触发 watch，这点容易漏。
watch(messages, persistMessages, { deep: true })

onMounted(() => {
  // 优先接着上一段聊：同一个标签页刷新后 session_id 不变，后端才认得出"那 7 月呢"。
  const stored = readStored<string>(SESSION_KEY)
  sessionId.value = stored || newSessionId()
  writeStored(SESSION_KEY, sessionId.value)
  const storedMessages = readStored<Message[]>(MESSAGES_KEY)
  if (Array.isArray(storedMessages) && storedMessages.length) {
    messages.value = storedMessages
    scrollToBottom()
  }
  loadHealth()
})
</script>

<template>
  <div class="chat">
    <!-- 状态条：说明回答范围与当前模型模式 -->
    <div class="chat__bar">
      <p class="chat__scope">
        回答基于数据库实绩与公司知识库，附数据依据与文档来源；对话范围不受看板筛选影响。
      </p>
      <div class="chat__bar-side">
        <button class="chat__text-btn" @click="openDebugLookup">调试记录</button>
        <span class="chat__mode" :class="`chat__mode--${mode}`">
          <span class="chat__mode-dot" aria-hidden="true"></span>
          <template v-if="mode === 'live'">已接入大模型 · 在线</template>
          <template v-else-if="mode === 'mock'">本地演示 · 降级模式（未配置模型 Key）</template>
          <template v-else>{{ healthError || '服务状态未知' }}</template>
        </span>
      </div>
    </div>

    <div class="chat__body">
      <div class="chat__scroll" v-if="messages.length">
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="chat__row"
          :class="msg.role === 'user' ? 'chat__row--user' : 'chat__row--bot'"
        >
          <!-- 用户消息：深松绿气泡 -->
          <template v-if="msg.role === 'user'">
            <div class="chat__bubble chat__bubble--user">
              <div class="chat__q">{{ msg.text }}</div>
            </div>
          </template>

          <!-- 加载中 -->
          <template v-else-if="msg.state === 'loading'">
            <div class="chat__avatar serif" aria-hidden="true">M</div>
            <div class="chat__bubble chat__bubble--bot">
              <div class="chat__analyzing">正在分析<span class="chat__dots">…</span></div>
            </div>
          </template>

          <!-- 请求失败 -->
          <template v-else-if="msg.state === 'error'">
            <div class="chat__avatar serif" aria-hidden="true">M</div>
            <div class="chat__bubble chat__bubble--bot">
              <div class="chat__err">
                <div class="chat__err-title">请求失败</div>
                <div class="chat__err-detail">{{ msg.error }}</div>
                <button class="chat__retry" @click="retry(msg)">重试</button>
              </div>
            </div>
          </template>

          <!-- 回答 -->
          <template v-else>
            <div class="chat__avatar serif" aria-hidden="true">M</div>
            <div class="chat__bubble chat__bubble--bot">
              <div class="chat__answer"><RichText :text="msg.text" /></div>

              <div class="chat__meta" v-if="msg.answerType">
                <span class="tag" :class="`tag--${msg.answerType}`">
                  {{ ANSWER_LABELS[msg.answerType] }}
                </span>
                <button
                  v-if="msg.traceId"
                  class="chat__text-btn chat__trace-link"
                  @click="openTrace(msg.traceId)"
                >
                  查看调试记录
                </button>
              </div>

              <div
                v-if="msg.citations.length || msg.evidence.length"
                class="chat__evidence"
              >
                <button class="chat__toggle" @click="toggle(msg.id)">
                  {{ expanded[msg.id] ? '收起依据' : '查看数据依据 / 文档来源' }}
                  <span class="chat__counts">
                    <template v-if="msg.evidence.length">{{ msg.evidence.length }} 项数据</template>
                    <template v-if="msg.citations.length"> · {{ msg.citations.length }} 篇文档</template>
                  </span>
                </button>

                <div v-if="expanded[msg.id]" class="chat__evidence-body">
                  <div v-for="(c, i) in msg.citations" :key="'c' + i" class="chat__doc">
                    <div class="chat__doc-id num">{{ c.doc_id }}</div>
                    <div class="chat__doc-quote">{{ c.quote }}</div>
                  </div>

                  <div v-for="(ev, i) in msg.evidence" :key="'e' + i" class="chat__data">
                    <div class="chat__data-head">
                      <span class="chat__data-tool">{{ ev.tool || 'SQL' }}</span>
                      <span class="chat__data-scope">{{ paramLabel(ev.params as Record<string, unknown>) }}</span>
                    </div>
                    <pre class="chat__data-result">{{ resultPreview(ev.result).text }}</pre>
                    <div v-if="resultPreview(ev.result).truncated" class="chat__data-note">
                      结果过长，已截断展示（完整数值以接口返回为准）
                    </div>
                  </div>

                  <div v-if="!msg.citations.length && !msg.evidence.length" class="chat__empty">
                    本条回答没有可展示的数据依据或文档来源。
                  </div>
                </div>
              </div>

              <div
                v-if="!msg.citations.length && !msg.evidence.length && msg.answerType === 'refusal'"
                class="chat__nosource"
              >
                无可用来源
              </div>
            </div>
          </template>
        </div>
      </div>

      <!-- 空状态：给出可点的示例问题 -->
      <div v-else class="chat__welcome">
        <div class="chat__welcome-title">有什么想了解的？</div>
        <div class="chat__welcome-desc">可以问经营数字、制度规定，也可以把两者合起来问。</div>
        <div class="chat__examples">
          <button
            v-for="q in EXAMPLES"
            :key="q"
            class="chat__example"
            @click="input = q"
          >
            <span class="chat__example-icon" aria-hidden="true">
              <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                <circle cx="9" cy="9" r="5.5" />
                <path d="m13.2 13.2 3.3 3.3" />
              </svg>
            </span>
            {{ q }}
          </button>
        </div>
      </div>
    </div>

    <div class="chat__inputbar">
      <textarea
        ref="inputEl"
        v-model="input"
        class="chat__input"
        rows="2"
        placeholder="输入问题，Enter 发送，Shift+Enter 换行"
        @keydown="onKeydown"
      ></textarea>
      <div class="chat__actions">
        <span class="chat__hint">Enter 发送 · Shift+Enter 换行</span>
        <button class="btn btn--ghost" :disabled="sending" @click="newChat">新建会话</button>
        <button class="btn btn--primary" :disabled="!canSend" @click="send()">发送</button>
      </div>
    </div>

    <TracePanel :open="debugOpen" :trace-id="debugTraceId" @close="debugOpen = false" />
  </div>
</template>

<style scoped>
.chat {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
}

/* —— 状态条 —— */
.chat__bar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  padding: 0 2px var(--sp-3);
  border-bottom: 1px solid var(--rule);
}

.chat__scope {
  margin: 0;
  font-size: var(--fs-xs);
  color: var(--ink-3);
  max-width: 66ch;
  line-height: 1.6;
}

.chat__bar-side {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-shrink: 0;
}

.chat__mode {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: var(--fs-xs);
  padding: 3px var(--sp-2);
  border-radius: 999px;
  border: 1px solid var(--rule);
  background: var(--surface);
  white-space: nowrap;
  color: var(--ink-2);
}

.chat__mode-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--rule-strong);
}

.chat__mode--live {
  color: var(--pine);
  border-color: var(--pine-tint-2);
  background: var(--pine-tint);
}
.chat__mode--live .chat__mode-dot {
  background: var(--pine);
}

.chat__mode--mock {
  color: var(--ochre);
  border-color: var(--ochre-line);
  background: var(--ochre-tint);
}
.chat__mode--mock .chat__mode-dot {
  background: var(--ochre);
}

.chat__text-btn {
  border: none;
  background: none;
  padding: 0;
  font-size: var(--fs-xs);
  color: var(--ink-2);
  cursor: pointer;
  border-bottom: 1px solid transparent;
  transition:
    color var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}
.chat__text-btn:hover {
  color: var(--pine);
  border-bottom-color: var(--pine);
}

/* —— 消息区 —— */
.chat__body {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.chat__scroll {
  flex: 1;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  padding: var(--sp-4) 2px var(--sp-3);
}

.chat__row {
  display: flex;
  gap: var(--sp-2);
}
.chat__row--user {
  justify-content: flex-end;
}
.chat__row--bot {
  justify-content: flex-start;
}

/* 助手头像：深松绿圆标 */
.chat__avatar {
  flex-shrink: 0;
  width: 28px;
  height: 28px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--pine);
  color: #fff;
  font-size: 13px;
  font-weight: 700;
  margin-top: 2px;
}

.chat__bubble {
  max-width: min(720px, 86%);
  border-radius: 12px;
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-md);
}

.chat__bubble--user {
  background: var(--pine);
  color: #fff;
  border-bottom-right-radius: 4px;
  box-shadow: var(--shadow-sm);
}

.chat__bubble--bot {
  background: var(--surface);
  border: 1px solid var(--rule);
  border-top-left-radius: 4px;
  box-shadow: var(--shadow-sm);
}

.chat__q {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.6;
}

.chat__answer {
  word-break: break-word;
  line-height: 1.8;
}

.chat__analyzing {
  color: var(--ink-3);
  font-size: var(--fs-md);
}
.chat__dots {
  display: inline-block;
  animation: blink 1.2s steps(2, start) infinite;
}
@keyframes blink {
  50% {
    opacity: 0.25;
  }
}

.chat__err {
  font-size: var(--fs-sm);
}
.chat__err-title {
  color: var(--vermilion);
  font-weight: 600;
}
.chat__err-detail {
  margin-top: 2px;
  color: var(--ink-2);
  word-break: break-word;
}
.chat__retry {
  margin-top: var(--sp-2);
  height: 30px;
  padding: 0 var(--sp-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  cursor: pointer;
  font-size: var(--fs-sm);
  transition:
    border-color var(--dur) var(--ease),
    color var(--dur) var(--ease);
}
.chat__retry:hover {
  border-color: var(--pine);
  color: var(--pine);
}

.chat__meta {
  margin-top: var(--sp-3);
  display: flex;
  align-items: center;
  gap: var(--sp-3);
}

.chat__trace-link {
  margin-left: 0;
}

/* 答案类型标记 */
.tag--data {
  background: var(--pine-tint);
  color: var(--pine);
  border-color: var(--pine-tint-2);
}
.tag--doc {
  background: var(--ochre-tint);
  color: var(--ochre);
  border-color: var(--ochre-line);
}
.tag--hybrid {
  background: var(--pine);
  color: #fff;
  border-color: var(--pine-deep);
}
.tag--refusal,
.tag--clarify {
  background: var(--vermilion-tint);
  color: var(--vermilion);
  border-color: #f0d9d2;
}

.chat__nosource {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

/* —— 依据 —— */
.chat__evidence {
  margin-top: var(--sp-3);
  border-top: 1px solid var(--rule-soft);
  padding-top: var(--sp-3);
}
.chat__toggle {
  border: none;
  background: none;
  color: var(--pine);
  cursor: pointer;
  font-size: var(--fs-sm);
  font-weight: 500;
  padding: 0;
}
.chat__counts {
  color: var(--ink-3);
  font-weight: 400;
  margin-left: 6px;
}
.chat__evidence-body {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.chat__doc {
  border-left: 2px solid var(--ochre);
  padding: 2px 0 2px var(--sp-3);
}
.chat__doc-id {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--ochre);
  letter-spacing: 0.04em;
}
.chat__doc-quote {
  font-size: var(--fs-sm);
  color: var(--ink);
  margin-top: 2px;
  line-height: 1.7;
  word-break: break-word;
}
.chat__data {
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  background: var(--surface-sunk);
}
.chat__data-head {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
}
.chat__data-tool {
  font-weight: 600;
  color: var(--pine);
  letter-spacing: 0.04em;
}
.chat__data-scope {
  color: var(--ink-3);
  text-align: right;
}
.chat__data-result {
  margin: var(--sp-2) 0 0;
  font-family: var(--font-mono);
  font-size: var(--fs-xs);
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--ink);
  max-height: 180px;
  overflow-y: auto;
}
.chat__data-note {
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--ink-3);
}
.chat__empty {
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

/* —— 空状态 —— */
.chat__welcome {
  padding: var(--sp-8) 0 var(--sp-10);
  max-width: 680px;
  margin: 0 auto;
  text-align: center;
}

.chat__welcome-title {
  font-size: var(--fs-xl);
  font-weight: 600;
}

.chat__welcome-desc {
  margin-top: var(--sp-2);
  color: var(--ink-2);
  font-size: var(--fs-sm);
}

.chat__examples {
  margin-top: var(--sp-6);
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(260px, 1fr));
  gap: var(--sp-3);
  text-align: left;
}

.chat__example {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  border: 1px solid var(--rule);
  background: var(--surface);
  border-radius: var(--r-md);
  padding: var(--sp-3) var(--sp-4);
  font-size: var(--fs-sm);
  color: var(--ink);
  cursor: pointer;
  box-shadow: var(--shadow-sm);
  transition:
    border-color var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}

.chat__example:hover {
  border-color: var(--pine);
  box-shadow: var(--shadow-md);
  transform: translateY(-1px);
}

.chat__example-icon {
  display: grid;
  place-items: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  border-radius: var(--r-sm);
  background: var(--pine-tint);
  color: var(--pine);
}
.chat__example-icon svg {
  width: 14px;
  height: 14px;
}

/* —— 输入区 —— */
.chat__inputbar {
  border-top: 1px solid var(--rule);
  padding-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.chat__input {
  width: 100%;
  resize: none;
  border: 1px solid var(--rule-strong);
  border-radius: var(--r-md);
  padding: var(--sp-3);
  font-size: var(--fs-md);
  font-family: inherit;
  line-height: 1.6;
  min-height: 56px;
  background: var(--surface);
  transition:
    border-color var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease);
}
.chat__input:focus {
  outline: none;
  border-color: var(--pine);
  box-shadow: 0 0 0 3px rgba(23, 75, 70, 0.1);
}

.chat__actions {
  display: flex;
  align-items: center;
  justify-content: flex-end;
  gap: var(--sp-3);
}

.chat__hint {
  margin-right: auto;
  font-size: var(--fs-2xs);
  color: var(--ink-3);
  letter-spacing: 0.04em;
}

@media (max-width: 760px) {
  .chat__bar {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--sp-2);
  }
  .chat__hint {
    display: none;
  }
}
</style>
