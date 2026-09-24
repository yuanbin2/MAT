<script setup lang="ts">
import { computed } from 'vue'
import type { MetricsSummary } from '../types'
import { formatMoney, formatOrders, formatQty } from '../format'

const props = defineProps<{
  data: MetricsSummary | null
  loading: boolean
}>()

// 卡片名称必须与 KB-001 v3 一致。
const cards = computed(() => {
  const d = props.data
  return [
    {
      key: 'net_revenue',
      label: '净营业额',
      value: d ? formatMoney(d.net_revenue) : '—',
      unit: '¥',
    },
    {
      key: 'orders',
      label: '有效订单数',
      value: d ? formatOrders(d.orders) : '—',
      unit: '单',
    },
    {
      key: 'aov',
      label: '客单价',
      value: d ? formatMoney(d.aov) : '—',
      unit: '¥',
      note: d && d.aov === null ? '无订单' : undefined,
    },
    {
      key: 'qty',
      label: '销量',
      value: d ? formatQty(d.qty) : '—',
      unit: '份',
    },
    {
      key: 'refund_amount',
      label: '退款金额',
      value: d ? formatMoney(d.refund_amount) : '—',
      unit: '¥',
      tone: 'refund',
    },
  ]
})
</script>

<template>
  <div class="metrics">
    <div v-if="loading" v-for="i in 5" :key="i" class="metric card">
      <div class="metric__label skeleton" style="width: 72px; height: 14px"></div>
      <div class="skeleton" style="width: 60%; height: 28px; margin-top: 12px"></div>
    </div>

    <div v-else v-for="card in cards" :key="card.key" class="metric card">
      <div class="metric__label">{{ card.label }}</div>
      <div
        class="metric__value num"
        :class="{ 'metric__value--refund': card.tone === 'refund' }"
      >
        {{ card.value }}
      </div>
      <div v-if="card.note" class="metric__note">{{ card.note }}</div>
    </div>
  </div>
</template>

<style scoped>
.metrics {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 16px;
}

.metric {
  padding: 18px 20px;
}

.metric__label {
  font-size: 13px;
  color: var(--c-text-secondary);
}

.metric__value {
  margin-top: 10px;
  font-size: 26px;
  font-weight: 600;
  color: var(--c-text);
  line-height: 1.2;
}

.metric__value--refund {
  color: var(--c-red);
}

.metric__note {
  margin-top: 6px;
  font-size: 12px;
  color: var(--c-amber);
}

@media (max-width: 1100px) {
  .metrics {
    grid-template-columns: repeat(3, 1fr);
  }
}

@media (max-width: 680px) {
  .metrics {
    grid-template-columns: repeat(2, 1fr);
  }
}
</style>
