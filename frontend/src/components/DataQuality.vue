<script setup lang="ts">
import { computed } from 'vue'
import type { CleaningReport } from '../types'
import { formatNumber } from '../format'

const props = defineProps<{
  report: CleaningReport | null
  loading: boolean
}>()

// 剔除原因，顺序固定：前六类为 KB-001 §3 明文规定，后两类为补充的数据异常分类。
const reasons = [
  { key: '1_unparseable_date', label: '日期无法解析' },
  { key: '2_empty_amount', label: '金额为空' },
  { key: '3_qty_le_zero', label: '数量不大于零' },
  { key: '4_store_not_in_stores', label: '门店外键无效' },
  { key: '5_product_not_in_products', label: '商品外键无效' },
  { key: '6_duplicate_row', label: '完全重复' },
  { key: '7_unparseable_amount', label: '金额无法解析' },
  { key: '8_qty_unparseable', label: '数量无法解析' },
]

const normalizedItems = computed(() => {
  const n = props.report?.normalized
  if (!n) return []
  return [
    { label: '金额去掉 ¥ 前缀', value: n.currency_amount ?? 0 },
    { label: '门店编号大小写/空白', value: n.store_code ?? 0 },
    { label: '商品编号大小写/空白', value: n.product_code ?? 0 },
    { label: '日期格式归一', value: n.date_format ?? 0 },
  ].filter((item) => item.value > 0)
})

const removedTotal = computed(() => {
  if (!props.report) return 0
  const r = props.report.removed
  return reasons.reduce((sum, item) => sum + (r[item.key] ?? 0), 0)
})

const maxReason = computed(() => {
  if (!props.report) return 1
  return Math.max(1, ...reasons.map((item) => props.report!.removed[item.key] ?? 0))
})
</script>

<template>
  <div class="dq card">
    <div class="card__header">
      <div>
        <div class="card__title">数据质量</div>
        <div class="card__subtitle">本次数据重建的全量清洗统计（不随日期/门店筛选变化）</div>
      </div>
    </div>

    <div class="card__body">
      <div v-if="loading" class="dq__loading">
        <div v-for="i in 4" :key="i" class="skeleton" style="height: 24px; margin-bottom: 10px"></div>
      </div>

      <div v-else-if="!report" class="dq__empty muted">暂无数据质量信息</div>

      <template v-else>
        <div class="dq__summary">
          <div class="dq__stat">
            <div class="dq__stat-label">原始行数</div>
            <div class="dq__stat-value num">{{ formatNumber(report.raw_rows) }}</div>
          </div>
          <div class="dq__stat">
            <div class="dq__stat-label">保留行数</div>
            <div class="dq__stat-value num dq__stat-value--keep">{{ formatNumber(report.kept_rows) }}</div>
          </div>
          <div class="dq__stat">
            <div class="dq__stat-label">剔除行数</div>
            <div class="dq__stat-value num dq__stat-value--remove">{{ formatNumber(removedTotal) }}</div>
          </div>
          <div class="dq__stat">
            <div class="dq__stat-label">退款行数</div>
            <div class="dq__stat-value num">{{ formatNumber(report.kept_refund_rows) }}</div>
          </div>
        </div>

        <div class="dq__section-label eyebrow">剔除构成</div>

        <div class="dq__reasons">
          <div v-for="r in reasons" :key="r.key" class="dq__reason">
            <div class="dq__reason-head">
              <span class="dq__reason-label">{{ r.label }}</span>
              <span class="dq__leader" aria-hidden="true"></span>
              <span class="dq__reason-count num">{{ formatNumber(report.removed[r.key] ?? 0) }} 行</span>
            </div>
            <div class="dq__bar">
              <div
                class="dq__bar-fill"
                :style="{ width: ((report.removed[r.key] ?? 0) / maxReason) * 100 + '%' }"
              ></div>
            </div>
          </div>
        </div>

        <div v-if="normalizedItems.length" class="dq__note">
          <div class="dq__note-title">可恢复的格式问题（已规范化保留，未剔除）</div>
          <div class="dq__note-list">
            <span v-for="item in normalizedItems" :key="item.label" class="dq__note-item">
              {{ item.label }} <span class="num">{{ formatNumber(item.value) }}</span> 行
            </span>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<style scoped>
.dq__loading {
  min-height: 160px;
}

.dq__empty {
  min-height: 120px;
  display: grid;
  place-items: center;
}

/* 汇总格：2×2（本卡片位于窄栏） */
.dq__summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: var(--sp-2);
  margin-bottom: var(--sp-5);
}

.dq__stat {
  background: var(--surface-sunk);
  border-radius: var(--r-md);
  padding: 10px var(--sp-3);
}

.dq__stat-label {
  font-size: var(--fs-2xs);
  letter-spacing: 0.08em;
  color: var(--ink-3);
}

.dq__stat-value {
  margin-top: 2px;
  font-size: 18px;
  font-weight: 600;
  line-height: 1.2;
  color: var(--ink);
}

.dq__stat-value--keep {
  color: var(--pine);
}

.dq__stat-value--remove {
  color: var(--vermilion);
}

.dq__section-label {
  color: var(--ink-3);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--rule-strong);
  margin-bottom: var(--sp-3);
}

.dq__reason {
  margin-bottom: 10px;
}

/* 点线引导 */
.dq__reason-head {
  display: flex;
  align-items: baseline;
  gap: var(--sp-2);
  font-size: var(--fs-sm);
  margin-bottom: 3px;
}

.dq__reason-label {
  color: var(--ink);
}

.dq__leader {
  flex: 1;
  min-width: 12px;
  border-bottom: 1px dotted var(--rule-strong);
  transform: translateY(-3px);
}

.dq__reason-count {
  color: var(--ink-2);
  font-size: var(--fs-xs);
}

.dq__bar {
  height: 5px;
  background: #edece7;
  border-radius: 2px;
  overflow: hidden;
}

.dq__bar-fill {
  height: 100%;
  background: var(--vermilion);
  border-radius: 2px;
  transition: width 300ms var(--ease);
}

.dq__note {
  margin-top: var(--sp-5);
  padding-top: var(--sp-4);
  border-top: 1px dashed var(--rule);
}

.dq__note-title {
  font-size: var(--fs-xs);
  color: var(--ochre);
  font-weight: 600;
  margin-bottom: var(--sp-2);
}

.dq__note-list {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-2);
}

.dq__note-item {
  font-size: var(--fs-xs);
  color: var(--ink-2);
  background: var(--ochre-tint);
  border: 1px solid var(--ochre-line);
  padding: 2px var(--sp-2);
  border-radius: var(--r-sm);
}

@media (max-width: 520px) {
  .dq__summary {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
