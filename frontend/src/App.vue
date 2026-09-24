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

const stores = ref<Store[]>([])
const dataQuality = ref<DataQualityInfo | null>(null)

const start = ref('')
const end = ref('')
const storeId = ref('')

const summary = ref<MetricsSummary | null>(null)
const daily = ref<DailyMetrics | null>(null)
const topProducts = ref<TopProduct[]>([])

const loading = ref(true)
const metaLoading = ref(true)
const error = ref('')

const glossaryOpen = ref(false)

const dataRange = computed(() => {
  const s = dataQuality.value?.data_period.start
  const e = dataQuality.value?.data_period.end
  return s && e ? `${s} ~ ${e}` : '—'
})

const defaultStart = ref('')
const defaultEnd = ref('')

async function loadMeta() {
  metaLoading.value = true
  try {
    const [storesResp, dqResp] = await Promise.all([fetchStores(), fetchDataQuality()])
    stores.value = storesResp.stores
    dataQuality.value = dqResp
    // 默认范围 = 数据实际覆盖区间，系统“今天”固定 2026-09-01，不用真实电脑日期。
    const s = dqResp.data_period.start ?? '2026-05-01'
    const e = dqResp.data_period.end ?? '2026-08-31'
    defaultStart.value = s
    defaultEnd.value = e
    start.value = s
    end.value = e
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    metaLoading.value = false
  }
}

async function loadMetrics() {
  if (!start.value || !end.value) return
  loading.value = true
  error.value = ''
  const params = {
    start: start.value,
    end: end.value,
    ...(storeId.value ? { store_id: storeId.value } : {}),
  }
  try {
    const [sum, day, top] = await Promise.all([
      fetchSummary(params),
      fetchDaily(params),
      fetchTopProducts({ ...params, limit: 10 }),
    ])
    summary.value = sum
    daily.value = day
    topProducts.value = top.products
  } catch (e) {
    error.value = (e as Error).message
  } finally {
    loading.value = false
  }
}

function onQuery() {
  loadMetrics()
}

function onReset() {
  start.value = defaultStart.value
  end.value = defaultEnd.value
  storeId.value = ''
  loadMetrics()
}

onMounted(async () => {
  await loadMeta()
  await loadMetrics()
})
</script>

<template>
  <div class="layout">
    <Sidebar />

    <div class="main">
      <header class="topbar">
        <div>
          <h1 class="topbar__title">经营总览</h1>
          <div class="topbar__sub">
            数据范围 <span class="num">{{ dataRange }}</span>
            <span v-if="storeId" class="topbar__chip">{{ storeId }}</span>
          </div>
        </div>
        <button class="glossary-btn" @click="glossaryOpen = true">指标口径</button>
      </header>

      <main class="content">
        <FilterBar
          :stores="stores"
          :start="start"
          :end="end"
          :store-id="storeId"
          @update:start="start = $event"
          @update:end="end = $event"
          @update:store-id="storeId = $event"
          @query="onQuery"
          @reset="onReset"
        />

        <div v-if="error" class="error-banner" role="alert">
          <span>数据加载失败：{{ error }}</span>
          <button class="btn btn--ghost" @click="loadMetrics">重试</button>
        </div>

        <MetricCards :data="summary" :loading="loading || metaLoading" />

        <TrendChart :days="daily?.days ?? []" :loading="loading || metaLoading" />

        <div class="grid-bottom">
          <TopProducts :products="topProducts" :loading="loading || metaLoading" />
          <DataQuality :report="dataQuality?.cleaning_report ?? null" :loading="metaLoading" />
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
  margin-top: 2px;
  font-size: 12px;
  color: var(--c-text-secondary);
}

.topbar__chip {
  display: inline-block;
  margin-left: 8px;
  padding: 1px 8px;
  border-radius: 999px;
  background: #e5f0ee;
  color: var(--c-primary);
  font-size: 11px;
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

.grid-bottom {
  display: grid;
  grid-template-columns: 3fr 2fr;
  gap: 16px;
  align-items: start;
}

@media (max-width: 1100px) {
  .grid-bottom {
    grid-template-columns: 1fr;
  }
}
</style>
