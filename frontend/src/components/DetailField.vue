<template>
  <div v-if="value" class="group py-2.5">
    <div class="text-micro text-ink-faint">{{ label }}</div>
    <div class="flex items-center gap-1">
      <span class="text-base text-ink">{{ value }}</span>
      <button
        v-if="copyable"
        class="rounded p-0.5 text-ink-faint opacity-0 transition-opacity hover:text-ink group-hover:opacity-100 focus-visible:opacity-100"
        :title="copied ? '已複製' : '複製'"
        @click.stop="doCopy"
      >
        <Copy class="h-3.5 w-3.5" :stroke-width="2" v-if="!copied" />
        <Check v-else class="h-3.5 w-3.5 text-good-ink" :stroke-width="2.5" />
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { Check, Copy } from 'lucide-vue-next'

const props = defineProps({
  label: { type: String, required: true },
  value: { type: String, default: '' },
  copyable: { type: Boolean, default: false },
})

const copied = ref(false)

async function doCopy() {
  try {
    await navigator.clipboard.writeText(props.value)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = props.value
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = true
  setTimeout(() => { copied.value = false }, 1500)
}
</script>
