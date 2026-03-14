<template>
  <div class="bg-white border border-gray-200 rounded-xl p-4 mb-4">
    <div class="flex flex-wrap gap-2 items-center">
      <!-- Search -->
      <div class="relative flex-shrink-0">
        <svg class="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M21 21l-4.35-4.35M17 11A6 6 0 105 11a6 6 0 0012 0z" />
        </svg>
        <input
          v-model="filters.searchName"
          type="text"
          placeholder="Name / 104 Code"
          class="pl-8 pr-3 py-1.5 text-sm border border-gray-200 rounded-lg bg-gray-50 focus:bg-white focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none transition w-44"
        />
      </div>

      <!-- Education -->
      <select
        v-model="filters.educationLevel"
        class="py-1.5 pl-2.5 pr-7 text-sm border border-gray-200 rounded-lg bg-gray-50 focus:bg-white focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none transition appearance-none w-32"
      >
        <option :value="null">Education</option>
        <option v-for="lvl in educationLevels" :key="lvl" :value="lvl">{{ lvl }}</option>
      </select>

      <!-- Experience -->
      <select
        v-model="filters.experienceRange"
        class="py-1.5 pl-2.5 pr-7 text-sm border border-gray-200 rounded-lg bg-gray-50 focus:bg-white focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none transition appearance-none w-32"
      >
        <option :value="null">Experience</option>
        <option v-for="r in experienceRanges" :key="r" :value="r">{{ r }}</option>
      </select>

      <!-- Score -->
      <select
        v-model="filters.scoreRange"
        class="py-1.5 pl-2.5 pr-7 text-sm border border-gray-200 rounded-lg bg-gray-50 focus:bg-white focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none transition appearance-none w-28"
      >
        <option :value="null">Score</option>
        <option v-for="r in scoreRanges" :key="r" :value="r">{{ r }}</option>
      </select>

      <!-- AI Tier -->
      <select
        v-model="filters.aiTier"
        class="py-1.5 pl-2.5 pr-7 text-sm border border-gray-200 rounded-lg bg-gray-50 focus:bg-white focus:border-blue-400 focus:ring-1 focus:ring-blue-400 outline-none transition appearance-none w-36"
      >
        <option :value="null">AI Tier</option>
        <option v-for="t in tierItems" :key="t.value" :value="t.value">{{ t.title }}</option>
      </select>

      <!-- Skills autocomplete -->
      <div class="relative flex-shrink-0">
        <div
          class="flex items-center gap-1.5 pl-2 pr-2 py-1.5 border rounded-lg bg-gray-50 focus-within:bg-white focus-within:ring-1 transition cursor-text"
          :class="filters.selectedSkills.length
            ? 'border-blue-300 focus-within:border-blue-400 focus-within:ring-blue-400'
            : 'border-gray-200 focus-within:border-blue-400 focus-within:ring-blue-400'"
          @click="skillInputEl?.focus()"
        >
          <svg class="w-3.5 h-3.5 text-gray-400 flex-shrink-0 pointer-events-none" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M7 7h.01M7 3h5c.512 0 1.024.195 1.414.586l7 7a2 2 0 010 2.828l-7 7a2 2 0 01-2.828 0l-7-7A1.994 1.994 0 013 12V7a4 4 0 014-4z" />
          </svg>
          <input
            ref="skillInputEl"
            v-model="skillQuery"
            @focus="onSkillFocus"
            @keydown="onSkillKeydown"
            @blur="onSkillBlur"
            placeholder="Skills…"
            autocomplete="off"
            class="bg-transparent outline-none text-sm w-20 min-w-0 placeholder-gray-400"
          />
          <span
            v-if="filters.selectedSkills.length"
            class="bg-blue-600 text-white text-xs rounded-full w-4 h-4 flex items-center justify-center font-semibold flex-shrink-0 leading-none"
          >{{ filters.selectedSkills.length }}</span>
        </div>

        <!-- Dropdown suggestions -->
        <div
          v-if="dropdownOpen && suggestions.length"
          class="absolute top-full left-0 mt-1 w-56 bg-white border border-gray-200 rounded-lg shadow-lg z-50 overflow-auto max-h-52 py-1"
        >
          <div
            v-for="(tag, i) in suggestions"
            :key="tag"
            @mousedown.prevent="addSkill(tag)"
            :class="[
              'px-3 py-1.5 text-sm cursor-pointer',
              i === activeIdx ? 'bg-blue-50 text-blue-700' : 'text-gray-700 hover:bg-gray-50'
            ]"
            v-html="highlight(tag)"
          />
          <div v-if="suggestions.length === 0" class="px-3 py-2 text-xs text-gray-400">No matches</div>
        </div>
      </div>

      <!-- Toggle buttons -->
      <div class="flex gap-1.5 flex-wrap">
        <button
          @click="filters.topUniversityOnly = !filters.topUniversityOnly"
          :class="[
            'px-3 py-1.5 text-xs font-semibold rounded-lg border transition',
            filters.topUniversityOnly
              ? 'bg-blue-600 text-white border-blue-600'
              : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
          ]"
        >頂大</button>

        <button
          @click="filters.hardFilterPassedOnly = !filters.hardFilterPassedOnly"
          :class="[
            'px-3 py-1.5 text-xs font-semibold rounded-lg border transition',
            filters.hardFilterPassedOnly
              ? 'bg-green-600 text-white border-green-600'
              : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
          ]"
        >Passed</button>

        <button
          @click="filters.bookmarkedOnly = !filters.bookmarkedOnly"
          :class="[
            'px-3 py-1.5 text-xs font-semibold rounded-lg border transition',
            filters.bookmarkedOnly
              ? 'bg-amber-500 text-white border-amber-500'
              : 'bg-white text-gray-600 border-gray-200 hover:border-gray-300'
          ]"
        >有興趣</button>

        <button
          v-if="hasActiveFilters"
          @click="filters.clearAll()"
          class="px-3 py-1.5 text-xs font-medium rounded-lg border border-gray-200 text-gray-500 hover:text-gray-700 hover:border-gray-300 transition"
        >Clear</button>
      </div>
    </div>

    <!-- Active skill chips -->
    <div v-if="filters.selectedSkills.length" class="flex flex-wrap gap-1.5 mt-2 pt-2 border-t border-gray-100">
      <span
        v-for="skill in filters.selectedSkills"
        :key="skill"
        class="inline-flex items-center gap-1 text-xs bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-2 py-0.5"
      >
        {{ skill }}
        <button
          @click="removeSkill(skill)"
          class="text-blue-400 hover:text-blue-600 leading-none"
        >×</button>
      </span>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useFilterStore } from '../stores/filters'

