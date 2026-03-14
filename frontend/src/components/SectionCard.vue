<template>
  <div class="rounded-xl border border-gray-300 bg-white shadow-sm mb-5 overflow-hidden">
    <div class="px-5 py-3.5 bg-gray-50 border-b border-gray-200 flex items-center gap-2">
      <h2 class="text-sm font-semibold text-gray-800 uppercase tracking-wide">{{ title }}</h2>
    </div>
    <div class="p-5">
      <slot />
    </div>
  </div>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  icon: { type: String, default: '' },
})
</script>
