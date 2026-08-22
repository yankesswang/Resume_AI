<template>
  <section class="card mb-4 overflow-hidden">
    <header class="border-b border-line bg-surface-2 px-5 py-3.5">
      <h2 class="text-title font-semibold text-ink">{{ title }}</h2>
    </header>
    <div class="p-5">
      <slot />
    </div>
  </section>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  icon: { type: String, default: '' },
})
</script>
