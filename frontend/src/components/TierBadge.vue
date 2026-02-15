<template>
  <v-chip
    :color="tierColor"
    :variant="variant"
    :size="size"
    class="font-weight-bold"
  >
    <v-icon v-if="showIcon" start size="small">{{ tierIcon }}</v-icon>
    T{{ tier }} {{ tierLabel }}
  </v-chip>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  tier: { type: Number, default: 1 },
  tierLabel: { type: String, default: '' },
  size: { type: String, default: 'default' },
  variant: { type: String, default: 'flat' },
  showIcon: { type: Boolean, default: true },
})

const tierConfig = {
  1: { color: 'grey', icon: 'mdi-api', label: 'Wrapper' },
  2: { color: 'blue', icon: 'mdi-database-search', label: 'RAG Architect' },
  3: { color: 'purple', icon: 'mdi-brain', label: 'Model Tuner' },
  4: { color: 'amber-darken-2', icon: 'mdi-rocket-launch', label: 'Inference Ops' },
}

const config = computed(() => tierConfig[props.tier] || tierConfig[1])
const tierColor = computed(() => config.value.color)
const tierIcon = computed(() => config.value.icon)
const tierLabel = computed(() => props.tierLabel || config.value.label)
</script>
