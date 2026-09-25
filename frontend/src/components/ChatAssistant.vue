<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { fetchChat, fetchHealth } from '../api'
import type { AnswerType, Citation, DataEvidence, HealthInfo } from '../types'
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

onMounted(() => {
  sessionId.value = newSessionId()
  loadHealth()
})
</script>

<template>
  <div class="chat">
    <div class="chat__header">
      <div>
        <h1 class="chat__title">AI 助手</h1>
        <div class="chat__sub">
          基于数据库实绩与公司知识库作答，回答附数据依据与文档来源；对话范围不受看板筛选影响。
        </div>
      </div>
      <div class="chat__mode-wrap">
        <button class="chat__debug-entry" @click="openDebugLookup">调试记录</button>
        <div class="chat__mode" :class="`chat__mode--${mode}`">
          <template v-if="mode === 'live'">已接入大模型 · 在线</template>
          <template v-else-if="mode === 'mock'">本地演示 · 降级模式（未配置模型 Key）</template>
          <template v-else>{{ healthError || '服务状态未知' }}</template>
        </div>
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
          <div class="chat__bubble">
            <template v-if="msg.role === 'user'">
              <div class="chat__q">{{ msg.text }}</div>
            </template>

            <template v-else-if="msg.state === 'loading'">
              <div class="chat__analyzing">正在分析<span class="chat__dots">…</span></div>
            </template>

            <template v-else-if="msg.state === 'error'">
              <div class="chat__err">
                <div class="chat__err-title">请求失败</div>
                <div class="chat__err-detail">{{ msg.error }}</div>
                <button class="chat__retry" @click="retry(msg)">重试</button>
              </div>
            </template>

            <template v-else>
              <div class="chat__answer">{{ msg.text }}</div>

              <div class="chat__meta" v-if="msg.answerType">
                <span class="chat__badge" :class="`chat__badge--${msg.answerType}`">
                  {{ ANSWER_LABELS[msg.answerType] }}
                </span>
                <button v-if="msg.traceId" class="chat__trace-link" @click="openTrace(msg.traceId)">
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
                    <div class="chat__doc-id">{{ c.doc_id }}</div>
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

              <div v-if="!msg.citations.length && !msg.evidence.length && msg.answerType === 'refusal'" class="chat__nosource">
                无可用来源
              </div>
            </template>
          </div>
        </div>
      </div>

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
        <button class="chat__new" :disabled="sending" @click="newChat">新建会话</button>
        <button class="chat__send" :disabled="!canSend" @click="send()">发送</button>
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

.chat__header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 2px 2px 16px;
}

.chat__title {
  margin: 0;
  font-size: 18px;
  font-weight: 600;
}

.chat__sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--c-text-secondary);
}

.chat__mode-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-shrink: 0;
}
.chat__debug-entry {
  font-size: 12px;
  height: 26px;
  padding: 0 10px;
  border: 1px solid var(--c-border);
  border-radius: 6px;
  background: #fff;
  color: var(--c-text-secondary);
  cursor: pointer;
}
.chat__debug-entry:hover {
  border-color: var(--c-primary);
  color: var(--c-primary);
}
.chat__trace-link {
  margin-left: 10px;
  border: none;
  background: none;
  color: var(--c-primary);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
  text-decoration: underline;
}
.chat__mode {
  flex-shrink: 0;
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 999px;
  border: 1px solid var(--c-border);
  background: #fff;
  white-space: nowrap;
}
.chat__mode--live {
  color: var(--c-primary);
  border-color: #cfe0dc;
  background: #f0f6f4;
}
.chat__mode--mock {
  color: var(--c-amber);
  border-color: #ead9c4;
  background: #fbf6ef;
}

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
  gap: 14px;
  padding: 4px 2px 8px;
}

.chat__row {
  display: flex;
}
.chat__row--user {
  justify-content: flex-end;
}
.chat__row--bot {
  justify-content: flex-start;
}

.chat__bubble {
  max-width: min(720px, 88%);
  border-radius: 10px;
  padding: 12px 16px;
  border: 1px solid var(--c-border);
  background: var(--c-card);
  box-shadow: var(--shadow);
  font-size: 14px;
}
.chat__row--user .chat__bubble {
  background: var(--c-primary);
  color: #fff;
  border-color: var(--c-primary);
}

.chat__q {
  white-space: pre-wrap;
  word-break: break-word;
}

.chat__answer {
  white-space: pre-wrap;
  word-break: break-word;
  line-height: 1.7;
}

