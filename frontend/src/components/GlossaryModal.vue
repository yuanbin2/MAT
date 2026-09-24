<script setup lang="ts">
defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()
</script>

<template>
  <div v-if="open" class="glossary" @click.self="emit('close')">
    <div class="glossary__panel" role="dialog" aria-modal="true" aria-label="指标口径">
      <div class="glossary__head">
        <h3 class="glossary__title">指标口径</h3>
        <button class="glossary__close" @click="emit('close')">×</button>
      </div>

      <div class="glossary__body">
        <div class="glossary__src">依据：KB-001《指标口径手册 v3》（2026-05-01 起生效）</div>

        <dl class="glossary__list">
          <div class="glossary__item">
            <dt>净营业额</dt>
            <dd>销售行金额之和 + 退款行金额之和（退款金额为负，实际相减）。</dd>
          </div>
          <div class="glossary__item">
            <dt>有效订单数</dt>
            <dd>销售行中不同订单号的个数；一张订单多行商品算 1 单，退款不计入订单。</dd>
          </div>
          <div class="glossary__item">
            <dt>客单价</dt>
            <dd>净营业额 ÷ 有效订单数，四舍五入保留 2 位；无订单时显示「—」。</dd>
          </div>
          <div class="glossary__item">
            <dt>退款归属</dt>
            <dd>退款行按退款行自己的日期、门店、商品归属，不回溯到原订单日期。</dd>
          </div>
        </dl>
      </div>
    </div>
  </div>
</template>

<style scoped>
.glossary {
  position: fixed;
  inset: 0;
  background: rgba(23, 48, 46, 0.35);
  display: grid;
  place-items: center;
  z-index: 100;
}

.glossary__panel {
  width: 480px;
  max-width: calc(100vw - 48px);
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 12px 40px rgba(0, 0, 0, 0.18);
  overflow: hidden;
}

.glossary__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 22px;
  border-bottom: 1px solid var(--c-border);
}

.glossary__title {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
}

.glossary__close {
  border: none;
  background: none;
  font-size: 22px;
  color: var(--c-text-secondary);
  cursor: pointer;
  line-height: 1;
}

.glossary__body {
  padding: 18px 22px 22px;
}

.glossary__src {
  font-size: 12px;
  color: var(--c-amber);
  margin-bottom: 14px;
}

.glossary__list {
  margin: 0;
}

.glossary__item {
  margin-bottom: 14px;
}

.glossary__item dt {
  font-weight: 600;
  color: var(--c-text);
  margin-bottom: 2px;
}

.glossary__item dd {
  margin: 0;
  color: var(--c-text-secondary);
  font-size: 13px;
}
</style>
