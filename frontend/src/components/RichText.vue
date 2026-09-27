<script setup lang="ts">
import { computed } from 'vue'
import { parseRichText } from '../markdown'

// 只做纯文本渲染：解析出结构化片段后用普通插值画出来，不用 v-html。
const props = defineProps<{ text: string }>()
const blocks = computed(() => parseRichText(props.text || ''))
</script>

<template>
  <div class="rich">
    <p v-for="(block, i) in blocks" :key="i" class="rich__block" :class="`rich__block--${block.kind}`">
      <template v-for="(segment, j) in block.segments" :key="j">
        <strong v-if="segment.bold" class="rich__strong">{{ segment.text }}</strong>
        <code v-else-if="segment.code" class="rich__code num">{{ segment.text }}</code>
        <template v-else>{{ segment.text }}</template>
      </template>
    </p>
  </div>
</template>

<style scoped>
.rich {
  word-break: break-word;
  line-height: 1.85;
}
.rich__block {
  margin: 0;
}
.rich__block + .rich__block {
  margin-top: 4px;
}

/* 项目符号用朱色小方块，像账簿里的勾注 */
.rich__block--bullet {
  padding-left: var(--sp-4);
  position: relative;
}
.rich__block--bullet::before {
  content: '';
  position: absolute;
  left: 2px;
  top: 0.68em;
  width: 4px;
  height: 4px;
  background: var(--vermilion);
  border-radius: 1px;
}

.rich__block--heading {
  font-weight: 600;
  color: var(--pine);
  margin-top: var(--sp-3);
}

.rich__strong {
  font-weight: 600;
  color: var(--ink);
}

.rich__code {
  font-family: var(--font-mono);
  background: var(--surface-sunk);
  border: 1px solid var(--rule-soft);
  border-radius: var(--r-xs);
  padding: 0 4px;
  font-size: 0.92em;
}
</style>
