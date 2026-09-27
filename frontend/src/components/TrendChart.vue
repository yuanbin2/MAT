<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { DataZoomComponent, GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { DailyPoint } from '../types'
import { formatMoney, formatOrders, shortDate } from '../format'

echarts.use([LineChart, GridComponent, TooltipComponent, DataZoomComponent, CanvasRenderer])

const props = defineProps<{
  days: DailyPoint[]
  loading: boolean
}>()

// 图表配色跟随设计系统（canvas 渲染器读不到 CSS 变量，这里必须写死色值）。
const INK = '#1E2E2B'
const INK_3 = '#6B746E'
const PINE = '#174B46'
const PINE_SOFT = '#2C6B62'
const PINE_TINT = '#E4EDEA'
const RULE = '#DED8C9'
const RULE_SOFT = '#EAE5D9'
const RULE_STRONG = '#C9C2AF'
const SURFACE = '#FFFDF8'

const chartEl = ref<HTMLDivElement | null>(null)
const rootEl = ref<HTMLElement | null>(null)
let chart: echarts.ECharts | null = null
// 容器尺寸变化（如与数据质量卡等高拉伸）时也要重绘，不能只监听 window。
let ro: ResizeObserver | null = null

function render() {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value)
  } else if (chart.getDom() !== chartEl.value) {
    // 容器在 loading/空态之间被 v-if 卸载又重挂载，旧实例已脱离文档，
    // 必须 dispose 后重新 init，否则图会画在看不见的旧 DOM 上。
    chart.dispose()
    chart = echarts.init(chartEl.value)
  }

  const dates = props.days.map((d) => d.date)
  const revenues = props.days.map((d) => d.net_revenue)

  // 区间较长时降低 X 轴标签密度，避免挤成一团。
  const interval = props.days.length > 60 ? Math.ceil(props.days.length / 30) - 1 : 'auto'

  chart.setOption({
    grid: { left: 12, right: 16, top: 24, bottom: props.days.length > 60 ? 52 : 24, containLabel: true },
    tooltip: {
      trigger: 'axis',
      backgroundColor: SURFACE,
      borderColor: RULE,
      borderWidth: 1,
      extraCssText: 'box-shadow: 0 6px 20px rgba(23,75,70,0.10); border-radius: 3px;',
      textStyle: { color: INK, fontSize: 12 },
      padding: [10, 14],
      axisPointer: {
        type: 'line',
        lineStyle: { color: RULE_STRONG, width: 1, type: 'dashed' },
      },
      formatter: (params: any) => {
        const p = params[0]
        const point = props.days[p.dataIndex]
        const aov = point.aov === null ? '—' : formatMoney(point.aov)
        return (
          `<div style="font-family:Georgia,'Songti SC',serif;font-size:13px;font-weight:600;` +
          `color:${PINE};margin-bottom:6px">${point.date}</div>` +
          `<div style="display:flex;gap:16px"><span style="color:${INK_3}">净营业额</span>` +
          `<b style="font-variant-numeric:tabular-nums">${formatMoney(point.net_revenue)}</b></div>` +
          `<div style="display:flex;gap:16px"><span style="color:${INK_3}">有效订单数</span>` +
          `<span style="font-variant-numeric:tabular-nums">${formatOrders(point.orders)}</span></div>` +
          `<div style="display:flex;gap:16px"><span style="color:${INK_3}">客单价</span>` +
          `<span style="font-variant-numeric:tabular-nums">${aov}</span></div>`
        )
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: RULE } },
      axisTick: { show: false },
      axisLabel: {
        color: INK_3,
        fontSize: 11,
        interval,
        formatter: (value: string) => shortDate(value),
      },
    },
    yAxis: {
      type: 'value',
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: {
        color: INK_3,
        fontSize: 11,
        formatter: (value: number) =>
          value >= 10000 ? `${(value / 10000).toFixed(1)}万` : `${value}`,
      },
      splitLine: { lineStyle: { color: RULE_SOFT, type: 'dashed' } },
    },
    series: [
      {
        name: '净营业额',
        type: 'line',
        data: revenues,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: PINE, width: 1.75 },
        itemStyle: { color: PINE },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: 'rgba(23,75,70,0.16)' },
              { offset: 1, color: 'rgba(23,75,70,0)' },
            ],
          },
        },
        emphasis: { focus: 'series', lineStyle: { width: 2.5 } },
      },
    ],
    // 长跨度区间可拖拽/滚轮缩放；短区间自然无感。
    dataZoom: [
      { type: 'inside', filterMode: 'none', zoomOnMouseWheel: true, moveOnMouseMove: true },
      {
        type: 'slider',
        filterMode: 'none',
        height: 18,
        bottom: 6,
        borderColor: RULE_SOFT,
        show: props.days.length > 60,
        handleStyle: { color: PINE, borderColor: PINE },
        moveHandleStyle: { color: RULE_STRONG },
        dataBackground: { lineStyle: { color: PINE_SOFT }, areaStyle: { color: PINE_TINT } },
        selectedDataBackground: { lineStyle: { color: PINE }, areaStyle: { color: PINE_TINT } },
        textStyle: { color: INK_3, fontSize: 10 },
      },
    ],
  })
}

