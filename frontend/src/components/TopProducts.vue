<script setup lang="ts">
import type { TopProduct } from '../types'
import { formatMoney, formatNumber } from '../format'

defineProps<{
  products: TopProduct[]
  loading: boolean
}>()
</script>

<template>
  <div class="top card">
    <div class="card__header">
      <div>
        <div class="card__title">Top 10 商品</div>
        <div class="card__subtitle">按净营业额降序</div>
      </div>
    </div>

    <div class="card__body top__body">
      <div v-if="loading" class="top__loading">
        <div v-for="i in 5" :key="i" class="skeleton" style="height: 30px; margin-bottom: 10px"></div>
      </div>

      <div v-else-if="products.length === 0" class="top__empty muted">该区间暂无数据</div>

      <table v-else class="top__table">
        <thead>
          <tr>
            <th class="col-rank">名次</th>
            <th>商品名称</th>
            <th>品类</th>
            <th class="col-num">净营业额</th>
            <th class="col-num">销量</th>
            <th class="col-num">有效订单数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in products" :key="p.product_id">
            <td class="col-rank">
              <span class="rank" :class="{ 'rank--top': i < 3 }">{{ i + 1 }}</span>
            </td>
            <td class="name" :title="p.product_name">{{ p.product_name }}</td>
            <td class="muted category">{{ p.product_category }}</td>
            <td class="col-num revenue">{{ formatMoney(p.net_revenue) }}</td>
            <td class="col-num">{{ formatNumber(p.qty) }} 份</td>
            <td class="col-num">{{ formatNumber(p.orders) }} 单</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.top__body {
  padding-top: var(--sp-2);
  overflow-x: auto;
}

.top__table {
  width: 100%;
  border-collapse: collapse;
  font-size: var(--fs-sm);
}

.top__table th {
  text-align: left;
  font-weight: 500;
  color: var(--ink-3);
  font-size: var(--fs-2xs);
  letter-spacing: 0.1em;
  padding: 0 10px 8px;
  border-bottom: 1px solid var(--rule-strong);
  white-space: nowrap;
}

.top__table td {
  padding: 9px 10px;
  border-bottom: 1px solid var(--rule-soft);
  white-space: nowrap;
}

.top__table tbody tr:last-child td {
  border-bottom: none;
}

.top__table tbody tr {
  transition: background var(--dur) var(--ease);
}

.top__table tbody tr:hover {
  background: var(--surface-sunk);
}

.col-rank {
  width: 56px;
  padding-left: 0 !important;
}

.col-num {
  text-align: right;
  font-variant-numeric: tabular-nums;
}

/* 名次：前三名做浅松绿底章 */
.rank {
  display: inline-grid;
  place-items: center;
  width: 22px;
  height: 22px;
  font-size: var(--fs-xs);
  font-weight: 600;
  line-height: 1;
  color: var(--ink-3);
  border: 1px solid transparent;
  border-radius: var(--r-sm);
}

.rank--top {
  color: var(--pine);
  border-color: var(--pine-tint-2);
  background: var(--pine-tint);
  font-weight: 600;
}

.name {
  max-width: 220px;
  overflow: hidden;
  text-overflow: ellipsis;
  color: var(--ink);
}

.category {
  font-size: var(--fs-xs);
}

.revenue {
  font-weight: 600;
  color: var(--ink);
}

.top__empty,
.top__loading {
  min-height: 160px;
  display: grid;
  place-items: center;
}

.top__loading {
  display: block;
}
</style>
