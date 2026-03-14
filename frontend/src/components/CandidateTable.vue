<template>
  <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
    <!-- Table -->
    <div ref="scrollEl" class="overflow-x-auto overflow-y-auto" style="max-height: calc(100vh - 220px)">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-gray-200 bg-gray-50 sticky top-0 z-10">
            <th class="w-10 px-3 py-2.5 text-center"></th>
            <th
              v-for="col in columns"
              :key="col.key"
              class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap cursor-pointer select-none hover:text-gray-700 transition-colors"
              :style="col.width ? `width: ${col.width}` : ''"
              @click="col.sortable !== false && toggleSort(col.key)"
            >
              <span class="inline-flex items-center gap-1">
                {{ col.title }}
                <span v-if="col.sortable !== false" class="text-gray-300">
                  <template v-if="sortKey === col.key">
                    <svg v-if="sortDir === 'asc'" class="w-3 h-3 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M5 15l7-7 7 7" />
                    </svg>
                    <svg v-else class="w-3 h-3 text-blue-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                    </svg>
                  </template>
                  <svg v-else class="w-3 h-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M7 16V4m0 0L3 8m4-4l4 4M17 8v12m0 0l4-4m-4 4l-4-4" />
                  </svg>
                </span>
              </span>
            </th>
          </tr>
        </thead>
        <tbody class="divide-y divide-gray-100">
          <tr
            v-for="item in sortedCandidates"
            :key="item.id"
            class="hover:bg-blue-50/50 cursor-pointer transition-colors group"
            @click="$router.push({ name: 'detail', params: { id: item.id } })"
          >
            <!-- Bookmark + Invitation -->
            <td class="px-3 py-3 text-center" @click.stop>
              <div class="flex items-center justify-center gap-1">
                <button
                  @click="bookmarks.toggle(item.id)"
                  :class="[
                    'w-5 h-5 transition-colors',
                    bookmarks.has(item.id) ? 'text-amber-400' : 'text-gray-200 group-hover:text-gray-300'
                  ]"
                  title="Toggle bookmark"
                >
                  <svg class="w-5 h-5" :fill="bookmarks.has(item.id) ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                  </svg>
                </button>
                <button
                  @click="invitations.toggle(item.id)"
                  :class="[
                    'w-5 h-5 transition-colors',
                    invitations.has(item.id) ? 'text-emerald-500' : 'text-gray-200 group-hover:text-gray-300'
                  ]"
                  :title="invitations.has(item.id) ? '取消邀請標記' : '標記已發邀請'"
                >
                  <svg class="w-5 h-5" :fill="invitations.has(item.id) ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
                  </svg>
                </button>
              </div>
            </td>

            <!-- Name -->
            <td class="px-3 py-3">
              <div class="flex items-center gap-2.5">
                <div class="w-8 h-8 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center shrink-0 overflow-hidden">
                  <img v-if="item.photo_url" :src="item.photo_url" :alt="item.name" class="w-full h-full object-cover" />
                  <span v-else>{{ item.name?.charAt(0) || '?' }}</span>
                </div>
                <span class="font-semibold text-gray-900 whitespace-nowrap">{{ item.name }}</span>
                <span
                  v-if="bookmarks.has(item.id)"
                  class="text-xs font-semibold bg-amber-50 text-amber-600 border border-amber-200 rounded-full px-2 py-0.5 whitespace-nowrap"
                >感興趣</span>
                <span
                  v-if="invitations.has(item.id)"
                  class="text-xs font-semibold bg-emerald-50 text-emerald-600 border border-emerald-200 rounded-full px-2 py-0.5 whitespace-nowrap"
                >邀請已發</span>
              </div>
            </td>

            <!-- Age -->
            <td class="px-3 py-3 text-gray-600 tabular-nums">
              <span v-if="calcAge(item.birth_year) != null">{{ calcAge(item.birth_year) }}</span>
              <span v-else class="text-gray-300">—</span>
            </td>

            <!-- 104 Code -->
            <td class="px-3 py-3">
              <span v-if="item.code_104" class="font-mono text-xs text-gray-600 bg-gray-100 rounded px-1.5 py-0.5">{{ item.code_104 }}</span>
              <span v-else class="text-gray-300">—</span>
            </td>

            <!-- University -->
            <td class="px-3 py-3">
              <div v-if="getEdu(item, 'university')" class="text-xs">
                <div class="font-medium text-gray-900">{{ getEdu(item, 'university').school }}</div>
                <div class="text-gray-400">{{ getEdu(item, 'university').department }}</div>
              </div>
              <span v-else class="text-gray-300">—</span>
            </td>

            <!-- Masters -->
            <td class="px-3 py-3">
              <div v-if="getEdu(item, 'masters')" class="text-xs">
                <div class="font-medium text-gray-900">{{ getEdu(item, 'masters').school }}</div>
                <div class="text-gray-400">{{ getEdu(item, 'masters').department }}</div>
              </div>
              <span v-else class="text-gray-300">—</span>
            </td>

            <!-- Experience -->
            <td class="px-3 py-3 text-gray-700 whitespace-nowrap text-xs">
              {{ item.years_of_experience || '無工作經驗' }}
            </td>

            <!-- AI Tier -->
            <td class="px-3 py-3">
              <TierBadge
                v-if="item.experience_detail?.tier"
                :tier="item.experience_detail.tier"
                :tier-label="item.experience_detail.tier_label"
                size="small"
              />
              <span v-else class="text-gray-300">—</span>
            </td>

            <!-- Skills -->
            <td class="px-3 py-3">
              <div class="flex flex-wrap gap-1">
                <span
                  v-for="tag in item.skill_tags.slice(0, 5)"
                  :key="tag"
                  class="text-xs bg-indigo-50 text-indigo-700 border border-indigo-100 rounded-full px-2 py-0.5"
                >{{ tag }}</span>
                <span
                  v-if="item.skill_tags.length > 5"
                  class="text-xs text-gray-400 px-1 py-0.5"
                >+{{ item.skill_tags.length - 5 }}</span>
              </div>
            </td>

            <!-- Score -->
            <td class="px-3 py-3">
              <ScoreBadge :score="item.overall_score" />
            </td>
          </tr>

          <!-- Empty state -->
          <tr v-if="sortedCandidates.length === 0">
            <td :colspan="columns.length + 1" class="px-6 py-16 text-center text-gray-400 text-sm">
              No candidates match the current filters.
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Footer count -->
    <div v-if="sortedCandidates.length > 0" class="px-4 py-2.5 border-t border-gray-100 text-xs text-gray-400 bg-gray-50">
      {{ sortedCandidates.length }} candidate{{ sortedCandidates.length !== 1 ? 's' : '' }}
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useFilterStore } from '../stores/filters'
import { useBookmarkStore } from '../stores/bookmarks'
import { useInvitationStore } from '../stores/invitations'
import ScoreBadge from './ScoreBadge.vue'
import TierBadge from './TierBadge.vue'

