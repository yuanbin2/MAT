<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import Sidebar from './components/Sidebar.vue'
import FilterBar from './components/FilterBar.vue'
import MetricCards from './components/MetricCards.vue'
import TrendChart from './components/TrendChart.vue'
import TopProducts from './components/TopProducts.vue'
import DataQuality from './components/DataQuality.vue'
import GlossaryModal from './components/GlossaryModal.vue'
import { fetchDataQuality, fetchDaily, fetchStores, fetchSummary, fetchTopProducts } from './api'
import type {
  DataQuality as DataQualityInfo,
  DailyMetrics,
  MetricsSummary,
  Store,
  TopProduct,
} from './types'
import { lastFullMonth } from './format'

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
    <Sidebar />

    <div class="main">
      <header class="topbar">
        <div>
          <h1 class="topbar__title">经营总览</h1>
          <div class="topbar__sub">
            <span>数据覆盖范围 <span class="num">{{ dataRange }}</span></span>
            <span class="topbar__dot">·</span>
            <span>当前报表区间 <span class="num">{{ appliedRange }}</span></span>
          </div>
        </div>
        <button class="glossary-btn" @click="glossaryOpen = true">指标口径</button>
      </header>

      <main class="content">
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
          <span>{{ metaError }}</span>
          <button class="btn btn--ghost" @click="loadMeta">重试</button>
        </div>

        <div v-else-if="metricsError" class="error-banner" role="alert">
          <span>{{ metricsError }}</span>
          <button class="btn btn--ghost" @click="loadMetrics">重试</button>
        </div>

        <template v-if="hasData || hasLoadedMetrics">
          <MetricCards :data="summary" :loading="metricsLoading" />
          <TrendChart :days="daily?.days ?? []" :loading="metricsLoading" />
          <div class="grid-bottom">
            <TopProducts :products="topProducts" :loading="metricsLoading" />
            <DataQuality :report="dataQuality?.cleaning_report ?? null" :loading="metaLoading" />
          </div>
        </template>

        <div v-else-if="!metaLoading && !metaError" class="empty-state card">
          <div class="empty-state__title">暂无有效销售数据</div>
          <div class="empty-state__desc">
            当前数据集清洗后没有可展示的经营数据，请确认 data/ 目录已就绪后执行重建。
          </div>
        </div>

        <!-- 第三关：AI 助手将在此处接入对话框，组件结构预留，暂不渲染占位内容 -->
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
}

.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 28px;
  background: var(--c-card);
  border-bottom: 1px solid var(--c-border);
  position: sticky;
  top: 0;
  z-index: 10;
}

.topbar__title {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  letter-spacing: 0.01em;
}

.topbar__sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--c-text-secondary);
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.topbar__dot {
  color: var(--c-border);
}

.glossary-btn {
  border: 1px solid var(--c-border);
  background: #fff;
  color: var(--c-text);
  height: 34px;
  padding: 0 14px;
  border-radius: 8px;
  font-size: 13px;
  cursor: pointer;
}

.glossary-btn:hover {
  border-color: var(--c-primary);
  color: var(--c-primary);
}

.content {
  padding: 20px 28px 32px;
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 1440px;
  width: 100%;
  margin: 0 auto;
}

.error-banner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  background: #fdf3f2;
  border: 1px solid #efd7d4;
  color: var(--c-red);
  padding: 12px 16px;
  border-radius: 8px;
  font-size: 13px;
}

.btn {
  height: 36px;
  padding: 0 18px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  white-space: nowrap;
}

.btn--ghost {
  background: #fff;
  color: var(--c-text);
  border-color: var(--c-border);
}

.btn--ghost:hover {
  border-color: var(--c-primary);
  color: var(--c-primary);
}

.grid-bottom {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
  align-items: start;
}

.empty-state {
  padding: 48px 24px;
  text-align: center;
}

.empty-state__title {
  font-size: 16px;
  font-weight: 600;
}

.empty-state__desc {
  margin-top: 8px;
  color: var(--c-text-secondary);
  font-size: 13px;
}

@media (max-width: 1100px) {
  .grid-bottom {
    grid-template-columns: 1fr;
  }
}
</style>
