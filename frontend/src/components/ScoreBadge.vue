<template>
  <span v-if="score == null" class="text-small text-ink-faint">—</span>
  <!-- Score is the primary ranking signal, so it reads as a number with a
       colour cue rather than a filled pill — pills at every severity made
       every row shout equally loudly. -->
  <span v-else class="inline-flex items-baseline gap-1 font-semibold tabular-nums" :class="toneClass">
    <span :class="size === 'large' ? 'text-display' : 'text-base'">{{ label }}</span>
    <span v-if="size === 'large'" class="text-small font-normal text-ink-faint">/ 100</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: { type: Number, default: null },
  size: { type: String, default: 'default' },
})

const toneClass = computed(() => {
  if (props.score >= 80) return 'text-good-ink'
  if (props.score >= 60) return 'text-info-ink'
  if (props.score >= 40) return 'text-warn-ink'
  return 'text-bad-ink'
})

const label = computed(() => {
  const value = Number(props.score)
  return Number.isFinite(value) ? value.toFixed(1) : '—'
})
</script>
