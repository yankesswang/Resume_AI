<template>
  <div>
    <div class="flex items-center gap-2 mb-4">
      <span class="text-micro font-semibold text-ink">工程成熟度</span>
      <span :class="['text-micro font-semibold px-2 py-0.5 rounded-full', mEngColorClass]">
        M_Eng = {{ mEng }}
      </span>
    </div>

    <div v-for="dim in dimensions" :key="dim.key" class="mb-3">
      <div class="flex justify-between items-center mb-1">
        <span class="text-micro text-ink-muted">{{ dim.label }}</span>
        <span class="text-micro font-semibold text-ink">
          Level {{ dim.level }}/3
          <span class="text-ink-faint ml-1">(+{{ dim.score }})</span>
        </span>
      </div>
      <div class="bg-surface-2 rounded-full h-2 overflow-hidden">
        <div
          class="h-2 rounded-full transition-all duration-500"
          :class="dim.barColor"
          :style="{ width: `${(dim.level / 3) * 100}%` }"
        />
      </div>
      <div class="text-micro text-ink-faint mt-0.5">{{ levelLabels[dim.level] }}</div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  detail: { type: Object, default: () => ({}) },
})

const mEng = computed(() => props.detail?.m_eng ?? 0)
const mEngColorClass = computed(() => {
  const v = mEng.value
  if (v >= 0.3) return 'bg-good-soft text-good-ink'
  if (v >= 0.15) return 'bg-brand-soft text-brand-ink'
  if (v > 0) return 'bg-warn-soft text-warn-ink'
  return 'bg-surface-2 text-ink-muted'
})

const levelLabels = { 0: 'None', 1: 'Basic', 2: 'Production', 3: 'Advanced' }

const dimensions = computed(() => [
  {
    key: 'backend',
    label: 'Backend',
    level: props.detail?.backend_level ?? 0,
    score: props.detail?.backend_score ?? 0,
    barColor: 'bg-blue-500',
  },
  {
    key: 'database',
    label: 'Database',
    level: props.detail?.database_level ?? 0,
    score: props.detail?.database_score ?? 0,
    barColor: 'bg-green-500',
  },
  {
    key: 'frontend',
    label: 'Frontend',
    level: props.detail?.frontend_level ?? 0,
    score: props.detail?.frontend_score ?? 0,
    barColor: 'bg-orange-500',
  },
])
</script>
