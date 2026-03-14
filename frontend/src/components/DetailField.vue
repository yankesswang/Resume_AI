<template>
  <div v-if="value" class="py-2 px-1">
    <div class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-0.5">{{ label }}</div>
    <div class="flex items-center gap-1 group">
      <span class="text-sm text-gray-900">{{ value }}</span>
      <button
        v-if="copyable"
        class="opacity-0 group-hover:opacity-100 transition-opacity ml-1 p-0.5 rounded text-gray-400 hover:text-gray-600"
        @click.stop="doCopy"
        :title="copied ? 'Copied!' : 'Copy'"
      >
        <svg v-if="!copied" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
        </svg>
        <svg v-else class="w-3.5 h-3.5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
        </svg>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: String, default: '' },
  copyable: { type: Boolean, default: false },
})

const copied = ref(false)

async function doCopy() {
  try {
    await navigator.clipboard.writeText(props.value)
    copied.value = true
    setTimeout(() => { copied.value = false }, 1500)
  } catch {
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
