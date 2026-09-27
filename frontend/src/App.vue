<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Sidebar from './components/Sidebar.vue'
import FilterBar from './components/FilterBar.vue'
import MetricCards from './components/MetricCards.vue'
import TrendChart from './components/TrendChart.vue'
import TopProducts from './components/TopProducts.vue'
import DataQuality from './components/DataQuality.vue'
import GlossaryModal from './components/GlossaryModal.vue'
import ChatAssistant from './components/ChatAssistant.vue'
import { fetchDataQuality, fetchDaily, fetchStores, fetchSummary, fetchTopProducts } from './api'
import type {
  DataQuality as DataQualityInfo,
  DailyMetrics,
  MetricsSummary,
  Store,
  TopProduct,
} from './types'
import { lastFullMonth } from './format'

// ---- 页面切换 ----
const view = ref<'overview' | 'assistant'>('overview')

// ---- 元数据（门店列表 + 数据质量，加载一次）----
const stores = ref<Store[]>([])
const dataQuality = ref<DataQualityInfo | null>(null)
const metaLoading = ref(false)
const metaError = ref('')

// ---- 草稿筛选条件（用户正在编辑，尚未应用）----
const draftStart = ref('')
const draftEnd = ref('')
const draftStoreId = ref('')

// ---- 已应用的报表条件（当前展示的数据用的条件）----
const appliedStart = ref('')
const appliedEnd = ref('')
const appliedStoreId = ref('')

// ---- 指标结果 ----
const summary = ref<MetricsSummary | null>(null)
const daily = ref<DailyMetrics | null>(null)
const topProducts = ref<TopProduct[]>([])
const metricsLoading = ref(false)
const metricsError = ref('')
const hasLoadedMetrics = ref(false)

// 请求序号：连续快速点击查询/重置时，旧响应不得覆盖新结果。
let requestSeq = 0

const glossaryOpen = ref(false)

const dataPeriod = computed(() => ({
  start: dataQuality.value?.data_period.start ?? null,
  end: dataQuality.value?.data_period.end ?? null,
}))

const hasData = computed(() => !!(dataPeriod.value.start && dataPeriod.value.end))

const dataRange = computed(() =>
  hasData.value ? `${dataPeriod.value.start} ~ ${dataPeriod.value.end}` : '暂无数据',
)

const appliedRange = computed(() =>
  appliedStart.value && appliedEnd.value
    ? `${appliedStart.value} ~ ${appliedEnd.value}${appliedStoreId.value ? ` · ${appliedStoreId.value}` : ''}`
    : '—',
)

async function loadMeta() {
  metaLoading.value = true
  metaError.value = ''
  const [storesRes, dqRes] = await Promise.allSettled([fetchStores(), fetchDataQuality()])

  const failures: string[] = []
  if (storesRes.status === 'fulfilled') {
    stores.value = storesRes.value.stores
  } else {
    failures.push(`门店列表（${(storesRes.reason as Error).message}）`)
  }
  if (dqRes.status === 'fulfilled') {
    dataQuality.value = dqRes.value
  } else {
    failures.push(`数据质量（${(dqRes.reason as Error).message}）`)
  }

  metaLoading.value = false

  if (failures.length) {
    metaError.value = '元数据加载失败：' + failures.join('、')
    return
  }

  // 元数据就绪后，确定默认区间（最近一个完整数据月），再加载指标。
  if (hasData.value) {
    const r = lastFullMonth(dataPeriod.value.end as string, dataPeriod.value.start as string)
    draftStart.value = r.start
    draftEnd.value = r.end
    draftStoreId.value = ''
  }
  // 无销售数据：不写死任何日期，保持为空，页面展示真实空状态。
  await loadMetrics()
}

