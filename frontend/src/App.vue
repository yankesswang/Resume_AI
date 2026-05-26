<template>
  <div class="flex flex-col h-screen bg-[#0D1117] overflow-hidden">
    <!-- Navbar -->
    <header class="h-10 flex-shrink-0 bg-white border-b border-gray-200 flex items-center px-4 gap-4">
      <!-- Logo -->
      <div class="flex items-center gap-2 flex-shrink-0">
        <div class="w-5 h-5 rounded-md bg-blue-600 flex items-center justify-center">
          <svg class="w-3 h-3 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
          </svg>
        </div>
        <span class="text-sm font-semibold text-gray-900">Resume AI</span>
      </div>

      <!-- Nav -->
      <nav class="flex items-center gap-1">
        <router-link
          to="/"
          class="px-3 py-1 rounded-md text-sm font-medium transition-colors"
          :class="$route.path === '/' ? 'bg-gray-100 text-gray-900' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'"
        >
          Candidates
        </router-link>
        <router-link
          to="/unique"
          class="px-3 py-1 rounded-md text-sm font-medium transition-colors"
          :class="$route.path === '/unique' ? 'bg-gray-100 text-gray-900' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'"
        >
          Unique
        </router-link>
        <router-link
          to="/bookmarks"
          class="px-3 py-1 rounded-md text-sm font-medium transition-colors flex items-center gap-1.5"
          :class="$route.path === '/bookmarks' ? 'bg-gray-100 text-gray-900' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'"
        >
          Interested
          <span v-if="bookmarks.count" class="text-xs bg-amber-100 text-amber-700 rounded-full px-1.5 py-0.5 font-semibold leading-none">
            {{ bookmarks.count }}
          </span>
        </router-link>
        <router-link
          to="/calendar"
          class="px-3 py-1 rounded-md text-sm font-medium transition-colors flex items-center gap-1.5"
          :class="$route.path === '/calendar' ? 'bg-gray-100 text-gray-900' : 'text-gray-500 hover:text-gray-900 hover:bg-gray-50'"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          Calendar
        </router-link>
      </nav>
    </header>

    <!-- Page content -->
    <main class="flex-1 overflow-hidden">
      <router-view v-slot="{ Component, route }">
        <keep-alive include="ListView">
          <component :is="Component" :key="route.path" />
        </keep-alive>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { useBookmarkStore } from './stores/bookmarks'

const bookmarks = useBookmarkStore()
</script>
