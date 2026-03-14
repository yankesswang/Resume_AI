<template>
  <div class="markdown-content" v-html="rendered"></div>
</template>

<script setup>
import { computed } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'

const props = defineProps({
  content: { type: String, default: '' },
})

marked.setOptions({
  breaks: true,
  gfm: true,
})

const rendered = computed(() => {
  if (!props.content) return ''
  const processed = props.content.replace(
    /^(#\w\S*(?:\s+#\w\S*)*)$/gm,
    (line) =>
      line
        .split(/\s+/)
        .map((tag) => `<span class="md-tag">${tag.slice(1)}</span>`)
        .join(' ')
  )
  const html = marked.parse(processed)
  return DOMPurify.sanitize(html)
})
</script>

<style scoped>
.markdown-content {
  font-size: 0.9rem;
  line-height: 1.75;
  color: #C9D1D9;
}

.markdown-content :deep(h1) {
  font-size: 1.2rem;
  font-weight: 700;
  margin: 1.2rem 0 0.5rem;
  color: #79C0FF;
}

.markdown-content :deep(h2) {
  font-size: 1.1rem;
  font-weight: 700;
  margin: 1rem 0 0.4rem;
  color: #79C0FF;
}

.markdown-content :deep(h3) {
  font-size: 1rem;
  font-weight: 700;
  margin: 0.9rem 0 0.4rem;
  color: #E6EDF3;
}

.markdown-content :deep(h4) {
  font-size: 0.95rem;
  font-weight: 700;
  margin: 0.8rem 0 0.3rem;
  color: #B1BAC4;
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 1.4rem;
  margin: 0.3rem 0;
}

.markdown-content :deep(li) {
  margin-bottom: 0.25rem;
}

.markdown-content :deep(p) {
  margin: 0.4rem 0;
}

.markdown-content :deep(.md-tag) {
  display: inline-block;
  background: #0d1f32;
  color: #58A6FF;
  border: 1px solid #1d3e6e;
  border-radius: 999px;
  padding: 1px 10px;
  font-size: 0.78rem;
  font-weight: 500;
  margin: 2px 2px;
}
</style>
