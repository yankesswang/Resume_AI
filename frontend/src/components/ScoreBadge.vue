<template>
  <span :class="[baseClass, colorClass, sizeClass]">
    {{ label }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: { type: Number, default: null },
  size: { type: String, default: 'default' },
})

const colorClass = computed(() => {
  if (props.score == null) return 'bg-gray-100 text-gray-500 border border-gray-200'
  if (props.score >= 80) return 'bg-green-100 text-green-700'
  if (props.score >= 60) return 'bg-blue-100 text-blue-700'
  if (props.score >= 40) return 'bg-amber-100 text-amber-700'
  return 'bg-red-100 text-red-700'
})

const sizeClass = computed(() =>
  props.size === 'large' ? 'text-lg px-3 py-1' : 'text-xs px-2 py-0.5'
)

const baseClass = 'inline-flex items-center justify-center rounded-full font-semibold tabular-nums'

const label = computed(() => {
  if (props.score == null) return '--'
  const value = Number(props.score)
  return Number.isFinite(value) ? value.toFixed(1) : '--'
})
</script>
