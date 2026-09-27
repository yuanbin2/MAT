<script setup lang="ts">
import { computed } from 'vue'
import type { Store } from '../types'

const props = defineProps<{
  stores: Store[]
  start: string
  end: string
  storeId: string
  dataPeriod: { start: string | null; end: string | null }
  disabled?: boolean
}>()

const emit = defineEmits<{
  (e: 'update:start', value: string): void
  (e: 'update:end', value: string): void
  (e: 'update:storeId', value: string): void
  (e: 'query'): void
  (e: 'reset'): void
}>()

const missingDate = computed(() => !props.start || !props.end)
const invalidRange = computed(() => {
  if (!props.start || !props.end) return false
  return props.start > props.end
})

const hint = computed(() => {
  if (missingDate.value) return '请选择开始与结束日期'
  if (invalidRange.value) return '结束日期不能早于开始日期'
  return ''
})
</script>

<template>
  <div class="filter card">
    <div class="filter__field">
      <label class="filter__label" for="start">开始日期</label>
      <input
        id="start"
        class="filter__input num"
        type="date"
        :value="start"
        :min="dataPeriod.start ?? undefined"
        :max="dataPeriod.end ?? undefined"
        @input="emit('update:start', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <span class="filter__sep" aria-hidden="true">至</span>

    <div class="filter__field">
      <label class="filter__label" for="end">结束日期</label>
      <input
        id="end"
        class="filter__input num"
        type="date"
        :value="end"
        :min="dataPeriod.start ?? undefined"
        :max="dataPeriod.end ?? undefined"
        @input="emit('update:end', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <div class="filter__field filter__field--store">
      <label class="filter__label" for="store">门店</label>
      <select
        id="store"
        class="filter__input"
        :value="storeId"
        @change="emit('update:storeId', ($event.target as HTMLSelectElement).value)"
      >
        <option value="">全部门店</option>
        <option v-for="s in stores" :key="s.store_id" :value="s.store_id">
          {{ s.store_id }} · {{ s.store_name }}
        </option>
      </select>
    </div>

    <div class="filter__actions">
      <button
        class="btn btn--primary"
        :disabled="missingDate || invalidRange || disabled"
        @click="emit('query')"
      >
        查询
      </button>
      <button class="btn btn--ghost" :disabled="disabled" @click="emit('reset')">重置</button>
    </div>

    <div v-if="hint" class="filter__hint" role="alert">{{ hint }}</div>
  </div>
</template>

<style scoped>
.filter {
  display: flex;
  align-items: flex-end;
  gap: var(--sp-3);
  padding: var(--sp-4) var(--sp-5);
  flex-wrap: wrap;
  position: relative;
}

.filter__field {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}

.filter__field--store {
  min-width: 200px;
  flex: 1;
}

.filter__label {
  font-size: var(--fs-xs);
  color: var(--ink-3);
  font-weight: 500;
}

.filter__input {
  height: 36px;
  padding: 0 var(--sp-3);
  border: 1px solid var(--rule-strong);
  border-radius: var(--r-md);
  background: var(--surface);
  color: var(--ink);
  font-size: var(--fs-sm);
  outline: none;
  min-width: 140px;
  transition:
    border-color var(--dur) var(--ease),
    box-shadow var(--dur) var(--ease);
}

.filter__input:hover {
  border-color: var(--ink-3);
}

.filter__input:focus {
  border-color: var(--pine);
  box-shadow: 0 0 0 3px rgba(23, 75, 70, 0.1);
}

/* 日期指示器染成松绿，去掉原生蓝 */
.filter__input::-webkit-calendar-picker-indicator {
  opacity: 0.55;
  cursor: pointer;
}
.filter__input::-webkit-calendar-picker-indicator:hover {
  opacity: 1;
}

.filter__sep {
  color: var(--ink-3);
  padding-bottom: 9px;
  font-size: var(--fs-sm);
}

.filter__actions {
  display: flex;
  gap: var(--sp-2);
  margin-left: auto;
}

.filter__hint {
  position: absolute;
  bottom: -24px;
  left: var(--sp-5);
  font-size: var(--fs-xs);
  color: var(--vermilion);
}
</style>
