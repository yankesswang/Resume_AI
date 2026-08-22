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
/* This component renders the resume's own prose — skills, self-introduction,
   autobiography, and the AI analysis. It is the primary reading surface of
   the app, so it runs a step larger than the surrounding chrome and uses the
   semantic tokens rather than the hard-coded dark values it carried before
   (which rendered as pale grey on white once a light theme existed). */
.markdown-content {
  font-size: 1.0625rem;   /* 17px — body prose, read rather than scanned */
  line-height: 1.75;
  color: var(--color-ink);
}

.markdown-content :deep(h1) {
  font-size: 1.375rem;
  font-weight: 700;
  margin: 1.2rem 0 0.5rem;
  color: var(--color-brand-ink);
}

.markdown-content :deep(h2) {
  font-size: 1.25rem;
  font-weight: 700;
  margin: 1rem 0 0.4rem;
  color: var(--color-brand-ink);
}

.markdown-content :deep(h3) {
  font-size: 1.125rem;
  font-weight: 700;
  margin: 0.9rem 0 0.4rem;
  color: var(--color-ink);
}

.markdown-content :deep(h4) {
  font-size: 1.0625rem;
  font-weight: 700;
  margin: 0.8rem 0 0.3rem;
  color: var(--color-ink-muted);
}

.markdown-content :deep(ul),
.markdown-content :deep(ol) {
  padding-left: 1.4rem;
  margin: 0.3rem 0;
}

.markdown-content :deep(li) {
  margin-bottom: 0.35rem;
}

.markdown-content :deep(p) {
  margin: 0.5rem 0;
}

.markdown-content :deep(strong) {
  font-weight: 600;
  color: var(--color-ink);
}

.markdown-content :deep(a) {
  color: var(--color-brand-ink);
  text-decoration: underline;
}

.markdown-content :deep(code) {
  font-family: var(--font-mono);
  font-size: 0.9375em;
  background: var(--color-surface-2);
  border: 1px solid var(--color-line);
  border-radius: 4px;
  padding: 0.0625rem 0.3125rem;
}

.markdown-content :deep(.md-tag) {
  display: inline-block;
  background: var(--color-brand-soft);
  color: var(--color-brand-ink);
  border: 1px solid var(--color-brand-line);
  border-radius: 999px;
  padding: 1px 10px;
  font-size: 0.9375rem;
  font-weight: 500;
  margin: 2px 2px;
}
</style>
