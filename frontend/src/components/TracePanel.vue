<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { TraceNotFoundError, fetchTrace } from '../api'
import type { TracePayload } from '../types'

const props = defineProps<{ open: boolean; traceId: string }>()
const emit = defineEmits<{ (e: 'close'): void }>()

const trace = ref<TracePayload | null>(null)
const loading = ref(false)
const error = ref('')
const notFound = ref(false)
const manualId = ref('')
const copied = ref(false)
const collapsed = ref<Record<string, boolean>>({})

const modeLabel = computed(() =>
  trace.value?.mode === 'live' ? '在线（真实模型）' : '降级（mock，未调用模型）',
)

async function load(traceId: string) {
  const id = traceId.trim()
  if (!id) return
  manualId.value = id
  loading.value = true
  error.value = ''
  notFound.value = false
  trace.value = null
  try {
    trace.value = await fetchTrace(id)
  } catch (e) {
    if (e instanceof TraceNotFoundError) {
      notFound.value = true
    } else {
      error.value = (e as Error).message || '接口失败'
    }
  } finally {
    loading.value = false
  }
}

watch(
  () => [props.open, props.traceId],
  () => {
    if (props.open && props.traceId) load(props.traceId)
  },
  { immediate: true },
)

function toggle(key: string) {
  collapsed.value[key] = !collapsed.value[key]
}

