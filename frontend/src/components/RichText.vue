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
        <strong v-if="segment.bold">{{ segment.text }}</strong>
        <code v-else-if="segment.code" class="rich__code">{{ segment.text }}</code>
        <template v-else>{{ segment.text }}</template>
      </template>
    </p>
  </div>
</template>

<style scoped>
.rich {
  word-break: break-word;
  line-height: 1.7;
}
.rich__block {
  margin: 0;
}
.rich__block + .rich__block {
  margin-top: 3px;
}
.rich__block--bullet {
  padding-left: 14px;
  position: relative;
}
.rich__block--bullet::before {
  content: '·';
  position: absolute;
  left: 4px;
  color: var(--c-text-secondary);
}
.rich__block--heading {
  font-weight: 600;
  margin-top: 8px;
}
.rich__code {
  background: #f0f2f0;
  border-radius: 4px;
  padding: 0 4px;
  font-size: 0.94em;
}
</style>
