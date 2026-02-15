<template>
  <div class="engineering-matrix">
    <div class="d-flex align-center mb-3">
      <span class="text-subtitle-2 font-weight-bold">Engineering Maturity</span>
      <v-chip
        size="small"
        :color="mEngColor"
        variant="tonal"
        class="ml-2"
      >
        M_Eng = {{ mEng }}
      </v-chip>
    </div>

    <div v-for="dim in dimensions" :key="dim.key" class="mb-3">
      <div class="d-flex justify-space-between align-center mb-1">
        <span class="text-body-2">
          <v-icon size="x-small" class="mr-1">{{ dim.icon }}</v-icon>
          {{ dim.label }}
        </span>
        <span class="text-caption font-weight-bold">
          Level {{ dim.level }} / 3
          <span class="text-grey ml-1">(+{{ dim.score }})</span>
        </span>
      </div>
      <v-progress-linear
        :model-value="(dim.level / 3) * 100"
        :color="dim.color"
        height="8"
        rounded
      />
      <div class="text-caption text-grey mt-1">{{ levelLabels[dim.level] }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  detail: { type: Object, default: () => ({}) },
})

const mEng = computed(() => props.detail?.m_eng ?? 0)
const mEngColor = computed(() => {
  const v = mEng.value
  if (v >= 0.3) return 'success'
  if (v >= 0.15) return 'info'
  if (v > 0) return 'warning'
  return 'grey'
})

const levelLabels = {
  0: 'None',
  1: 'Basic',
  2: 'Production',
  3: 'Advanced',
}

const dimensions = computed(() => [
  {
    key: 'backend',
    label: 'Backend',
    icon: 'mdi-server',
    level: props.detail?.backend_level ?? 0,
    score: props.detail?.backend_score ?? 0,
    color: 'blue',
  },
  {
    key: 'database',
    label: 'Database',
    icon: 'mdi-database',
    level: props.detail?.database_level ?? 0,
    score: props.detail?.database_score ?? 0,
    color: 'green',
  },
  {
    key: 'frontend',
    label: 'Frontend',
    icon: 'mdi-monitor',
    level: props.detail?.frontend_level ?? 0,
    score: props.detail?.frontend_score ?? 0,
    color: 'orange',
  },
])
</script>