function resize() {
  chart?.resize()
}

onMounted(() => {
  render()
  window.addEventListener('resize', resize)
  ro = new ResizeObserver(() => resize())
  if (rootEl.value) ro.observe(rootEl.value)
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
  ro?.disconnect()
  ro = null
  chart?.dispose()
  chart = null
})

// flush: 'post' —— 等 v-if/v-else 分支真正挂载后再初始化图表，
// 否则 loading 翻转时 chartEl 还是 null，图会画在空处。
watch(() => props.days, render, { deep: true, flush: 'post' })
watch(
  () => props.loading,
  () => {
    if (!props.loading) render()
  },
  { flush: 'post' },
)
</script>

<template>
  <div ref="rootEl" class="trend card">
    <div class="card__header trend__header">
      <div>
        <div class="card__title">营业额趋势</div>
        <div class="card__subtitle">按日净营业额（¥），退款已从当日营业额中扣除</div>
      </div>
      <div class="trend__legend">
        <span class="trend__legend-key" aria-hidden="true"></span>
        <span class="trend__legend-text">净营业额</span>
        <span v-if="!loading && days.length" class="trend__legend-count num">
          共 {{ days.length }} 天
        </span>
      </div>
    </div>
    <div class="card__body trend__body">
      <div v-if="loading" class="trend__placeholder skeleton"></div>
      <div v-else-if="days.length === 0" class="trend__empty muted">该区间暂无数据</div>
      <div v-else ref="chartEl" class="trend__chart"></div>
    </div>
  </div>
</template>

<style scoped>
.trend__header {
  align-items: flex-start;
  padding-bottom: var(--sp-1);
}

.trend__legend {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: var(--ink-2);
  flex-shrink: 0;
}

.trend__legend-key {
  width: 14px;
  height: 0;
  border-top: 2px solid var(--pine);
}

.trend__legend-count {
  color: var(--ink-3);
  padding-left: var(--sp-2);
  border-left: 1px solid var(--rule);
}

/* 卡片纵向 flex：图表填满剩余高度（与右侧数据质量卡等高拉伸） */
.trend {
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.trend__body {
  flex: 1;
  display: flex;
  flex-direction: column;
  padding-top: var(--sp-2);
  min-height: 0;
}

.trend__chart {
  flex: 1;
  min-height: 320px;
  width: 100%;
}

.trend__empty {
  flex: 1;
  min-height: 320px;
  display: grid;
  place-items: center;
  font-size: var(--fs-sm);
}

.trend__placeholder {
  flex: 1;
  min-height: 320px;
  border-radius: var(--r-sm);
}

@media (max-width: 760px) {
  .trend__chart,
  .trend__empty,
  .trend__placeholder {
    min-height: 260px;
  }
}
</style>
