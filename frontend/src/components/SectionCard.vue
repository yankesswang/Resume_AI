<template>
  <v-card class="mb-5" elevation="1">
    <v-card-title class="section-title d-flex align-center">
      <v-icon v-if="icon" class="mr-2" color="primary">{{ icon }}</v-icon>
      {{ title }}
    </v-card-title>
    <v-divider />
    <v-card-text class="section-body">
      <slot />
    </v-card-text>
  </v-card>
</template>

<script setup>
defineProps({
  title: { type: String, required: true },
  icon: { type: String, default: '' },
})
</script>

<style scoped>
.section-title {
  font-size: 1.1rem !important;
  font-weight: 700 !important;
  padding: 16px 20px !important;
  color: #212121;
}
.section-body {
  padding: 16px 20px !important;
  font-size: 0.95rem;
}
</style>
