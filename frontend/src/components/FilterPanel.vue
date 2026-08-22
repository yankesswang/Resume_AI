<template>
  <div class="card mb-4">
    <!-- Primary row: the controls reached for on nearly every search. -->
    <div class="flex flex-wrap items-center gap-3 p-4">
      <div class="relative">
        <Search class="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-faint" :stroke-width="2" />
        <input
          v-model="filters.searchName"
          type="text"
          placeholder="搜尋姓名或 104 代碼"
          class="field w-64 pl-9"
        />
      </div>

      <select
        v-if="importBatches.length"
        v-model="filters.importBatchId"
        class="field w-56"
        :class="{ 'field-active': filters.importBatchId }"
      >
        <option :value="null">全部匯入批次</option>
        <option v-for="batch in importBatches" :key="batch.id" :value="batch.id">
          {{ batch.batch_name }}（{{ batch.total_candidates }}）
        </option>
      </select>

      <button
        class="btn"
        :class="filters.bookmarkedOnly ? 'btn-on' : 'btn-ghost'"
        @click="filters.bookmarkedOnly = !filters.bookmarkedOnly"
      >
        <Star class="h-3.5 w-3.5" :stroke-width="1.8" :fill="filters.bookmarkedOnly ? 'currentColor' : 'none'" />
        感興趣
      </button>

      <div class="ml-auto flex items-center gap-2">
        <button
          class="btn"
          :class="filters.advancedCount ? 'btn-on' : 'btn-ghost'"
          @click="filters.panelOpen = !filters.panelOpen"
        >
          <Filter class="h-3.5 w-3.5" :stroke-width="2" />
          進階篩選
          <span v-if="filters.advancedCount" class="chip border-transparent bg-brand text-white">
            {{ filters.advancedCount }}
          </span>
          <ChevronDown class="h-3 w-3 transition-transform" :class="{ 'rotate-180': filters.panelOpen }" :stroke-width="2.5" />
        </button>

        <button v-if="hasActiveFilters" class="btn btn-ghost" @click="filters.clearAll()">清除全部</button>
      </div>
    </div>

    <!-- While the panel is collapsed, every active advanced condition still
         shows as a removable chip — a hidden filter must never silently
         narrow the table with no indication on screen. -->
    <div v-if="!filters.panelOpen && activeChips.length" class="flex flex-wrap items-center gap-2 border-t border-line px-4 py-3">
      <span
        v-for="chip in activeChips"
        :key="chip.key"
        class="chip border-brand-line bg-brand-soft py-0.5 pl-2 pr-1 text-brand-ink"
      >
        <span v-if="chip.label" class="opacity-60">{{ chip.label }}</span>
        {{ chip.value }}
        <button class="rounded px-0.5 leading-none opacity-60 transition-opacity hover:opacity-100" title="清除此條件" @click="chip.clear()">×</button>
      </span>
    </div>

    <!-- Advanced panel -->
    <div v-if="filters.panelOpen" class="space-y-4 border-t border-line p-4">
      <div class="grid gap-x-4 gap-y-2 sm:grid-cols-2 lg:grid-cols-3">
        <label class="flex items-center gap-2">
          <span class="w-14 shrink-0 text-micro text-ink-muted">學歷</span>
          <select v-model="filters.educationLevel" class="field min-w-0 flex-1" :class="{ 'field-active': isSet(filters.educationLevel) }">
            <option :value="null">不限</option>
            <option v-for="lvl in educationLevels" :key="lvl" :value="lvl">{{ lvl }}</option>
          </select>
        </label>

        <label class="flex items-center gap-2">
          <span class="w-14 shrink-0 text-micro text-ink-muted">年資</span>
          <select v-model="filters.experienceRange" class="field min-w-0 flex-1" :class="{ 'field-active': isSet(filters.experienceRange) }">
            <option :value="null">不限</option>
            <option v-for="r in experienceRanges" :key="r" :value="r">{{ r }}</option>
          </select>
        </label>

        <label class="flex items-center gap-2">
          <span class="w-14 shrink-0 text-micro text-ink-muted">分數</span>
          <select v-model="filters.scoreRange" class="field min-w-0 flex-1" :class="{ 'field-active': isSet(filters.scoreRange) }">
            <option :value="null">不限</option>
            <option v-for="r in scoreRanges" :key="r" :value="r">{{ scoreRangeLabel(r) }}</option>
          </select>
        </label>

        <label class="flex items-center gap-2">
          <span class="w-14 shrink-0 text-micro text-ink-muted">AI Tier</span>
          <select v-model="filters.aiTier" class="field min-w-0 flex-1" :class="{ 'field-active': isSet(filters.aiTier) }">
            <option :value="null">不限</option>
            <option v-for="t in tierItems" :key="t.value" :value="t.value">{{ t.title }}</option>
          </select>
        </label>

        <label class="flex items-center gap-2">
          <span class="w-14 shrink-0 text-micro text-ink-muted">身分</span>
          <select v-model="filters.candidateType" class="field min-w-0 flex-1" :class="{ 'field-active': isSet(filters.candidateType) }">
            <option :value="null">不限</option>
            <option value="實習">實習</option>
            <option value="正職">工程師</option>
          </select>
        </label>

        <label class="flex items-center gap-2">
          <span class="w-14 shrink-0 text-micro text-ink-muted">年齡</span>
          <select v-model="filters.ageRange" class="field min-w-0 flex-1" :class="{ 'field-active': isSet(filters.ageRange) }">
            <option :value="null">不限</option>
            <option v-for="r in ageRanges" :key="r" :value="r">{{ ageRangeLabel(r) }}</option>
          </select>
        </label>

        <div class="flex items-center gap-2">
          <span class="w-14 shrink-0 text-micro text-ink-muted">技能</span>
          <div class="relative min-w-0 flex-1">
            <div
              class="field flex cursor-text items-center gap-1.5"
              :class="{ 'field-active': filters.selectedSkills.length }"
              @click="skillInputEl?.focus()"
            >
              <input
                ref="skillInputEl"
                v-model="skillQuery"
                placeholder="搜尋技能…"
                autocomplete="off"
                class="min-w-0 flex-1 bg-transparent text-small text-ink outline-none placeholder:text-ink-faint"
                @focus="onSkillFocus"
                @keydown="onSkillKeydown"
                @blur="onSkillBlur"
              />
              <span v-if="filters.selectedSkills.length" class="chip border-transparent bg-brand text-white">
                {{ filters.selectedSkills.length }}
              </span>
            </div>

            <div
              v-if="dropdownOpen && suggestions.length"
              class="absolute left-0 top-full z-50 mt-1 max-h-52 w-60 overflow-auto rounded-card border border-line-strong bg-surface-3 py-1 shadow-xl"
            >
              <div
                v-for="(tag, i) in suggestions"
                :key="tag"
                class="cursor-pointer px-3 py-1.5 text-small"
                :class="i === activeIdx ? 'bg-brand-soft text-brand-ink' : 'text-ink-muted hover:bg-surface-2 hover:text-ink'"
                @mousedown.prevent="addSkill(tag)"
                v-html="highlight(tag)"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Dedupe is one mutually exclusive choice, so a segmented control
           replaces the separate toggle buttons it used to be. -->
      <div class="flex flex-wrap items-center gap-2">
        <span class="w-14 shrink-0 text-micro text-ink-muted">去重</span>
        <div class="inline-flex overflow-hidden rounded-control border border-line">
          <button
            v-for="opt in dedupeOptions"
            :key="opt.value ?? 'all'"
            class="border-r border-line px-3 py-1.5 text-micro font-medium transition-colors last:border-r-0"
            :class="filters.dedupeStatus === opt.value
              ? 'bg-brand-soft text-brand-ink'
              : 'bg-surface-2 text-ink-muted hover:text-ink'"
            @click="filters.dedupeStatus = opt.value"
          >{{ opt.label }}</button>
        </div>
      </div>

      <div class="flex flex-wrap items-center gap-2">
        <span class="w-14 shrink-0 text-micro text-ink-muted">其他</span>
        <button
          class="btn"
          :class="filters.topUniversityOnly ? 'btn-on' : 'btn-ghost'"
          @click="filters.topUniversityOnly = !filters.topUniversityOnly"
        >頂尖大學</button>
        <button
          class="btn"
          :class="filters.hardFilterPassedOnly ? 'btn-on' : 'btn-ghost'"
          @click="filters.hardFilterPassedOnly = !filters.hardFilterPassedOnly"
        >通過硬性條件</button>

        <button v-if="filters.advancedCount" class="btn btn-ghost ml-auto" @click="filters.clearAdvanced()">
          重設進階篩選
        </button>
      </div>

      <div v-if="filters.selectedSkills.length" class="flex flex-wrap gap-1.5 border-t border-line pt-2.5">
        <span
          v-for="skill in filters.selectedSkills"
          :key="skill"
          class="chip border-brand-line bg-brand-soft py-0.5 pl-2 pr-1 text-brand-ink"
        >
          {{ skill }}
          <button class="rounded px-0.5 leading-none opacity-60 transition-opacity hover:opacity-100" title="移除" @click="removeSkill(skill)">×</button>
        </span>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useFilterStore } from '../stores/filters'
