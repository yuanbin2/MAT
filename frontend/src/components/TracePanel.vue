<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
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
const expandedFilters = ref<Record<string, boolean>>({})

//: 请求序号。快速连续切 trace ID 时，先发的请求可能后回来——只认最新那一次的结果，
//: 否则面板会显示成"另一个 trace 的内容"，排查时会被带偏。
let requestSeq = 0

const modeLabel = computed(() =>
  trace.value?.mode === 'live' ? '在线（真实模型）' : '降级（mock，未调用模型）',
)

async function load(traceId: string) {
  const id = traceId.trim()
  const seq = ++requestSeq
  manualId.value = id
  // 先无条件清空：换 ID、或者点了空查询，都不该继续显示上一条 trace 的内容。
  trace.value = null
  error.value = ''
  notFound.value = false
  if (!id) {
    loading.value = false
    return
  }
  loading.value = true
  try {
    const payload = await fetchTrace(id)
    if (seq !== requestSeq) return // 已经有更新的请求了，这条响应作废
    trace.value = payload
  } catch (e) {
    if (seq !== requestSeq) return
    if (e instanceof TraceNotFoundError) {
      notFound.value = true
    } else {
      error.value = (e as Error).message || '接口失败'
    }
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

watch(
  () => [props.open, props.traceId],
  () => {
    // 关着的时候不管；打开时一律走 load——包括 traceId 为空，
    // 那时的正确行为是清空旧内容，而不是把上一条留在屏幕上。
    if (props.open) load(props.traceId)
  },
  { immediate: true },
)

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))

function toggle(key: string) {
  collapsed.value[key] = !collapsed.value[key]
}

function toggleFilters(key: string) {
  expandedFilters.value[key] = !expandedFilters.value[key]
}

/** 过滤原因默认只显示前几条，点一下展开全部——排查"为什么这篇没进来"时要能看全。 */
function visibleFiltered(key: string, list: { doc_id: string; reason: string }[]) {
  return expandedFilters.value[key] ? list : list.slice(0, 4)
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
  <div v-if="open" class="trace-layer">
    <div class="trace-scrim" @click="emit('close')"></div>

    <aside class="drawer" role="dialog" aria-label="调试记录">
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
          class="drawer__input num"
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
            <h3 class="sec__title">知识库检索 <span class="sec__n num">{{ trace.retrievals.length }}</span></h3>
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
                  <tr><th>doc_id</th><th>chunk_id</th><th>分数</th><th>片段</th></tr>
                </thead>
                <tbody>
                  <tr v-for="(h, j) in r.hits" :key="'h' + j" :class="{ 'row--padded': h.padded }">
                    <td class="nowrap">{{ h.doc_id }}</td>
                    <td class="nowrap muted-cell">{{ h.chunk_id }}</td>
                    <td class="num nowrap">{{ h.score }}</td>
                    <td>
                      <span v-if="h.padded" class="tag tag--muted">补位</span>
                      <span v-else-if="h.sibling" class="tag tag--muted">相邻</span>
                      <span v-if="h.kind === 'table'" class="tag tag--muted">表格</span>
                      <span class="clip">{{ h.preview }}</span>
                    </td>
                  </tr>
                </tbody>
              </table>
              <div v-if="r.filtered && r.filtered.length" class="filters">
                <button class="filters__toggle" @click="toggleFilters('f' + i)">
                  被过滤 {{ r.filtered.length }} 篇
                  {{ expandedFilters['f' + i] ? '（收起）' : '（展开全部）' }}
                </button>
                <span
                  v-for="(f, j) in visibleFiltered('f' + i, r.filtered)"
                  :key="'f' + j"
                  class="filter-item"
                >
                  {{ f.doc_id }}（{{ f.reason }}）
                </span>
              </div>
            </div>
          </section>

          <!-- 4. 工具与数据 -->
          <section class="sec">
            <h3 class="sec__title">工具与数据 <span class="sec__n num">{{ trace.tools.length }}</span></h3>
            <div v-if="!trace.tools.length" class="empty">本次没有执行工具。</div>
            <div v-for="(t, i) in trace.tools" :key="'t' + i" class="sub">
              <div class="sub__head">
                <span class="sub__name">
                  {{ t.tool }}
                  <span class="tag" :class="`tag--${t.status}`">{{ t.status }}</span>
                  <span v-if="t.accepted" class="tag tag--ok">已用于{{ t.entered === 'citations' ? '引用' : '证据' }}</span>
                  <span v-else-if="t.pending" class="tag tag--warn">待回答定稿后核对</span>
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
    </aside>
  </div>
</template>

<style scoped>
.trace-layer {
  position: fixed;
  inset: 0;
  z-index: 50;
}

.trace-scrim {
  position: absolute;
  inset: 0;
  background: rgba(30, 46, 43, 0.28);
  animation: fade 200ms var(--ease) both;
}

@keyframes fade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.drawer {
  position: absolute;
  top: 0;
  right: 0;
  width: min(640px, 100vw);
  height: 100vh;
  background: var(--paper);
  border-left: 1px solid var(--rule-strong);
  box-shadow: -12px 0 32px rgba(23, 75, 70, 0.12);
  display: flex;
  flex-direction: column;
  animation: slide-in 260ms var(--ease) both;
}

@keyframes slide-in {
  from {
    transform: translateX(24px);
    opacity: 0.4;
  }
  to {
    transform: none;
    opacity: 1;
  }
}

.drawer__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  background: var(--pine);
  color: #eaf1ee;
}

