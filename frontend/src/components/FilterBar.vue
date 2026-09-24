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
        class="filter__input"
        type="date"
        :value="start"
        :min="dataPeriod.start ?? undefined"
        :max="dataPeriod.end ?? undefined"
        @input="emit('update:start', ($event.target as HTMLInputElement).value)"
      />
    </div>

    <span class="filter__sep">至</span>

    <div class="filter__field">
      <label class="filter__label" for="end">结束日期</label>
      <input
        id="end"
        class="filter__input"
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
  gap: 12px;
  padding: 14px 18px;
  flex-wrap: wrap;
  position: relative;
}

.filter__field {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.filter__field--store {
  min-width: 200px;
  flex: 1;
}

.filter__label {
  font-size: 12px;
  color: var(--c-text-secondary);
}

.filter__input {
  height: 36px;
  padding: 0 10px;
  border: 1px solid var(--c-border);
  border-radius: 8px;
  background: #fff;
  color: var(--c-text);
  font-size: 13px;
  outline: none;
  min-width: 140px;
}

.filter__input:focus {
  border-color: var(--c-primary);
  box-shadow: 0 0 0 2px rgba(23, 75, 70, 0.12);
}

.filter__sep {
  color: var(--c-text-secondary);
  padding-bottom: 8px;
}

.filter__actions {
  display: flex;
  gap: 8px;
  margin-left: auto;
  padding-bottom: 1px;
}

.btn {
  height: 36px;
  padding: 0 18px;
  border-radius: 8px;
  border: 1px solid transparent;
  font-size: 13px;
  cursor: pointer;
  transition: background 0.15s, border-color 0.15s;
  white-space: nowrap;
}

.btn--primary {
  background: var(--c-primary);
  color: #fff;
}

.btn--primary:hover:not(:disabled) {
  background: var(--c-primary-hover);
}

.btn--primary:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.btn--ghost {
  background: #fff;
  color: var(--c-text);
  border-color: var(--c-border);
}

.btn--ghost:hover:not(:disabled) {
  border-color: var(--c-primary);
  color: var(--c-primary);
}

.btn--ghost:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.filter__hint {
  position: absolute;
  bottom: -24px;
  left: 18px;
  font-size: 12px;
  color: var(--c-red);
}
</style>