import { ChevronDown, Filter, Search, Star } from 'lucide-vue-next'

const filters = useFilterStore()

const props = defineProps({
  educationLevels: { type: Array, default: () => [] },
  skillTags: { type: Array, default: () => [] },
  experienceRanges: { type: Array, default: () => ['0-2年', '3-5年', '5-10年', '10年+'] },
  scoreRanges: { type: Array, default: () => ['80+', '60-79', '40-59', '<40', 'No Score'] },
  importBatches: { type: Array, default: () => [] },
  // [{value, label}] from /api/filters, named by the active job's domain
  // profile. Empty falls back to the AI ladder below.
  aiTiers: { type: Array, default: () => [] },
})

// Local, not a prop: unlike the score/experience ranges the API supplies, age
// bands are derived client-side from birth_year. Split around the pool's shape
// — it is overwhelmingly 22-30, so one wide "20-30" bucket would sort nobody.
const ageRanges = ['~24', '25-29', '30-34', '35-39', '40+']

// Tier names belong to the active job's scoring standard, not to this
// component: a sales role calls level 2 「獨立業務」, not "RAG Architect".
// The API supplies them; these four are the fallback for a job with no domain
// profile, which is exactly when the pipeline runs the AI scorers.
const FALLBACK_TIERS = [
  { title: 'T0 - Non-AI', value: 0 },
  { title: 'T1 - Wrapper', value: 1 },
  { title: 'T2 - RAG Architect', value: 2 },
  { title: 'T3 - AI Expert', value: 3 },
]

