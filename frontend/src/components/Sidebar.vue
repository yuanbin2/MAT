<script setup lang="ts">
// 侧栏：经营总览 与 AI 助手 两个页面。
defineProps<{ active: string }>()
defineEmits<{ (e: 'navigate', view: 'overview' | 'assistant'): void }>()
</script>

<template>
  <aside class="sidebar">
    <div class="brand">
      <div class="brand__mark">M</div>
      <div class="brand__text">
        <div class="brand__name">Moneki.ai</div>
        <div class="brand__sub">经营分析</div>
      </div>
    </div>

    <nav class="nav">
      <div class="nav__label">报表</div>
      <a
        class="nav__item"
        :class="{ 'nav__item--active': active === 'overview' }"
        href="#"
        @click.prevent="$emit('navigate', 'overview')"
      >
        <span class="nav__dot" aria-hidden="true"></span>
        经营总览
      </a>
    </nav>

    <div class="nav">
      <div class="nav__label">智能</div>
      <a
        class="nav__item"
        :class="{ 'nav__item--active': active === 'assistant' }"
        href="#"
        @click.prevent="$emit('navigate', 'assistant')"
      >
        <span class="nav__dot" aria-hidden="true"></span>
        AI 助手
      </a>
    </div>

    <div class="sidebar__foot muted">业务日期 2026-09-01</div>
  </aside>
</template>

<style scoped>
.sidebar {
  width: 220px;
  flex-shrink: 0;
  background: var(--c-primary);
  color: #eaf1ee;
  display: flex;
  flex-direction: column;
  height: 100vh;
  position: sticky;
  top: 0;
}

.brand {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 22px 20px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.brand__mark {
  width: 36px;
  height: 36px;
  border-radius: 8px;
  background: #fff;
  color: var(--c-primary);
  font-weight: 700;
  font-size: 20px;
  display: grid;
  place-items: center;
}

.brand__name {
  font-weight: 600;
  font-size: 15px;
  color: #fff;
  letter-spacing: 0.02em;
}

.brand__sub {
  font-size: 12px;
  color: rgba(234, 241, 238, 0.7);
}

.nav {
  padding: 16px 12px;
}

.nav__label {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: rgba(234, 241, 238, 0.5);
  padding: 0 12px 8px;
}

.nav__item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 12px;
  border-radius: 8px;
  color: #eaf1ee;
  text-decoration: none;
  font-size: 14px;
  margin-bottom: 2px;
}

.nav__item--active {
  background: rgba(255, 255, 255, 0.14);
  font-weight: 600;
}

.nav__item--soon {
  color: rgba(234, 241, 238, 0.55);
  cursor: default;
}

.nav__dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.4);
}

.nav__item--active .nav__dot {
  background: #e9b97a;
}

.nav__tag {
  margin-left: auto;
  font-size: 11px;
  padding: 1px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.12);
  color: rgba(234, 241, 238, 0.7);
}

.sidebar__foot {
  margin-top: auto;
  padding: 16px 20px;
  font-size: 12px;
  color: rgba(234, 241, 238, 0.55);
}
</style>
