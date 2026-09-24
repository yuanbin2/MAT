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
        <div v-for="i in 5" :key="i" class="skeleton" style="height: 32px; margin-bottom: 8px"></div>
      </div>

      <div v-else-if="products.length === 0" class="top__empty muted">该区间暂无数据</div>

      <table v-else class="top__table">
        <thead>
          <tr>
            <th class="col-rank">排名</th>
            <th>商品名称</th>
            <th>品类</th>
            <th class="num">净营业额</th>
            <th class="num">销量</th>
            <th class="num">有效订单数</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="(p, i) in products" :key="p.product_id">
            <td class="col-rank">
              <span class="rank" :class="{ 'rank--top': i < 3 }">{{ i + 1 }}</span>
            </td>
            <td class="name" :title="p.product_name">{{ p.product_name }}</td>
            <td class="muted">{{ p.product_category }}</td>
            <td class="num">{{ formatMoney(p.net_revenue) }}</td>
            <td class="num">{{ formatNumber(p.qty) }} 份</td>
            <td class="num">{{ formatNumber(p.orders) }} 单</td>
          </tr>
        </tbody>
      </table>
    </div>
  </div>
</template>

<style scoped>
.top__body {
  padding-top: 8px;
  overflow-x: auto;
}

.top__table {
  width: 100%;
  border-collapse: collapse;
  font-size: 13px;
}

.top__table th {
  text-align: left;
  font-weight: 500;
  color: var(--c-text-secondary);
  font-size: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid var(--c-border);
  white-space: nowrap;
}

.top__table td {
  padding: 10px;
  border-bottom: 1px solid var(--c-border);
  white-space: nowrap;
}

.top__table tbody tr:last-child td {
  border-bottom: none;
}

.top__table tbody tr:hover {
  background: #f7f9f7;
}

.col-rank {
  width: 56px;
}

.rank {
  display: inline-grid;
  place-items: center;
  width: 24px;
  height: 24px;
  border-radius: 6px;
  background: #eef1ee;
  color: var(--c-text-secondary);
  font-size: 12px;
  font-weight: 600;
}

.rank--top {
  background: #e5f0ee;
  color: var(--c-primary);
}

.name {
  max-width: 240px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.top__empty,
.top__loading {
  min-height: 120px;
  display: grid;
  place-items: center;
}

.top__loading {
  display: block;
}
</style>
