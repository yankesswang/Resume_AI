<template>
  <v-app>
    <router-view v-slot="{ Component, route }">
      <keep-alive include="ListView">
        <component :is="Component" :key="route.path" />
      </keep-alive>
    </router-view>
  </v-app>
</template>

<script setup>
</script>
