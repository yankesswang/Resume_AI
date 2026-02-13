<template>
  <v-col v-if="value" :cols="cols" :sm="sm" class="py-2">
    <div class="field-label">{{ label }}</div>
    <div class="field-value d-flex align-center">
      <span>{{ value }}</span>
      <v-btn
        v-if="copyable"
        :icon="copied ? 'mdi-check' : 'mdi-content-copy'"
        :color="copied ? 'success' : undefined"
        size="x-small"
        variant="text"
        density="compact"
        class="ml-1 copy-btn"
        @click.stop="doCopy"
      />
    </div>
  </v-col>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: String, default: '' },
  cols: { type: [String, Number], default: '6' },
  sm: { type: [String, Number], default: '4' },
  copyable: { type: Boolean, default: false },
})

const copied = ref(false)

async function doCopy() {
  try {
    await navigator.clipboard.writeText(props.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
    // fallback
    const ta = document.createElement('textarea')
    ta.value = props.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  }
}
</script>

<style scoped>
.field-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: #757575;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  margin-bottom: 2px;
}
.field-value {
  font-size: 0.95rem;
  color: rgba(0, 0, 0, 0.87);
}
.copy-btn {
  opacity: 0.4;
  transition: opacity 0.15s;
}
.field-value:hover .copy-btn {
  opacity: 1;
}
</style>
