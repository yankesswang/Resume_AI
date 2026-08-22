<template>
  <span class="chip" :class="[config.tone, size === 'small' ? '' : 'text-small px-2 py-0.5']">
    <span class="font-semibold">T{{ tier }}</span>
    <span :class="config.dim">{{ displayLabel }}</span>
  </span>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tier: { type: Number, default: 0 },
  tierLabel: { type: String, default: '' },
  size: { type: String, default: 'default' },
})

// Tier colour climbs neutral → info → expert with rank, so a scan down the
// column reads as a gradient. Tier 0 is deliberately *neutral*, not red:
// "not an AI engineer" is the common case, not an error.
const tierConfig = {
  0: { tone: 'bg-neutral-soft text-neutral-ink border-neutral-line', dim: 'text-ink-faint', label: 'Non-AI' },
  1: { tone: 'bg-neutral-soft text-neutral-ink border-neutral-line', dim: 'opacity-70', label: 'Wrapper' },
  2: { tone: 'bg-info-soft text-info-ink border-info-line', dim: 'opacity-75', label: 'RAG Architect' },
  3: { tone: 'bg-expert-soft text-expert-ink border-expert-line', dim: 'opacity-75', label: 'AI Expert' },
}

const config = computed(() => tierConfig[props.tier] ?? tierConfig[0])
const displayLabel = computed(() => props.tierLabel || config.value.label)
</script>
