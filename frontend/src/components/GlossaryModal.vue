<script setup lang="ts">
import { onBeforeUnmount, watch } from 'vue'

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{ (e: 'close'): void }>()

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  (open) => {
    if (open) window.addEventListener('keydown', onKeydown)
    else window.removeEventListener('keydown', onKeydown)
  },
)

onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <div v-if="open" class="glossary" @click.self="emit('close')">
    <div class="glossary__panel" role="dialog" aria-modal="true" aria-label="指标口径">
      <div class="glossary__head">
        <div>
          <h3 class="glossary__title">指标口径</h3>
          <div class="glossary__stamp">KB-001 v3</div>
        </div>
        <button class="glossary__close" aria-label="关闭" @click="emit('close')">×</button>
      </div>

      <div class="glossary__body">
        <div class="glossary__src">依据 KB-001《指标口径手册 v3》，2026-05-01 起生效</div>

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
  background: rgba(30, 46, 43, 0.3);
  display: grid;
  place-items: center;
  z-index: 100;
  padding: var(--sp-6);
  animation: fade 180ms var(--ease) both;
}

@keyframes fade {
  from {
    opacity: 0;
  }
  to {
    opacity: 1;
  }
}

.glossary__panel {
  width: 520px;
  max-width: 100%;
  background: var(--surface);
  border: 1px solid var(--rule);
  border-radius: var(--r-md);
  box-shadow: 0 16px 48px rgba(23, 75, 70, 0.16);
  overflow: hidden;
  animation: rise 260ms var(--ease) both;
}

@keyframes rise {
  from {
    opacity: 0;
    transform: translateY(10px);
  }
  to {
    opacity: 1;
    transform: none;
  }
}

/* 头部：深松绿压边，与侧栏品牌带呼应 */
.glossary__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  background: var(--pine);
  color: #f6f2e8;
}

.glossary__title {
  margin: 0;
  font-size: var(--fs-lg);
  font-weight: 600;
  letter-spacing: 0.03em;
}

.glossary__stamp {
  margin-top: 2px;
  font-size: var(--fs-2xs);
  letter-spacing: 0.16em;
  color: rgba(234, 241, 238, 0.65);
}

.glossary__close {
  border: none;
  background: none;
  font-size: 20px;
  line-height: 1;
  color: rgba(234, 241, 238, 0.8);
  cursor: pointer;
  padding: 2px 4px;
  border-radius: var(--r-xs);
  transition: color var(--dur) var(--ease);
}
.glossary__close:hover {
  color: #fff;
}

.glossary__body {
  padding: var(--sp-4) var(--sp-5) var(--sp-5);
}

.glossary__src {
  font-size: var(--fs-xs);
  color: var(--ochre);
  padding-bottom: var(--sp-3);
  margin-bottom: var(--sp-4);
  border-bottom: 1px solid var(--ochre-line);
}

.glossary__list {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.glossary__item dt {
  font-weight: 600;
  color: var(--pine);
  font-size: var(--fs-sm);
  margin-bottom: 2px;
}

.glossary__item dd {
  margin: 0;
  color: var(--ink-2);
  font-size: var(--fs-sm);
  line-height: 1.75;
}
</style>