.drawer__title {
  display: flex;
  align-items: baseline;
  gap: var(--sp-3);
  font-size: var(--fs-md);
  font-weight: 600;
  letter-spacing: 0.03em;
}

.drawer__id {
  font-size: var(--fs-xs);
  color: rgba(234, 241, 238, 0.7);
  font-weight: 400;
}

.drawer__head-actions {
  display: flex;
  gap: var(--sp-2);
}

.mini {
  height: 28px;
  padding: 0 10px;
  font-size: var(--fs-xs);
  border: 1px solid rgba(234, 241, 238, 0.35);
  border-radius: var(--r-xs);
  background: transparent;
  color: #eaf1ee;
  cursor: pointer;
  transition:
    background var(--dur) var(--ease),
    color var(--dur) var(--ease),
    border-color var(--dur) var(--ease);
}
.mini:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.12);
  border-color: rgba(255, 255, 255, 0.5);
}
.mini:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.mini--close {
  border-color: rgba(192, 138, 58, 0.7);
  color: #e8c98d;
}

.drawer__lookup {
  display: flex;
  gap: var(--sp-2);
  padding: var(--sp-3) var(--sp-5);
  background: var(--surface);
  border-bottom: 1px solid var(--rule);
}

.drawer__input {
  flex: 1;
  min-width: 0;
  height: 32px;
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  padding: 0 var(--sp-2);
  font-size: var(--fs-xs);
  background: var(--surface);
}
.drawer__input:focus {
  outline: none;
  border-color: var(--pine);
  box-shadow: 0 0 0 3px rgba(23, 75, 70, 0.08);
}

.btn {
  height: 32px;
  padding: 0 var(--sp-4);
  border: none;
  border-radius: var(--r-sm);
  background: var(--pine);
  color: #f6f2e8;
  font-size: var(--fs-xs);
  cursor: pointer;
  transition: background var(--dur) var(--ease);
}
.btn:hover {
  background: var(--pine-deep);
}

.drawer__body {
  flex: 1;
  overflow-y: auto;
  padding: var(--sp-4) var(--sp-5) var(--sp-10);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  counter-reset: sec;
}

.state {
  color: var(--ink-2);
  font-size: var(--fs-sm);
  padding: var(--sp-6) 0;
}
.state--warn {
  color: var(--ochre);
}
.state--err {
  color: var(--vermilion);
}

.sec {
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--r-sm);
  padding: var(--sp-4);
}

.sec__title {
  margin: 0 0 var(--sp-3);
  font-size: var(--fs-sm);
  font-weight: 600;
  color: var(--pine);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--rule-soft);
}

/* 章节序号：01 02 03… */
.sec__title::before {
  counter-increment: sec;
  content: counter(sec, decimal-leading-zero);
  font-family: var(--font-serif);
  font-weight: 400;
  font-size: var(--fs-xs);
  color: var(--ink-3);
}

.sec__n {
  font-size: var(--fs-2xs);
  color: var(--pine);
  background: var(--pine-tint);
  border: 1px solid var(--pine-tint-2);
  border-radius: var(--r-xs);
  padding: 0 6px;
  font-weight: 500;
}