const filters = useFilterStore()

const props = defineProps({
  educationLevels: { type: Array, default: () => [] },
  skillTags: { type: Array, default: () => [] },
  experienceRanges: { type: Array, default: () => ['0-2年', '3-5年', '5-10年', '10年+'] },
  scoreRanges: { type: Array, default: () => ['80+', '60-79', '40-59', '<40', 'No Score'] },
})

const tierItems = [
  { title: 'T1 - Wrapper', value: 1 },
  { title: 'T2 - RAG Architect', value: 2 },
  { title: 'T3 - Model Tuner', value: 3 },
  { title: 'T4 - Inference Ops', value: 4 },
]

// --- Skill autocomplete ---
const skillQuery = ref('')
const dropdownOpen = ref(false)
const activeIdx = ref(-1)
const skillInputEl = ref(null)

// Reset highlight index when query changes
watch(skillQuery, () => { activeIdx.value = -1 })

const suggestions = computed(() => {
  const q = skillQuery.value.trim().toLowerCase()
  return props.skillTags.filter(
    (tag) => !filters.selectedSkills.includes(tag) && tag.toLowerCase().includes(q)
  )
})

function escapeHtml(str) {
  return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
}

function highlight(tag) {
  const q = skillQuery.value.trim()
  if (!q) return escapeHtml(tag)
  const idx = tag.toLowerCase().indexOf(q.toLowerCase())
  if (idx === -1) return escapeHtml(tag)
  return (
    escapeHtml(tag.slice(0, idx)) +
    '<strong class="font-semibold">' +
    escapeHtml(tag.slice(idx, idx + q.length)) +
    '</strong>' +
    escapeHtml(tag.slice(idx + q.length))
  )
}

function addSkill(tag) {
  if (tag && !filters.selectedSkills.includes(tag)) {
    filters.selectedSkills = [...filters.selectedSkills, tag]
  }
  skillQuery.value = ''
  activeIdx.value = -1
  dropdownOpen.value = false
  skillInputEl.value?.focus()
}

function removeSkill(tag) {
  filters.selectedSkills = filters.selectedSkills.filter((s) => s !== tag)
}

function onSkillFocus() {
  dropdownOpen.value = true
}

function onSkillBlur() {
  // Delay so mousedown on a suggestion fires before closing
  setTimeout(() => {
    dropdownOpen.value = false
    activeIdx.value = -1
  }, 150)
}

function onSkillKeydown(e) {
  if (e.key === 'ArrowDown') {
    e.preventDefault()
    dropdownOpen.value = true
    activeIdx.value = Math.min(activeIdx.value + 1, suggestions.value.length - 1)
  } else if (e.key === 'ArrowUp') {
    e.preventDefault()
    activeIdx.value = Math.max(activeIdx.value - 1, -1)
  } else if (e.key === 'Enter') {
    e.preventDefault()
    const target = activeIdx.value >= 0
      ? suggestions.value[activeIdx.value]
      : suggestions.value[0]
    if (target) addSkill(target)
  } else if (e.key === 'Escape') {
    e.preventDefault()
    if (dropdownOpen.value) {
      dropdownOpen.value = false
      activeIdx.value = -1
    } else {
      skillQuery.value = ''
    }
  } else if (e.key === 'Backspace' && skillQuery.value === '' && filters.selectedSkills.length > 0) {
    filters.selectedSkills = filters.selectedSkills.slice(0, -1)
  }
}

// --- Active filter indicator ---
const hasActiveFilters = computed(() =>
  filters.searchName ||
  filters.educationLevel ||
  filters.selectedSkills.length > 0 ||
  filters.experienceRange ||
  filters.scoreRange ||
  filters.aiTier ||
  filters.topUniversityOnly ||
  filters.hardFilterPassedOnly ||
  filters.bookmarkedOnly
)
</script>