const tierItems = computed(() =>
  props.aiTiers.length
    ? props.aiTiers.map((t) => ({ title: `T${t.value} - ${t.label}`, value: t.value }))
    : FALLBACK_TIERS
)

const dedupeOptions = [
  { label: '全部', value: null },
  { label: '新履歷', value: 'unique' },
  { label: '重複', value: 'duplicate' },
  { label: '待確認', value: 'review' },
]

// Tier 0 is a legitimate selection, so emptiness is checked explicitly rather
// than by falsiness — `filters.aiTier === 0` must still read as "set".
function isSet(value) {
  return value != null && value !== ''
}

// The API returns this range key in English; the UI is Chinese.
function scoreRangeLabel(range) {
  return range === 'No Score' ? '尚未評分' : range
}

function ageRangeLabel(range) {
  if (range === '~24') return '24 歲以下'
  if (range === '40+') return '40 歲以上'
  return `${range} 歲`
}

// --- Chips summarising the collapsed panel's active filters ---
const activeChips = computed(() => {
  const chips = []
  const add = (key, label, value, clear) => chips.push({ key, label, value, clear })

  if (filters.educationLevel) {
    add('edu', '學歷', filters.educationLevel, () => { filters.educationLevel = null })
  }
  if (filters.experienceRange) {
    add('exp', '經驗', filters.experienceRange, () => { filters.experienceRange = null })
  }
  if (filters.scoreRange) {
    add('score', '分數', scoreRangeLabel(filters.scoreRange), () => { filters.scoreRange = null })
  }
  if (filters.aiTier != null && filters.aiTier !== '') {
    const tier = tierItems.value.find((t) => t.value === filters.aiTier)
    add('tier', 'AI', tier ? tier.title : filters.aiTier, () => { filters.aiTier = null })
  }
  if (filters.candidateType) {
    add(
      'type',
      '身分',
      filters.candidateType === '正職' ? '工程師' : filters.candidateType,
      () => { filters.candidateType = null },
    )
  }
  if (filters.ageRange) {
    add('age', '年齡', ageRangeLabel(filters.ageRange), () => { filters.ageRange = null })
  }
  if (filters.dedupeStatus) {
    const opt = dedupeOptions.find((o) => o.value === filters.dedupeStatus)
    add('dedupe', '去重', opt ? opt.label : filters.dedupeStatus, () => { filters.dedupeStatus = null })
  }
  if (filters.topUniversityOnly) {
    add('top', '', '頂尖大學', () => { filters.topUniversityOnly = false })
  }
  if (filters.hardFilterPassedOnly) {
    add('hard', '', '通過硬性條件', () => { filters.hardFilterPassedOnly = false })
  }
  for (const skill of filters.selectedSkills) {
    add(`skill:${skill}`, '技能', skill, () => removeSkill(skill))
  }
  return chips
})

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
  Boolean(
    filters.searchName ||
    filters.bookmarkedOnly ||
    filters.importBatchId ||
    filters.advancedCount
  )
)
</script>