function pretty(value: unknown): string {
  if (value === null || value === undefined) return ''
  try {
    return typeof value === 'string' ? value : JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function fmtMs(value: number | null | undefined): string {
  // 没测量到就如实说“未记录”，不用 0 冒充。
  if (value === null || value === undefined) return '未记录'
  return `${value} ms`
}

function fmtParams(params: Record<string, unknown> | undefined): string {
  if (!params) return ''
  return Object.entries(params)
    .map(([key, value]) => `${key}=${typeof value === 'object' ? JSON.stringify(value) : value}`)
    .join(' · ')
}

async function copyId() {
  if (!trace.value) return
  try {
    await navigator.clipboard.writeText(trace.value.trace_id)
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  } catch {
    error.value = '复制失败，请手动选中 trace ID'
  }
}

function exportJson() {
  if (!trace.value) return
  // 接口返回的就是落盘前已脱敏的记录，直接导出即可。
  const blob = new Blob([JSON.stringify(trace.value, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${trace.value.trace_id}.json`
  a.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div v-if="open" class="drawer" role="dialog" aria-label="调试记录">
    <div class="drawer__head">
      <div class="drawer__title">
        <span>调试记录</span>
        <span v-if="trace" class="drawer__id num">{{ trace.trace_id }}</span>
      </div>
      <div class="drawer__head-actions">
        <button class="mini" :disabled="!trace" @click="copyId">
          {{ copied ? '已复制' : '复制 ID' }}
        </button>
        <button class="mini" :disabled="!trace" @click="exportJson">导出脱敏 JSON</button>
        <button class="mini mini--close" @click="emit('close')">关闭</button>
      </div>
    </div>

    <div class="drawer__lookup">
      <input
        v-model="manualId"
        class="drawer__input"
        placeholder="粘贴 trace ID（例如 t-20260901-0001）"
        @keydown.enter="load(manualId)"
      />
      <button class="btn" @click="load(manualId)">查看</button>
    </div>

    <div class="drawer__body">
      <div v-if="loading" class="state">加载中…</div>
      <div v-else-if="notFound" class="state state--warn">
        记录不存在或已过期（服务只保留有界数量的 trace）。
      </div>
      <div v-else-if="error" class="state state--err">{{ error }}</div>

      <template v-else-if="trace">
        <!-- 1. 概览 -->
        <section class="sec">
          <h3 class="sec__title">概览</h3>
          <div class="kv">
            <div class="kv__row"><span class="kv__k">原问题</span><span class="kv__v">{{ trace.question || '（空）' }}</span></div>
            <div class="kv__row"><span class="kv__k">回答类型</span><span class="kv__v">{{ trace.answer.type || '—' }}</span></div>
            <div class="kv__row"><span class="kv__k">模式</span><span class="kv__v">{{ modeLabel }}</span></div>
            <div class="kv__row"><span class="kv__k">总耗时</span><span class="kv__v num">{{ fmtMs(trace.total_ms) }}</span></div>
            <div class="kv__row">
              <span class="kv__k">错误数</span>
              <span class="kv__v num" :class="{ 'kv__v--bad': trace.errors.length }">{{ trace.errors.length }}</span>
            </div>
          </div>
          <div v-if="trace.answer.answer_preview" class="preview">{{ trace.answer.answer_preview }}</div>
        </section>

        <!-- 2. 问题理解 -->
        <section class="sec">
          <h3 class="sec__title">问题理解</h3>
          <div class="kv">
            <div class="kv__row"><span class="kv__k">补全问题</span><span class="kv__v">{{ trace.plan.standalone_question || trace.question }}</span></div>
            <div class="kv__row"><span class="kv__k">意图 / 类型</span><span class="kv__v">{{ trace.plan.intent || '—' }} / {{ trace.plan.kind || '—' }}</span></div>
            <div class="kv__row"><span class="kv__k">日期区间</span><span class="kv__v num">{{ pretty(trace.plan.window) || '—' }}<template v-if="trace.plan.compare_window"> · 对比 {{ pretty(trace.plan.compare_window) }}</template></span></div>
            <div class="kv__row"><span class="kv__k">门店 / 商品</span><span class="kv__v">{{ trace.plan.store_id || '全部' }} / {{ trace.plan.product_id || '全部' }}</span></div>
            <div class="kv__row"><span class="kv__k">指标</span><span class="kv__v">{{ trace.plan.metric || '—' }}</span></div>
            <div class="kv__row"><span class="kv__k">检索查询</span><span class="kv__v">{{ trace.plan.search_query || '—' }}</span></div>
          </div>
        </section>

        <!-- 3. 知识库检索 -->
        <section class="sec">
          <h3 class="sec__title">知识库检索 <span class="sec__n">{{ trace.retrievals.length }}</span></h3>
          <div v-if="!trace.retrievals.length" class="empty">本次没有检索知识库。</div>
          <div v-for="(r, i) in trace.retrievals" :key="'r' + i" class="sub">
            <div class="sub__head">
              <span class="sub__name">{{ r.query }}</span>
              <span class="sub__meta num">
                as_of {{ r.as_of || '—' }} · 门店 {{ r.store_id || '全部' }} · 覆盖 {{ r.coverage ?? '—' }}
                <template v-if="r.window"> · 窗口 {{ r.window[0] }}~{{ r.window[1] }}</template>
              </span>
            </div>
            <table class="mini-table">
              <thead>
                <tr><th>doc_id</th><th>分数</th><th>片段</th></tr>
              </thead>
              <tbody>
                <tr v-for="(h, j) in r.hits" :key="'h' + j" :class="{ 'row--padded': h.padded }">
                  <td class="nowrap">{{ h.doc_id }}</td>
                  <td class="num nowrap">{{ h.score }}</td>
                  <td>
                    <span v-if="h.padded" class="tag tag--muted">补位</span>
                    <span class="clip">{{ h.preview }}</span>
                  </td>
                </tr>
              </tbody>
            </table>
            <div v-if="r.filtered && r.filtered.length" class="filters">
              <span class="filters__label">被过滤 {{ r.filtered.length }} 篇：</span>
              <span v-for="(f, j) in r.filtered.slice(0, 4)" :key="'f' + j" class="filter-item">
                {{ f.doc_id }}（{{ f.reason }}）
              </span>
            </div>
          </div>
        </section>

        <!-- 4. 工具与数据 -->
        <section class="sec">
          <h3 class="sec__title">工具与数据 <span class="sec__n">{{ trace.tools.length }}</span></h3>
          <div v-if="!trace.tools.length" class="empty">本次没有执行工具。</div>
          <div v-for="(t, i) in trace.tools" :key="'t' + i" class="sub">
            <div class="sub__head">
              <span class="sub__name">
                {{ t.tool }}
                <span class="tag" :class="`tag--${t.status}`">{{ t.status }}</span>
                <span v-if="t.accepted" class="tag tag--ok">已用于{{ t.entered === 'citations' ? '引用' : '证据' }}</span>
                <span v-else class="tag tag--muted">未采纳</span>
              </span>
              <span class="sub__meta num">{{ fmtMs(t.took_ms) }}<template v-if="t.result_bytes"> · {{ t.result_bytes }} B</template></span>
            </div>
            <div class="kv__row"><span class="kv__k">参数</span><span class="kv__v num">{{ fmtParams(t.params) || '—' }}</span></div>
            <div v-if="t.reject_reason" class="reject">拒绝原因：{{ t.reject_reason }}</div>
            <button class="link" @click="toggle('tool' + i)">
              {{ collapsed['tool' + i] ? '展开结果' : '收起结果' }}
            </button>
            <pre v-if="!collapsed['tool' + i] && t.result_preview" class="code">{{ t.result_preview }}</pre>
          </div>
        </section>

        <!-- 5. 模型与异常 -->
        <section class="sec">
          <h3 class="sec__title">模型与异常</h3>
          <div v-if="!trace.model_called" class="empty">
            本次未调用模型（{{ trace.mode === 'mock' ? 'mock 降级模式' : '规划器已决定走本地模板' }}）。
          </div>
          <div v-for="(c, i) in trace.llm_calls" :key="'l' + i" class="sub">
            <div class="sub__head">
              <span class="sub__name">第 {{ i + 1 }} 次调用</span>
              <span class="sub__meta num">
                {{ c.model || '' }} · {{ fmtMs(c.took_ms) }}
                <template v-if="c.status"> · HTTP {{ c.status }}</template>
                <template v-if="c.error"> · {{ c.error }}</template>
              </span>
            </div>
            <details v-if="c.request" class="fold">
              <summary>最终请求 / 提示词</summary>
              <pre class="code">{{ c.request }}</pre>
            </details>
            <details v-if="c.response">
              <summary>原始响应</summary>
              <pre class="code">{{ c.response }}</pre>
            </details>
            <div v-if="c.detail" class="reject">{{ c.detail }}</div>
          </div>
          <div v-if="trace.errors.length" class="errors">
            <div v-for="(e, i) in trace.errors" :key="'e' + i" class="error-item">
              <div class="error-item__head">{{ e.where }} · {{ e.type }}</div>
              <div class="error-item__msg">{{ e.message }}</div>
              <details v-if="e.traceback">
                <summary>堆栈</summary>
                <pre class="code">{{ e.traceback }}</pre>
              </details>
            </div>
          </div>
        </section>

        <!-- 6. 时间线 -->
        <section class="sec">
          <h3 class="sec__title">时间线</h3>
          <table class="mini-table">
            <thead>
              <tr><th>步骤</th><th>发生</th><th>耗时</th></tr>
            </thead>
            <tbody>
              <tr v-for="(s, i) in trace.steps" :key="'s' + i">
                <td>{{ s.step }}</td>
                <td class="num nowrap">{{ s.at_ms }} ms</td>
                <td class="num nowrap">{{ fmtMs(s.took_ms) }}</td>
              </tr>
            </tbody>
          </table>
        </section>
      </template>
    </div>
  </div>
</template>

<style scoped>
.drawer {
  position: fixed;
  top: 0;
  right: 0;
  width: min(620px, 100vw);
  height: 100vh;
  background: var(--c-bg);
  border-left: 1px solid var(--c-border);
  box-shadow: -8px 0 24px rgba(23, 75, 70, 0.08);
  display: flex;
  flex-direction: column;
  z-index: 50;
}
.drawer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 18px;
  background: var(--c-card);
  border-bottom: 1px solid var(--c-border);
}
.drawer__title {
  display: flex;
  align-items: baseline;
  gap: 10px;
  font-weight: 600;
  font-size: 15px;
}
.drawer__id {
  font-size: 12px;
  color: var(--c-text-secondary);
  font-weight: 400;
}
.drawer__head-actions {
  display: flex;
  gap: 8px;
}
.mini {
  height: 28px;
  padding: 0 10px;
  font-size: 12px;
  border: 1px solid var(--c-border);
  border-radius: 6px;
  background: #fff;
  cursor: pointer;
}
.mini:hover:not(:disabled) {
  border-color: var(--c-primary);
  color: var(--c-primary);
}
.mini:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.mini--close {
  border-color: #e6cfcc;
  color: var(--c-red);
}
.drawer__lookup {
  display: flex;
  gap: 8px;
  padding: 12px 18px;
  background: var(--c-card);
  border-bottom: 1px solid var(--c-border);
}
.drawer__input {
  flex: 1;
  height: 32px;
  border: 1px solid var(--c-border);
  border-radius: 6px;
  padding: 0 10px;
  font-size: 13px;
}
.drawer__input:focus {
  outline: none;
  border-color: var(--c-primary);
}
.btn {
  height: 32px;
  padding: 0 14px;
  border: none;
  border-radius: 6px;
  background: var(--c-primary);
  color: #fff;
  font-size: 13px;
  cursor: pointer;
}
.drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: 16px 18px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}
.state {
  color: var(--c-text-secondary);
  font-size: 13px;
  padding: 24px 0;
}
.state--warn {
  color: var(--c-amber);
}
.state--err {
  color: var(--c-red);
}
.sec {
  background: var(--c-card);
  border: 1px solid var(--c-border);
  border-radius: 10px;
  padding: 14px 16px;
}
.sec__title {
  margin: 0 0 10px;
  font-size: 13px;
  font-weight: 600;
  color: var(--c-primary);
  display: flex;
  align-items: center;
  gap: 8px;
}
.sec__n {
  font-size: 11px;
  color: #fff;
  background: var(--c-primary);
  border-radius: 999px;
  padding: 0 7px;
  font-weight: 500;
}
.kv {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kv__row {
  display: flex;
  gap: 10px;
  font-size: 13px;
  align-items: baseline;
}
.kv__k {
  flex-shrink: 0;
  width: 76px;
  color: var(--c-text-secondary);
  font-size: 12px;
}
.kv__v {
  word-break: break-word;
}
.kv__v--bad {
  color: var(--c-red);
  font-weight: 600;
}
.preview {
  margin-top: 10px;
  padding: 10px 12px;
  background: #fafbfa;
  border: 1px solid var(--c-border);
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.6;
  white-space: pre-wrap;
  word-break: break-word;
}
.sub {
  border-top: 1px dashed var(--c-border);
  padding-top: 10px;
  margin-top: 10px;
}
.sub:first-of-type {
  border-top: none;
  margin-top: 0;
  padding-top: 0;
}
.sub__head {
  display: flex;
  justify-content: space-between;
  gap: 10px;
  align-items: baseline;
}
.sub__name {
  font-size: 13px;
  font-weight: 600;
}
.sub__meta {
  font-size: 12px;
  color: var(--c-text-secondary);
  text-align: right;
}
.mini-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: 8px;
  font-size: 12px;
}
.mini-table th {
  text-align: left;
  color: var(--c-text-secondary);
  font-weight: 500;
  padding: 4px 6px;
  border-bottom: 1px solid var(--c-border);
}
.mini-table td {
  padding: 5px 6px;
  border-bottom: 1px solid #f0f3f1;
  vertical-align: top;
}
.nowrap {
  white-space: nowrap;
}
.num {
  font-variant-numeric: tabular-nums;
}
.row--padded td {
  color: var(--c-text-secondary);
}
.clip {
  display: inline-block;
  word-break: break-word;
}
.tag {
  display: inline-block;
  font-size: 11px;
  padding: 0 6px;
  border-radius: 999px;
  margin-right: 4px;
}
.tag--ok {
  background: #eef5f3;
  color: var(--c-primary);
}
.tag--rejected,
.tag--error {
  background: #f7eeee;
  color: var(--c-red);
}
.tag--muted {
  background: #f0f2f0;
  color: var(--c-text-secondary);
}
.filters {
  margin-top: 8px;
  font-size: 12px;
  color: var(--c-text-secondary);
  line-height: 1.7;
}
.filters__label {
  color: var(--c-amber);
}
.filter-item {
  margin-right: 10px;
}
.reject {
  margin-top: 6px;
  font-size: 12px;
  color: var(--c-red);
  background: #fdf3f2;
  border-radius: 6px;
  padding: 6px 8px;
}
.code {
  margin: 8px 0 0;
  padding: 10px;
  background: #f7f9f8;
  border: 1px solid var(--c-border);
  border-radius: 6px;
  font-family: 'SF Mono', 'Cascadia Code', Consolas, monospace;
  font-size: 11.5px;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow-y: auto;
}
.link {
  margin-top: 6px;
  border: none;
  background: none;
  color: var(--c-primary);
  font-size: 12px;
  cursor: pointer;
  padding: 0;
}
.fold {
  margin-top: 6px;
}
details summary {
  cursor: pointer;
  font-size: 12px;
  color: var(--c-primary);
  margin-top: 6px;
}
.empty {
  font-size: 13px;
  color: var(--c-text-secondary);
}
.errors {
  margin-top: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.error-item {
  border-left: 2px solid var(--c-red);
  padding-left: 10px;
}
.error-item__head {
  font-size: 12px;
  font-weight: 600;
  color: var(--c-red);
}
.error-item__msg {
  font-size: 12px;
  word-break: break-word;
}
@media (max-width: 680px) {
  .drawer {
    width: 100vw;
  }
  .kv__k {
    width: 64px;
  }
}
</style>