async function loadMetrics() {
  // 没有可用日期范围时不发起请求（此时 draft 为空，由 FilterBar 禁用查询）。
  if (!draftStart.value || !draftEnd.value) {
    hasLoadedMetrics.value = false
    return
  }
  const seq = ++requestSeq
  metricsLoading.value = true
  metricsError.value = ''
  const params = {
    start: draftStart.value,
    end: draftEnd.value,
    ...(draftStoreId.value ? { store_id: draftStoreId.value } : {}),
  }
  try {
    const [sum, day, top] = await Promise.all([
      fetchSummary(params),
      fetchDaily(params),
      fetchTopProducts({ ...params, limit: 10 }),
    ])
    if (seq !== requestSeq) return
    // 请求成功才把草稿条件“应用”为报表条件。
    appliedStart.value = draftStart.value
    appliedEnd.value = draftEnd.value
    appliedStoreId.value = draftStoreId.value
    summary.value = sum
    daily.value = day
    topProducts.value = top.products
    hasLoadedMetrics.value = true
  } catch (e) {
    if (seq !== requestSeq) return
    // 查询失败：保留旧结果，明确标注旧结果所用条件。
    metricsError.value =
      `查询失败：${(e as Error).message}。当前展示的仍是 ` +
      `${appliedRange.value}${appliedRange.value === '—' ? '' : ' 的结果'}，可重试。`
  } finally {
    if (seq === requestSeq) metricsLoading.value = false
  }
}

function onQuery() {
  loadMetrics()
}

function onReset() {
  if (hasData.value) {
    const r = lastFullMonth(dataPeriod.value.end as string, dataPeriod.value.start as string)
    draftStart.value = r.start
    draftEnd.value = r.end
  } else {
    draftStart.value = ''
    draftEnd.value = ''
  }
  draftStoreId.value = ''
  loadMetrics()
}

onMounted(loadMeta)
</script>

<template>
  <div class="layout">
    <Sidebar :active="view" @navigate="view = $event" />

    <div class="main">
      <header class="topbar">
        <div class="topbar__lead">
          <h1 class="topbar__title">{{ view === 'overview' ? '经营总览' : 'AI 助手' }}</h1>
          <div v-if="view === 'overview'" class="topbar__sub">
            <span>数据覆盖 <span class="num">{{ dataRange }}</span></span>
            <span class="topbar__dot" aria-hidden="true"></span>
            <span>共 {{ stores.length }} 家门店</span>
            <span class="topbar__dot" aria-hidden="true"></span>
            <span>当前报表区间 <span class="num">{{ appliedRange }}</span></span>
          </div>
        </div>
        <button v-if="view === 'overview'" class="glossary-btn" @click="glossaryOpen = true">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M10 5.5C8.8 4.4 7 4 4 4v11c3 0 4.8.4 6 1.5 1.2-1.1 3-1.5 6-1.5V4c-3 0-4.8.4-6 1.5Z" />
            <path d="M10 5.5v11" />
          </svg>
          指标口径
        </button>
      </header>

      <main v-if="view === 'overview'" class="content">
        <FilterBar
          v-model:start="draftStart"
          v-model:end="draftEnd"
          v-model:store-id="draftStoreId"
          :stores="stores"
          :data-period="dataPeriod"
          :disabled="metaLoading"
          @query="onQuery"
          @reset="onReset"
        />

        <div v-if="metaError" class="error-banner" role="alert">
          <span class="error-banner__mark" aria-hidden="true">!</span>
          <span class="error-banner__text">{{ metaError }}</span>
          <button class="btn--text error-banner__retry" @click="loadMeta">重试</button>
        </div>

        <div v-else-if="metricsError" class="error-banner" role="alert">
          <span class="error-banner__mark" aria-hidden="true">!</span>
          <span class="error-banner__text">{{ metricsError }}</span>
          <button class="btn--text error-banner__retry" @click="loadMetrics">重试</button>
        </div>

        <template v-if="hasData || hasLoadedMetrics">
          <MetricCards :data="summary" :loading="metricsLoading" />

          <!-- 趋势（主）+ 数据质量（辅）并排；Top10 独占一行 -->
          <div class="grid-mid">
            <TrendChart :days="daily?.days ?? []" :loading="metricsLoading" />
            <DataQuality :report="dataQuality?.cleaning_report ?? null" :loading="metaLoading" />
          </div>

          <TopProducts :products="topProducts" :loading="metricsLoading" />
        </template>

        <div v-else-if="!metaLoading && !metaError" class="empty-state card">
          <div class="empty-state__title">暂无有效销售数据</div>
          <div class="empty-state__desc">
            当前数据集清洗后没有可展示的经营数据，请确认 data/ 目录已就绪后执行重建。
          </div>
        </div>
      </main>

      <main v-else class="content content--chat">
        <ChatAssistant />
      </main>
    </div>

    <GlossaryModal :open="glossaryOpen" @close="glossaryOpen = false" />
  </div>