.chat__analyzing {
  color: var(--c-text-secondary);
  font-size: 14px;
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
  font-size: 13px;
}
.chat__err-title {
  color: var(--c-red);
  font-weight: 600;
}
.chat__err-detail {
  margin-top: 4px;
  color: var(--c-text-secondary);
  word-break: break-word;
}
.chat__retry {
  margin-top: 10px;
  height: 30px;
  padding: 0 14px;
  border: 1px solid var(--c-border);
  border-radius: 8px;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
}
.chat__retry:hover {
  border-color: var(--c-primary);
  color: var(--c-primary);
}

.chat__meta {
  margin-top: 10px;
}
.chat__badge {
  display: inline-block;
  font-size: 12px;
  padding: 2px 10px;
  border-radius: 999px;
}
.chat__badge--data {
  background: #eef5f3;
  color: var(--c-primary);
}
.chat__badge--doc {
  background: #fbf4e8;
  color: var(--c-amber);
}
.chat__badge--hybrid {
  background: #eef5f3;
  color: var(--c-primary);
  border: 1px solid #cfe0dc;
}
.chat__badge--refusal,
.chat__badge--clarify {
  background: #f7eeee;
  color: var(--c-red);
}

.chat__nosource {
  margin-top: 8px;
  font-size: 12px;
  color: var(--c-text-secondary);
}

.chat__evidence {
  margin-top: 12px;
  border-top: 1px solid var(--c-border);
  padding-top: 10px;
}
.chat__toggle {
  border: none;
  background: none;
  color: var(--c-primary);
  cursor: pointer;
  font-size: 13px;
  padding: 0;
}
.chat__counts {
  color: var(--c-text-secondary);
  margin-left: 6px;
}
.chat__evidence-body {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chat__doc {
  border-left: 2px solid var(--c-amber);
  padding: 4px 0 4px 12px;
}
.chat__doc-id {
  font-size: 12px;
  font-weight: 600;
  color: var(--c-amber);
}
.chat__doc-quote {
  font-size: 13px;
  color: var(--c-text);
  margin-top: 2px;
  word-break: break-word;
}
.chat__data {
  border: 1px solid var(--c-border);
  border-radius: 8px;
  padding: 10px 12px;
  background: #fafbfa;
}
.chat__data-head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  font-size: 12px;
}
.chat__data-tool {
  font-weight: 600;
  color: var(--c-primary);
}
.chat__data-scope {
  color: var(--c-text-secondary);
  text-align: right;
}
.chat__data-result {
  margin: 8px 0 0;
  font-size: 12px;
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  color: var(--c-text);
  max-height: 180px;
  overflow-y: auto;
}
.chat__data-note {
  margin-top: 6px;
  font-size: 12px;
  color: var(--c-text-secondary);
}
.chat__empty {
  font-size: 12px;
  color: var(--c-text-secondary);
}

.chat__welcome {
  padding: 32px 8px;
}
.chat__welcome-title {
  font-size: 16px;
  font-weight: 600;
}
.chat__welcome-desc {
  margin-top: 6px;
  color: var(--c-text-secondary);
  font-size: 13px;
}
.chat__examples {
  margin-top: 16px;
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}
.chat__example {
  border: 1px solid var(--c-border);
  background: #fff;
  border-radius: 999px;
  padding: 6px 14px;
  font-size: 13px;
  color: var(--c-text);
  cursor: pointer;
}
.chat__example:hover {
  border-color: var(--c-primary);
  color: var(--c-primary);
}

.chat__inputbar {
  border-top: 1px solid var(--c-border);
  padding-top: 14px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.chat__input {
  width: 100%;
  resize: none;
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 10px 12px;
  font-size: 14px;
  font-family: inherit;
  line-height: 1.5;
  min-height: 52px;
  background: #fff;
}
.chat__input:focus {
  outline: none;
  border-color: var(--c-primary);
  box-shadow: 0 0 0 3px rgba(23, 75, 70, 0.1);
}
.chat__actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}
.chat__new {
  height: 34px;
  padding: 0 16px;
  border: 1px solid var(--c-border);
  background: #fff;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}
.chat__new:hover {
  border-color: var(--c-primary);
  color: var(--c-primary);
}
.chat__send {
  height: 34px;
  padding: 0 20px;
  border: none;
  background: var(--c-primary);
  color: #fff;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}
.chat__send:disabled {
  background: #9fb6b1;
  cursor: not-allowed;
}
</style>