const props = defineProps({
  candidates: { type: Array, default: () => [] },
})

const filters = useFilterStore()
const bookmarks = useBookmarkStore()
const invitations = useInvitationStore()

const sortKey = ref('overall_score')
const sortDir = ref('desc')

const columns = [
  { title: '姓名', key: 'name', width: '160px' },
  { title: '年齡', key: 'age', width: '70px' },
  { title: '104代碼', key: 'code_104', width: '140px' },
  { title: '大學', key: 'university', sortable: false, width: '180px' },
  { title: '碩士', key: 'masters', sortable: false, width: '180px' },
  { title: '年資', key: 'years_of_experience', width: '90px' },
  { title: 'AI Tier', key: 'ai_tier', width: '140px' },
  { title: '技能', key: 'skill_tags', sortable: false },
  { title: '分數', key: 'overall_score', width: '80px' },
]

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'desc'
  }
}

const mastersKeywords = ['碩', '研究所', 'Master', 'MBA', 'MS', 'MA']
const universityKeywords = ['大學', '⼤學', '學士', 'Bachelor', 'BS', 'BA']

function getEdu(item, type) {
  const records = item.education || []
  for (const ed of records) {
    const dl = ed.degree_level || ''
    if (type === 'masters' && mastersKeywords.some((k) => dl.includes(k))) return ed
    if (type === 'university' && universityKeywords.some((k) => dl.includes(k))) {
      const dept = ed.department || ''
      const parts = dept.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
      const undergradPart = parts.find((p) => !mastersKeywords.some((k) => p.includes(k)))
      return undergradPart ? { school: ed.school, department: undergradPart } : ed
    }
  }
  if (type === 'masters') {
    for (const ed of records) {
      const dept = ed.department || ''
      const parts = dept.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
      const mastersPart = parts.find((p) => mastersKeywords.some((k) => p.includes(k)))
      if (mastersPart) return { school: ed.school, department: mastersPart }
    }
  }
  if (records.length === 0 && item.school) {
    const major = item.major || ''
    const parts = major.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
    const mastersPart = parts.find((p) => mastersKeywords.some((k) => p.includes(k)))
    const undergradPart = parts.find((p) => !mastersKeywords.some((k) => p.includes(k)))
    if (type === 'masters' && mastersPart) return { school: item.school, department: mastersPart }
    if (type === 'university' && undergradPart) return { school: item.school, department: undergradPart }
    if (type === 'university' && !undergradPart && !mastersPart) return { school: item.school, department: major }
  }
  return null
}