.kv {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.kv__row {
  display: flex;
  gap: var(--sp-3);
  font-size: var(--fs-sm);
  align-items: baseline;
}
.kv__k {
  flex-shrink: 0;
  width: 72px;
  color: var(--ink-3);
  font-size: var(--fs-xs);
}
.kv__v {
  word-break: break-word;
  min-width: 0;
}
.kv__v--bad {
  color: var(--vermilion);
  font-weight: 600;
}

.preview {
  margin-top: var(--sp-3);
  padding: var(--sp-3);
  background: var(--surface-sunk);
  border: 1px solid var(--rule-soft);
  border-radius: var(--r-sm);
  font-size: var(--fs-sm);
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
}

.sub {
  border-top: 1px dashed var(--rule);
  padding-top: var(--sp-3);
  margin-top: var(--sp-3);
}
.sub:first-of-type {
  border-top: none;
  margin-top: 0;
  padding-top: 0;
}

.sub__head {
  display: flex;
  justify-content: space-between;
  gap: var(--sp-3);
  align-items: baseline;
}
.sub__name {
  font-size: var(--fs-sm);
  font-weight: 600;
}
.sub__meta {
  font-size: var(--fs-xs);
  color: var(--ink-3);
  text-align: right;
}

.mini-table {
  width: 100%;
  border-collapse: collapse;
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
}
.mini-table th {
  text-align: left;
  color: var(--ink-3);
  font-weight: 500;
  font-size: var(--fs-2xs);
  letter-spacing: 0.08em;
  padding: var(--sp-1) 6px;
  border-bottom: 1px solid var(--rule-strong);
}
.mini-table td {
  padding: 5px 6px;
  border-bottom: 1px solid var(--rule-soft);
  vertical-align: top;
}

.nowrap {
  white-space: nowrap;
}
.num {
  font-variant-numeric: tabular-nums;
}
.row--padded td {
  color: var(--ink-3);
}
.clip {
  display: inline-block;
  word-break: break-word;
}

.tag {
  display: inline-block;
  font-size: var(--fs-2xs);
  padding: 0 5px;
  border-radius: var(--r-xs);
  margin-right: 4px;
  border: 1px solid transparent;
}
.tag--ok {
  background: var(--pine-tint);
  color: var(--pine);
  border-color: var(--pine-tint-2);
}
.tag--warn {
  background: var(--ochre-tint);
  color: var(--ochre);
  border-color: var(--ochre-line);
}
.tag--rejected,
.tag--error {
  background: var(--vermilion-tint);
  color: var(--vermilion);
  border-color: #efd8d1;
}
.tag--muted {
  background: var(--surface-sunk);
  color: var(--ink-3);
  border-color: var(--rule-soft);
}

.filters {
  margin-top: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--ink-3);
  line-height: 1.8;
}
.filters__toggle {
  color: var(--ochre);
  background: none;
  border: none;
  padding: 0;
  margin-right: var(--sp-2);
  font: inherit;
  cursor: pointer;
  border-bottom: 1px solid currentColor;
}
.filters__toggle:focus-visible {
  outline: 2px solid var(--pine);
  outline-offset: 2px;
}
.muted-cell {
  color: var(--ink-3);
}
.filter-item {
  margin-right: var(--sp-2);
}

.reject {
  margin-top: 6px;
  font-size: var(--fs-xs);
  color: var(--vermilion);
  background: var(--vermilion-tint);
  border-left: 2px solid var(--vermilion);
  border-radius: 0 var(--r-xs) var(--r-xs) 0;
  padding: 6px var(--sp-2);
}

.code {
  margin: var(--sp-2) 0 0;
  padding: var(--sp-3);
  background: var(--surface-sunk);
  border: 1px solid var(--rule-soft);
  border-radius: var(--r-sm);
  font-family: var(--font-mono);
  font-size: var(--fs-2xs);
  line-height: 1.65;
  white-space: pre-wrap;
  word-break: break-word;
  max-height: 260px;
  overflow-y: auto;
}

.link {
  margin-top: 6px;
  border: none;
  background: none;
  color: var(--pine);
  font-size: var(--fs-xs);
  cursor: pointer;
  padding: 0;
  border-bottom: 1px solid transparent;
}
.link:hover {
  border-bottom-color: var(--pine);
}

.fold {
  margin-top: 6px;
}
details summary {
  cursor: pointer;
  font-size: var(--fs-xs);
  color: var(--pine);
  margin-top: 6px;
}

.empty {
  font-size: var(--fs-sm);
  color: var(--ink-3);
}

.errors {
  margin-top: var(--sp-3);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.error-item {
  border-left: 2px solid var(--vermilion);
  padding-left: var(--sp-3);
}
.error-item__head {
  font-size: var(--fs-xs);
  font-weight: 600;
  color: var(--vermilion);
}
.error-item__msg {
  font-size: var(--fs-xs);
  word-break: break-word;
  color: var(--ink-2);
}

@media (max-width: 680px) {
  .drawer {
    width: 100vw;
  }
  .kv__k {
    width: 60px;
  }

  /* 头部允许换行：标题 + 三个操作按钮在 390px 下放不下 */
  .drawer__head {
    padding: var(--sp-3) var(--sp-4);
    flex-wrap: wrap;
  }
  .drawer__title {
    min-width: 0;
    flex-wrap: wrap;
  }
  .drawer__head-actions {
    width: 100%;
    justify-content: flex-end;
  }
  .mini {
    height: 32px; /* 触摸目标 */
  }
  .drawer__lookup {
    padding: var(--sp-3) var(--sp-4);
  }
  .drawer__input {
    height: 40px;
    font-size: 16px;
  }
  .btn {
    height: 40px;
  }
  .drawer__body {
    padding: var(--sp-3) var(--sp-4) var(--sp-8);
    padding-bottom: max(var(--sp-8), env(safe-area-inset-bottom));
  }
}
</style>
