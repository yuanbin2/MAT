<script setup lang="ts">
// 侧栏：经营总览 与 AI 助手 两个页面。
defineProps<{ active: string }>()
defineEmits<{ (e: 'navigate', view: 'overview' | 'assistant'): void }>()
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand__mark serif" aria-hidden="true">M</div>
      <div class="brand__text">
        <div class="brand__name">Moneki.ai</div>
        <div class="brand__sub">经营分析系统</div>
      </div>
    </div>

    <nav class="nav">
      <div class="nav__label">经营报表</div>
      <a
        class="nav__item"
        :class="{ 'nav__item--active': active === 'overview' }"
        href="#"
        @click.prevent="$emit('navigate', 'overview')"
      >
        <span class="nav__icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <path d="M3 16.5h14" />
            <path d="M4.5 16.5v-5.5M9 16.5V7M13.5 16.5v-8" />
          </svg>
        </span>
        经营总览
      </a>

      <div class="nav__label nav__label--gap">智能问答</div>
      <a
        class="nav__item"
        :class="{ 'nav__item--active': active === 'assistant' }"
        href="#"
        @click.prevent="$emit('navigate', 'assistant')"
      >
        <span class="nav__icon" aria-hidden="true">
          <svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">
            <path d="M4 5.5h12a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H9l-3.5 3v-3H4A1.5 1.5 0 0 1 2.5 13V7A1.5 1.5 0 0 1 4 5.5Z" />
            <path d="M6.5 9.5h7M6.5 12h4" />
          </svg>
        </span>
        AI 助手
      </a>
    </nav>

    <div class="sidebar__foot">
      <div class="sidebar__foot-item">
        <span class="sidebar__foot-label">业务日期</span>
        <span class="num">2026-09-01</span>
      </div>
      <div class="sidebar__foot-item">
        <span class="sidebar__foot-label">指标口径</span>
        <span>KB-001 v3</span>
      </div>
    </div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 224px;
  flex-shrink: 0;
  background: linear-gradient(180deg, #16463f 0%, var(--pine-deep) 100%);
  color: #dce7e2;
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: sticky;
  top: 0;
}

/* —— 品牌 —— */
.brand {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  padding: var(--sp-5) var(--sp-5);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.brand__mark {
  width: 34px;
  height: 34px;
  display: grid;
  place-items: center;
  border-radius: var(--r-md);
  background: var(--sand);
  color: #0f3733;
  font-size: 17px;
  font-weight: 700;
  line-height: 1;
}

.brand__name {
  font-weight: 600;
  font-size: 15px;
  color: #fff;
  letter-spacing: 0.02em;
}

.brand__sub {
  margin-top: 1px;
  font-size: var(--fs-2xs);
  letter-spacing: 0.08em;
  color: rgba(220, 231, 226, 0.6);
}

/* —— 导航 —— */
.nav {
  padding: var(--sp-5) var(--sp-3);
  display: flex;
  flex-direction: column;
}

.nav__label {
  font-size: var(--fs-2xs);
  letter-spacing: 0.12em;
  color: rgba(220, 231, 226, 0.45);
  padding: 0 var(--sp-3) var(--sp-2);
}

.nav__label--gap {
  padding-top: var(--sp-5);
}

.nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px var(--sp-3);
  border-radius: var(--r-md);
  color: rgba(220, 231, 226, 0.85);
  text-decoration: none;
  font-size: var(--fs-md);
  margin-bottom: 2px;
  transition:
    background var(--dur) var(--ease),
    color var(--dur) var(--ease);
}

.nav__item:hover {
  background: rgba(255, 255, 255, 0.07);
  color: #fff;
}

.nav__item--active {
  background: rgba(255, 255, 255, 0.12);
  color: #fff;
  font-weight: 600;
}

.nav__icon {
  display: grid;
  place-items: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  opacity: 0.75;
}

.nav__item--active .nav__icon {
  opacity: 1;
  color: var(--sand);
}

/* —— 页脚 —— */
.sidebar__foot {
  margin-top: auto;
  padding: var(--sp-4) var(--sp-5);
  border-top: 1px solid rgba(255, 255, 255, 0.08);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  font-size: var(--fs-xs);
  color: rgba(220, 231, 226, 0.85);
}

.sidebar__foot-item {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  gap: var(--sp-2);
}

.sidebar__foot-label {
  font-size: var(--fs-2xs);
  letter-spacing: 0.08em;
  color: rgba(220, 231, 226, 0.45);
}

@media (max-width: 900px) {
  .sidebar {
    width: 176px;
  }
  .brand,
  .nav,
  .sidebar__foot {
    padding-left: var(--sp-3);
    padding-right: var(--sp-3);
  }
}
</style>