function calcAge(birthYear) {
  if (!birthYear) return null
  const year = parseInt(birthYear, 10)
  if (isNaN(year) || year < 1900) return null
  return new Date().getFullYear() - year
}

function parseYearsOfExperience(raw) {
  if (!raw) return null
  const match = raw.match(/(\d+)/)
  return match ? parseInt(match[1], 10) : null
}

function matchExperienceRange(years, range) {
  if (years == null) return false
  switch (range) {
    case '0-2年': return years >= 0 && years <= 2
    case '3-5年': return years >= 3 && years <= 5
    case '5-10年': return years >= 5 && years <= 10
    case '10年+': return years > 10
    default: return true
  }
}

const TOP_UNIVERSITY_KEYWORDS = [
  // 台灣大學 (NTU)
  '台灣大學', '臺灣大學', '國立台灣大學', '國立臺灣大學',
  '台大', '臺大',
  'National Taiwan University', 'National Taiwan Univ.', 'Taiwan University',
  'NTU', 'N.T.U.', 'N T U',

  // 清華大學 (NTHU) — includes Tsinghua spelling variants
  '清華大學', '國立清華大學', '清大',
  'National Tsing Hua University', 'National Tsinghua University',
  'Tsing Hua University', 'Tsinghua University',
  'National Tsing Hua Univ.', 'National Tsinghua Univ.',
  'NTHU', 'N.T.H.U.', 'N T H U',

  // 交通大學 / 陽明交通大學 (NCTU → NYCU after 2021 merger)
  '交通大學', '國立交通大學', '交大',
  '陽明交通大學', '陽明交大', '國立陽明交通大學', '國立陽明交大', '陽交大',
  'National Chiao Tung University', 'Chiao Tung University',
  'National Chiao-Tung University', 'National Chiao Tung Univ.',
  'National Yang Ming Chiao Tung University', 'Yang Ming Chiao Tung University',
  'National Yang-Ming Chiao-Tung University', 'Yang Ming Chiao Tung Univ.',
  'NCTU', 'N.C.T.U.', 'NYCU', 'N.Y.C.U.',

  // 成功大學 (NCKU)
  '成功大學', '國立成功大學', '成大',
  'National Cheng Kung University', 'Cheng Kung University',
  'National Cheng Kung Univ.', 'National Cheng-Kung University',
  'NCKU', 'N.C.K.U.',

  // 政治大學 (NCCU)
  '政治大學', '國立政治大學', '政大',
  'National Chengchi University', 'Chengchi University',
  'National Chengchi Univ.', 'National Cheng-Chi University',
  'NCCU', 'N.C.C.U.',

  // 台灣科技大學 (NTUST / Taiwan Tech)
  '台灣科技大學', '臺灣科技大學', '國立台灣科技大學', '國立臺灣科技大學',
  '台科大', '臺科大',
  'National Taiwan University of Science and Technology',
  'National Taiwan Univ. of Science and Technology',
  'National Taiwan University of Science & Technology',
  'Taiwan Tech', 'Taiwan Tech University',
  'NTUST', 'N.T.U.S.T.',
];


