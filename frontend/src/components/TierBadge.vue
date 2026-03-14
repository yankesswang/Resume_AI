<template>
  <span :class="[baseClass, colorClass, sizeClass]">
    T{{ tier }} {{ displayLabel }}
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tier: { type: Number, default: 1 },
  tierLabel: { type: String, default: '' },
  size: { type: String, default: 'default' },
})

const tierConfig = {
  1: { color: 'bg-gray-100 text-gray-600', label: 'Wrapper' },
  2: { color: 'bg-blue-100 text-blue-700', label: 'RAG Architect' },
  3: { color: 'bg-purple-100 text-purple-700', label: 'Model Tuner' },
  4: { color: 'bg-amber-100 text-amber-700', label: 'Inference Ops' },
}

const config = computed(() => tierConfig[props.tier] || tierConfig[1])
const colorClass = computed(() => config.value.color)
const displayLabel = computed(() => props.tierLabel || config.value.label)

const baseClass = 'inline-flex items-center rounded-full font-semibold'
const sizeClass = computed(() =>
  props.size === 'small' ? 'text-xs px-2 py-0.5' : 'text-sm px-2.5 py-1'
)
</script>
