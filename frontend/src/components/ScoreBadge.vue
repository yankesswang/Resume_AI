<template>
  <v-chip :color="color" :variant="variant" :size="size">
    {{ label }}
  </v-chip>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  score: { type: Number, default: null },
  size: { type: String, default: 'default' },
})

const color = computed(() => {
  if (props.score == null) return 'grey'
  if (props.score >= 80) return 'success'
  if (props.score >= 60) return 'info'
  if (props.score >= 40) return 'warning'
  return 'error'
})

const variant = computed(() => (props.score == null ? 'outlined' : 'flat'))

const label = computed(() => (props.score != null ? String(Math.round(props.score)) : '--'))
</script>
