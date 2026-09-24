<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, watch } from 'vue'
import * as echarts from 'echarts/core'
import { LineChart } from 'echarts/charts'
import { GridComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import type { DailyPoint } from '../types'
import { formatMoney, formatOrders, shortDate } from '../format'

echarts.use([LineChart, GridComponent, TooltipComponent, CanvasRenderer])

const props = defineProps<{
  days: DailyPoint[]
  loading: boolean
}>()

const chartEl = ref<HTMLDivElement | null>(null)
let chart: echarts.ECharts | null = null

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
    grid: { left: 64, right: 24, top: 30, bottom: 36 },
    tooltip: {
      trigger: 'axis',
      backgroundColor: '#fff',
      borderColor: 'var(--c-border)',
      borderWidth: 1,
      textStyle: { color: '#24302e', fontSize: 12 },
      padding: [10, 14],
      formatter: (params: any) => {
        const p = params[0]
        const point = props.days[p.dataIndex]
        const aov = point.aov === null ? '—' : formatMoney(point.aov)
        return (
          `<div style="font-weight:600;margin-bottom:6px">${point.date}</div>` +
          `<div>净营业额：<b>${formatMoney(point.net_revenue)}</b></div>` +
          `<div>有效订单数：${formatOrders(point.orders)}</div>` +
          `<div>客单价：${aov}</div>`
        )
      },
    },
    xAxis: {
      type: 'category',
      data: dates,
      boundaryGap: false,
      axisLine: { lineStyle: { color: '#d8dfda' } },
      axisTick: { show: false },
      axisLabel: {
        color: '#66736f',
        fontSize: 11,
        interval,
        formatter: (value: string) => shortDate(value),
      },
    },
    yAxis: {
      type: 'value',
      axisLabel: {
        color: '#66736f',
        fontSize: 11,
        formatter: (value: number) => (value >= 10000 ? `${(value / 10000).toFixed(1)}万` : `${value}`),
      },
      splitLine: { lineStyle: { color: '#eef1ee' } },
    },
    series: [
      {
        name: '净营业额',
        type: 'line',
        data: revenues,
        smooth: false,
        symbol: 'none',
        lineStyle: { color: '#174b46', width: 2 },
        itemStyle: { color: '#174b46' },
        areaStyle: { color: 'rgba(23, 75, 70, 0.06)' },
        emphasis: { focus: 'series' },
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
})

onBeforeUnmount(() => {
  window.removeEventListener('resize', resize)
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
  <div class="trend card">
    <div class="card__header">
      <div>
        <div class="card__title">营业额趋势</div>
        <div class="card__subtitle">按日净营业额（¥）</div>
      </div>
    </div>
    <div class="card__body trend__body">
      <div v-if="loading" class="trend__placeholder skeleton" style="height: 300px"></div>
      <div v-else-if="days.length === 0" class="trend__empty muted">该区间暂无数据</div>
      <div v-else ref="chartEl" class="trend__chart"></div>
    </div>
  </div>
</template>

<style scoped>
.trend__body {
  padding-top: 8px;
}

.trend__chart {
  height: 300px;
  width: 100%;
}

.trend__empty {
  height: 300px;
  display: grid;
  place-items: center;
}

.trend__placeholder {
  border-radius: 8px;
}
</style>