</template>

<style scoped>
.layout {
  display: flex;
  min-height: 100vh;
}

.main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  height: 100vh;
  overflow: hidden;
}

/* —— 顶栏 —— */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-6);
  flex-shrink: 0;
  padding: var(--sp-4) var(--sp-6);
  background: var(--surface);
  border-bottom: 1px solid var(--rule);
  z-index: 10;
}

.topbar__title {
  margin: 0;
  font-size: var(--fs-xl);
  font-weight: 600;
  letter-spacing: 0.01em;
  line-height: 1.3;
}

.topbar__sub {
  margin-top: 2px;
  font-size: var(--fs-xs);
  color: var(--ink-2);
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

.topbar__sub .num {
  color: var(--ink);
}

.topbar__dot {
  width: 3px;
  height: 3px;
  border-radius: 50%;
  background: var(--rule-strong);
}

.glossary-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  border: 1px solid var(--rule-strong);
  background: var(--surface);
  color: var(--ink-2);
  height: 34px;
  padding: 0 var(--sp-3);
  border-radius: var(--r-md);
  font-size: var(--fs-sm);
  font-weight: 500;
  cursor: pointer;
  flex-shrink: 0;
  transition:
    border-color var(--dur) var(--ease),
    color var(--dur) var(--ease);
}

.glossary-btn svg {
  width: 15px;
  height: 15px;
}

.glossary-btn:hover {
  border-color: var(--pine);
  color: var(--pine);
}

/* —— 内容区 —— */
.content {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  padding: var(--sp-5) var(--sp-6) var(--sp-8);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
}

/* 纵向 flex 容器里，任何面板都不许被压缩 */
.content > * {
  flex-shrink: 0;
}

.content--chat {
  gap: 0;
  padding-bottom: var(--sp-5);
}

/* 趋势（主）+ 数据质量（辅） */
.grid-mid {
  display: grid;
  grid-template-columns: minmax(0, 1.9fr) minmax(0, 1fr);
  gap: var(--sp-4);
  align-items: stretch;
}

/* —— 错误条 —— */
.error-banner {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  background: var(--vermilion-tint);
  border: 1px solid #f0d9d2;
  border-left: 3px solid var(--vermilion);
  border-radius: var(--r-md);
  padding: 10px var(--sp-4);
  font-size: var(--fs-sm);
  color: var(--ink);
}

.error-banner__mark {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  display: grid;
  place-items: center;
  border-radius: 50%;
  background: var(--vermilion);
  color: #fff;
  font-size: 11px;
  font-weight: 700;
}

.error-banner__text {
  flex: 1;
  min-width: 0;
}

.error-banner__retry {
  color: var(--vermilion);
  border-bottom: 1px solid currentColor;
  border-radius: 0;
  padding-bottom: 1px;
}
.error-banner__retry:hover {
  color: var(--pine);
}

/* —— 空状态 —— */
.empty-state {
  padding: var(--sp-10) var(--sp-6);
  text-align: center;
}

.empty-state__title {
  font-size: var(--fs-lg);
  font-weight: 600;
}

.empty-state__desc {
  margin-top: var(--sp-2);
  color: var(--ink-2);
  font-size: var(--fs-sm);
}

@media (max-width: 1200px) {
  .grid-mid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 1100px) {
  .topbar,
  .content {
    padding-left: var(--sp-5);
    padding-right: var(--sp-5);
  }
}

@media (max-width: 760px) {
  .topbar {
    flex-direction: column;
    align-items: flex-start;
    gap: var(--sp-3);
  }
  .topbar__sub {
    flex-direction: column;
    align-items: flex-start;
    gap: 2px;
  }
  .topbar__dot {
    display: none;
  }
}
</style>
