<script setup lang="ts">
import { computed } from 'vue'
import type { MetricsSummary } from '../types'
import { formatMoney, formatOrders, formatQty } from '../format'

const props = defineProps<{
  data: MetricsSummary | null
  loading: boolean
}>()

// 卡片名称必须与 KB-001 v3 一致；图标为 20x20 线性 SVG（path 数据）。
const cards = computed(() => {
  const d = props.data
  return [
    {
      key: 'net_revenue',
      label: '净营业额',
      value: d ? formatMoney(d.net_revenue) : '—',
      lead: true,
      tone: '',
      paths: [
        'M3 6.5h14a1 1 0 0 1 1 1v7a1 1 0 0 1-1 1H3a1 1 0 0 1-1-1v-7a1 1 0 0 1 1-1Z',
        'M10 8.2a2.3 2.3 0 1 0 0 4.6 2.3 2.3 0 0 0 0-4.6Z',
        'M4.8 9.2v3.6M15.2 9.2v3.6',
      ],
    },
    {
      key: 'orders',
      label: '有效订单数',
      value: d ? formatOrders(d.orders) : '—',
      tone: '',
      paths: [
        'M5.5 3.5h9v13l-2.2-1.4-2.3 1.4-2.3-1.4L5.5 16.5v-13Z',
        'M8 7h4M8 10h4',
      ],
    },
    {
      key: 'aov',
      label: '客单价',
      value: d ? formatMoney(d.aov) : '—',
      note: d && d.aov === null ? '无订单' : undefined,
      tone: '',
      paths: [
        'M10 3.8a2.9 2.9 0 1 0 0 5.8 2.9 2.9 0 0 0 0-5.8Z',
        'M4.3 16.5c.8-3.1 2.9-4.7 5.7-4.7s4.9 1.6 5.7 4.7',
      ],
    },
    {
      key: 'qty',
      label: '销量',
      value: d ? formatQty(d.qty) : '—',
      tone: '',
      paths: [
        'M6.2 7.5h7.6l.9 9H5.3l.9-9Z',
        'M7.7 7.5V6a2.3 2.3 0 0 1 4.6 0v1.5',
      ],
    },
    {
      key: 'refund_amount',
      label: '退款金额',
      value: d ? formatMoney(d.refund_amount) : '—',
      tone: 'refund',
      paths: [
        'M16.6 10.4a6.1 6.1 0 1 1-2.1-4.6',
        'M16.8 2.8v3.6h-3.6',
      ],
    },
  ]
})
</script>

<template>
  <div class="metrics">
    <div v-if="loading" v-for="i in 5" :key="i" class="metric card">
      <div class="metric__head">
        <div class="skeleton" style="width: 32px; height: 32px; border-radius: 8px"></div>
        <div class="skeleton" style="width: 64px; height: 13px"></div>
      </div>
      <div class="skeleton" style="width: 62%; height: 28px; margin-top: 14px"></div>
    </div>

    <div
      v-else
      v-for="card in cards"
      :key="card.key"
      class="metric card"
      :class="{ 'metric--lead': card.lead }"
    >
      <div class="metric__head">
        <span
          class="metric__icon"
          :class="{ 'metric__icon--refund': card.tone === 'refund' }"
          aria-hidden="true"
        >
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
            <path v-for="(p, i) in card.paths" :key="i" :d="p" />
          </svg>
        </span>
        <span class="metric__label">{{ card.label }}</span>
      </div>
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
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: var(--sp-4);
}

.metric {
  padding: var(--sp-4) var(--sp-4) var(--sp-4);
  min-width: 0;
  transition:
    box-shadow var(--dur) var(--ease),
    transform var(--dur) var(--ease);
}

.metric:hover {
  box-shadow: var(--shadow-md);
}

.metric__head {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-width: 0;
}

.metric__icon {
  display: grid;
  place-items: center;
  width: 32px;
  height: 32px;
  flex-shrink: 0;
  border-radius: var(--r-md);
  background: var(--pine-tint);
  color: var(--pine);
}

.metric__icon--refund {
  background: var(--vermilion-tint);
  color: var(--vermilion);
}

.metric__icon svg {
  width: 18px;
  height: 18px;
}

.metric__label {
  font-size: var(--fs-sm);
  color: var(--ink-2);
  font-weight: 500;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.metric__value {
  margin-top: var(--sp-3);
  font-size: 26px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--ink);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* 净营业额是这行 KPI 的锚点 */
.metric--lead .metric__value {
  color: var(--pine);
}

.metric__value--refund {
  color: var(--vermilion);
}

.metric__note {
  margin-top: var(--sp-1);
  font-size: var(--fs-2xs);
  color: var(--ochre);
}

@media (max-width: 1240px) {
  .metrics {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}

@media (max-width: 680px) {
  .metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .metric--lead {
    grid-column: span 2;
  }
}
</style>