// Normalize CJK compatibility variants (e.g. ⼤ U+2F23 → 大 U+5927) before matching
function normalizeHan(s) {
  return (s || '').normalize('NFKC')
}
const TOP_UNIVERSITY_KEYWORDS_NORM = TOP_UNIVERSITY_KEYWORDS.map(normalizeHan)

function isTopUniversity(candidate) {
  const edu = candidate.education || []
  for (const e of edu) {
    const school = normalizeHan(e.school)
    if (TOP_UNIVERSITY_KEYWORDS_NORM.some((k) => school.includes(k))) return true
  }
  const fallback = normalizeHan(candidate.school)
  return TOP_UNIVERSITY_KEYWORDS_NORM.some((k) => fallback.includes(k))
}

function matchScoreRange(score, range) {
  switch (range) {
    case '80+': return score != null && score >= 80
    case '60-79': return score != null && score >= 60 && score < 80
    case '40-59': return score != null && score >= 40 && score < 60
    case '<40': return score != null && score < 40
    case 'No Score': return score == null
    default: return true
  }
}

const filteredCandidates = computed(() =>
  props.candidates.filter((c) => {
    if (filters.searchName) {
      const q = filters.searchName.toLowerCase()
      if (!(c.name?.toLowerCase().includes(q) || c.code_104?.toLowerCase().includes(q))) return false
    }
    if (filters.educationLevel != null && filters.educationLevel !== '' && c.education_level !== filters.educationLevel) return false
    if (filters.selectedSkills.length > 0) {
      const tags = c.skill_tags || []
      if (!filters.selectedSkills.every((s) => tags.includes(s))) return false
    }
    if (filters.experienceRange != null && filters.experienceRange !== '') {
      if (!matchExperienceRange(parseYearsOfExperience(c.years_of_experience), filters.experienceRange)) return false
    }
    if (filters.scoreRange != null && filters.scoreRange !== '' && !matchScoreRange(c.overall_score ?? null, filters.scoreRange)) return false
    if (filters.topUniversityOnly && !isTopUniversity(c)) return false
    if (filters.aiTier && c.experience_detail?.tier !== filters.aiTier) return false
    if (filters.hardFilterPassedOnly && c.passed_hard_filter === false) return false
    if (filters.bookmarkedOnly && !bookmarks.has(c.id)) return false
    return true
  }).map((c) => ({ ...c, age: calcAge(c.birth_year), overall_score: c.overall_score ?? null }))
)

const sortedCandidates = computed(() => {
  const arr = [...filteredCandidates.value]
  const key = sortKey.value
  const dir = sortDir.value === 'asc' ? 1 : -1
  return arr.sort((a, b) => {
    let av = a[key] ?? null
    let bv = b[key] ?? null
    if (key === 'ai_tier') {
      av = a.experience_detail?.tier ?? null
      bv = b.experience_detail?.tier ?? null
    }
    if (av === null && bv === null) return 0
    if (av === null) return 1
    if (bv === null) return -1
    if (typeof av === 'string') return dir * av.localeCompare(bv)
    return dir * (av - bv)
  })
})

const scrollEl = ref(null)

defineExpose({
  filteredCount: computed(() => sortedCandidates.value.length),
  getScrollTop: () => scrollEl.value?.scrollTop ?? 0,
  setScrollTop: (top) => { if (scrollEl.value) scrollEl.value.scrollTop = top },
})
</script>
