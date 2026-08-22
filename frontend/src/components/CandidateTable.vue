<template>
  <div class="card overflow-hidden">
    <div ref="scrollEl" class="overflow-auto" style="max-height: calc(100dvh - 280px)">
      <table class="w-full table-fixed border-collapse text-small">
        <thead>
          <tr class="sticky top-0 z-10 bg-surface-2">
            <th class="w-11 border-b border-line px-2.5 py-3"></th>
            <th
              v-for="col in columns"
              :key="col.key"
              class="border-b border-line px-4 py-3 text-micro font-semibold text-ink-muted whitespace-nowrap"
              :class="[
                col.sortable !== false ? 'cursor-pointer select-none hover:text-ink' : '',
                col.align === 'right' ? 'text-right' : 'text-left',
              ]"
              :style="col.width ? `width: ${col.width}` : ''"
              @click="col.sortable !== false && toggleSort(col.key)"
            >
              <span class="inline-flex items-center gap-1" :class="col.align === 'right' ? 'flex-row-reverse' : ''">
                {{ col.title }}
                <!-- Only the active sort shows an arrow. The old table drew a
                     faint glyph on every sortable header, which added nine
                     competing marks to the busiest row on screen. -->
                <ChevronDown class="h-3 w-3 text-brand-ink" :class="{ 'rotate-180': sortDir === 'asc' }" :stroke-width="3" v-if="col.sortable !== false && sortKey === col.key" />
              </span>
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in pagedCandidates"
            :key="item.id"
            class="group cursor-pointer border-b border-line/60 transition-colors hover:bg-surface-2"
            @click="$router.push({ name: 'detail', params: { id: item.id } })"
          >
            <!-- Row actions. Both were always-visible grey glyphs before; now
                 an unset action only appears on hover, while a *set* one stays
                 lit — so the column reads as "who is marked", not as chrome. -->
            <td class="px-2.5 py-3.5 align-middle" @click.stop>
              <div class="flex items-center justify-center gap-0.5">
                <button
                  class="rounded p-1 transition-colors"
                  :class="bookmarks.has(item.id)
                    ? 'text-warn-ink'
                    : 'text-ink-faint opacity-0 hover:text-ink group-hover:opacity-100 focus-visible:opacity-100'"
                  :title="bookmarks.has(item.id) ? '取消標記感興趣' : '標記為感興趣'"
                  @click="bookmarks.toggle(item.id)"
                >
                  <Star class="h-4 w-4" :stroke-width="1.8" :fill="bookmarks.has(item.id) ? 'currentColor' : 'none'" />
                </button>
                <button
                  class="rounded p-1 transition-colors"
                  :class="invitations.has(item.id)
                    ? 'text-good-ink'
                    : 'text-ink-faint opacity-0 hover:text-ink group-hover:opacity-100 focus-visible:opacity-100'"
                  :title="invitations.has(item.id) ? '取消邀請標記' : '標記已發邀請'"
                  @click="invitations.toggle(item.id)"
                >
                  <Mail class="h-4 w-4" :stroke-width="1.8" :fill="invitations.has(item.id) ? 'currentColor' : 'none'" />
                </button>
              </div>
            </td>

            <!-- Name. Previously this one cell carried up to six chips —
                 感興趣 / 實習 / dedupe / 分數 / 邀請已發 — three of which
                 duplicated a dedicated column or the row-action icons beside
                 it. Only 身分 and a non-unique dedupe verdict remain: the two
                 that have no other home. -->
            <td class="px-4 py-3.5">
              <div class="flex items-center gap-2.5">
                <div class="flex h-9 w-9 shrink-0 items-center justify-center overflow-hidden rounded-lg bg-surface-3 text-small font-semibold text-ink-muted">
                  <img v-if="item.photo_url" :src="item.photo_url" :alt="item.name" class="h-full w-full object-cover" />
                  <span v-else>{{ item.name?.charAt(0) || '?' }}</span>
                </div>
                <div class="min-w-0">
                  <div class="flex items-center gap-1.5">
                    <span class="truncate font-medium text-ink">{{ item.name }}</span>
                    <span
                      v-if="item.dedupe_status && item.dedupe_status !== 'unique'"
                      class="chip"
                      :class="dedupeChipClass(item.dedupe_status)"
                    >{{ dedupeLabel(item.dedupe_status) }}</span>
                  </div>
                  <div class="flex items-center gap-1.5 text-micro text-ink-faint">
                    <span v-if="item.candidate_type">{{ item.candidate_type === '實習' ? '實習' : '工程師' }}</span>
                    <span v-if="item.candidate_type && item.code_104" class="opacity-40">·</span>
                    <span v-if="item.code_104" class="truncate font-mono">{{ item.code_104 }}</span>
                  </div>
                </div>
              </div>
            </td>

            <td class="px-4 py-3.5 text-ink-muted">
              <span v-if="calcAge(item.birth_year) != null">{{ calcAge(item.birth_year) }}</span>
              <span v-else class="text-ink-faint">—</span>
            </td>

            <td class="px-4 py-3.5">
              <div v-if="getEdu(item, 'university')" class="min-w-0">
                <div class="truncate text-ink">{{ getEdu(item, 'university').school }}</div>
                <div class="truncate text-micro text-ink-faint">{{ getEdu(item, 'university').department }}</div>
              </div>
              <span v-else class="text-ink-faint">—</span>
            </td>

            <td class="px-4 py-3.5">
              <div v-if="getEdu(item, 'masters')" class="min-w-0">
                <div class="truncate text-ink">{{ getEdu(item, 'masters').school }}</div>
                <div class="truncate text-micro text-ink-faint">{{ getEdu(item, 'masters').department }}</div>
              </div>
              <span v-else class="text-ink-faint">—</span>
            </td>

            <td class="whitespace-nowrap px-4 py-3.5 text-ink-muted">
              <span v-if="item.years_of_experience">{{ item.years_of_experience }}</span>
              <span v-else class="text-ink-faint">無經驗</span>
            </td>

            <td class="px-4 py-3.5">
              <TierBadge
                v-if="item.experience_detail?.tier != null"
                :tier="item.experience_detail.tier"
                :tier-label="item.experience_detail.tier_label"
                size="small"
              />
              <span v-else class="text-ink-faint">—</span>
            </td>

            <td class="px-4 py-3.5">
              <div v-if="item.skill_tags?.length" class="flex flex-wrap items-center gap-1">
                <span
                  v-for="tag in item.skill_tags.slice(0, 4)"
                  :key="tag"
                  class="chip border-line bg-surface-2 text-ink-muted"
                >{{ tag }}</span>
                <span
                  v-if="item.skill_tags.length > 4"
                  class="text-micro text-ink-faint"
                  :title="item.skill_tags.slice(4).join('、')"
                >+{{ item.skill_tags.length - 4 }}</span>
              </div>
              <span v-else class="text-ink-faint">—</span>
            </td>

            <td class="px-4 py-3.5 text-right">
              <ScoreBadge :score="item.overall_score" />
            </td>
          </tr>

          <tr v-if="sortedCandidates.length === 0">
            <td :colspan="columns.length + 1" class="px-6 py-20 text-center">
              <p class="text-base text-ink-muted">沒有符合條件的人選</p>
              <p class="mt-1 text-small text-ink-faint">試著放寬或清除上方的篩選條件</p>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <!-- Pager. Shown only when there is more than one page, so a filtered-down
         result set does not grow a control that cannot do anything. -->
    <div
      v-if="pageCount > 1"
      class="flex items-center justify-between gap-3 border-t border-line bg-surface-2 px-4 py-3"
    >
      <span class="text-micro text-ink-muted tabular-nums">
        {{ rangeStart }}-{{ rangeEnd }} / 共 {{ sortedCandidates.length }} 位
      </span>
      <div class="flex items-center gap-1.5">
        <button class="btn btn-ghost" :disabled="page === 1" @click="goPage(1)">最前</button>
        <button class="btn btn-ghost" :disabled="page === 1" @click="goPage(page - 1)">上一頁</button>
        <span class="px-2 text-micro text-ink-muted tabular-nums">
          {{ page }} / {{ pageCount }}
        </span>
        <button class="btn btn-ghost" :disabled="page === pageCount" @click="goPage(page + 1)">下一頁</button>
        <button class="btn btn-ghost" :disabled="page === pageCount" @click="goPage(pageCount)">最後</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useFilterStore } from '../stores/filters'
import { useBookmarkStore } from '../stores/bookmarks'
import { useInvitationStore } from '../stores/invitations'
import ScoreBadge from './ScoreBadge.vue'
import TierBadge from './TierBadge.vue'
import { ChevronDown, Mail, Star } from 'lucide-vue-next'

const props = defineProps({
  candidates: { type: Array, default: () => [] },
})

const filters = useFilterStore()
const bookmarks = useBookmarkStore()
const invitations = useInvitationStore()

const sortKey = ref('overall_score')
const sortDir = ref('desc')

const columns = [
  { title: '姓名', key: 'name', width: '150px' },
  { title: '年齡', key: 'age', width: '56px' },
  { title: '大學', key: 'university', sortable: false, width: '160px' },
  { title: '碩士', key: 'masters', sortable: false, width: '160px' },
  { title: '年資', key: 'years_of_experience', width: '84px' },
  { title: 'AI Tier', key: 'ai_tier', width: '132px' },
  { title: '技能', key: 'skill_tags', sortable: false, width: '200px' },
  { title: '總分', key: 'overall_score', width: '80px', align: 'right' },
]

function toggleSort(key) {
  if (sortKey.value === key) {
    sortDir.value = sortDir.value === 'asc' ? 'desc' : 'asc'
  } else {
    sortKey.value = key
    sortDir.value = 'desc'
  }
}

// Each education row arrives tagged with `degree_rank` (phd/master/bachelor/
// associate/high_school) by the backend's normalise_degree() — the same ladder
// the min_education hard filter gates on. The keyword lists that used to live
// here knew nothing of 四技/二技 or 博士班, so a university-of-technology
// graduate showed a blank 大學 column and a PhD appeared in neither.
//
// A doctorate counts as postgraduate for the 碩士 column: the alternative is
// showing the highest qualification nowhere at all.
const MASTERS_RANKS = ['master', 'phd']
const UNIVERSITY_RANKS = ['bachelor']

function isRank(row, ranks) {
  return ranks.includes(row?.degree_rank)
}

// Department text still needs splitting when one row packs both degrees into
// "資訊工程學系、資訊工程學系碩士班"; degree_rank describes the row, not each
// comma-separated part, so this narrow keyword check stays for that job only.
const mastersKeywords = ['碩', '博', '研究所', 'Master', 'MBA', 'MS', 'MA', 'PhD']

function getEdu(item, type) {
  const records = item.education || []
  for (const ed of records) {
    if (type === 'masters' && isRank(ed, MASTERS_RANKS)) return ed
    if (type === 'university' && isRank(ed, UNIVERSITY_RANKS)) {
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

function dedupeLabel(status) {
  if (status === 'duplicate') return '重複'
  if (status === 'review') return '待確認'
  return '唯一'
}

// 'unique' is the expected outcome and is no longer badged at all — badging
// the normal case on every row is what made the dedupe verdict unreadable.
function dedupeChipClass(status) {
  if (status === 'duplicate') return 'bg-bad-soft text-bad-ink border-bad-line'
  return 'bg-warn-soft text-warn-ink border-warn-line'
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

// School rank comes from the API as `school_tier` (A/B/C/D), computed by the
// backend's school_tier() — the same function the scoring pipeline and the
// hard filter use. This used to be a ~50-entry keyword list maintained here,
// which could not see the operator overrides saved from the 學校分級 page:
// promoting a school there moved it in the ranking while this filter kept
// excluding it, with nothing to indicate the two disagreed.
const TOP_SCHOOL_TIER = 'A'

function isTopUniversity(candidate) {
  return candidate.school_tier === TOP_SCHOOL_TIER
}


/**
 * Age bands, matched against the same `calcAge(birth_year)` the 年齡 column
 * shows — never the stored `age`, which is a snapshot from import time and
 * drifts a year out. A filter that disagreed with the visible column would
 * look broken.
 *
 * An unparsable birth year fails every band: 42 candidates have no usable one,
 * and letting them through would make "40+" quietly mean "40+ or unknown".
 */
function matchAgeRange(age, range) {
  if (age == null) return false
  switch (range) {
    case '~24': return age <= 24
    case '25-29': return age >= 25 && age <= 29
    case '30-34': return age >= 30 && age <= 34
    case '35-39': return age >= 35 && age <= 39
    case '40+': return age >= 40
    default: return true
  }
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
    // Tier 0 is a real tier — compare against null, not falsiness.
    if (filters.aiTier != null && filters.aiTier !== '' && c.experience_detail?.tier !== filters.aiTier) return false
    if (filters.hardFilterPassedOnly && c.passed_hard_filter === false) return false
    if (filters.dedupeStatus && c.dedupe_status !== filters.dedupeStatus) return false
    if (filters.importBatchId && c.import_batch_id !== Number(filters.importBatchId)) return false
    if (filters.bookmarkedOnly && !bookmarks.has(c.id)) return false
    if (filters.candidateType && c.candidate_type !== filters.candidateType) return false
    // `age` is attached by the .map() below, i.e. after this predicate runs —
    // so derive it here rather than reading c.age, which is still the stored one.
    if (filters.ageRange && !matchAgeRange(calcAge(c.birth_year), filters.ageRange)) return false
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

// Rendering every match at once is what put the browser over the edge: the
// API returns all 3179 candidates in one 6MB response, and a `v-for` over
// that built ~3179 rows, each carrying an avatar, chips and several SVGs.
// A plain 3179-row table with no CSS and no JS is enough to crash the
// renderer on its own, so this is a hard ceiling, not a tuning knob.
const PAGE_SIZE = 100
const page = ref(1)

const pageCount = computed(() =>
  Math.max(1, Math.ceil(sortedCandidates.value.length / PAGE_SIZE))
)

// Re-sorting or re-filtering can leave the cursor past the end of the new
// result set; clamp rather than render an empty page.
watch([sortedCandidates, pageCount], () => {
  if (page.value > pageCount.value) page.value = pageCount.value
})

const pagedCandidates = computed(() => {
  const start = (page.value - 1) * PAGE_SIZE
  return sortedCandidates.value.slice(start, start + PAGE_SIZE)
})

const rangeStart = computed(() =>
  sortedCandidates.value.length === 0 ? 0 : (page.value - 1) * PAGE_SIZE + 1
)
const rangeEnd = computed(() =>
  Math.min(page.value * PAGE_SIZE, sortedCandidates.value.length)
)

function goPage(n) {
  page.value = Math.min(Math.max(1, n), pageCount.value)
  if (scrollEl.value) scrollEl.value.scrollTop = 0
}

defineExpose({
  filteredCount: computed(() => sortedCandidates.value.length),
  getScrollTop: () => scrollEl.value?.scrollTop ?? 0,
  setScrollTop: (top) => { if (scrollEl.value) scrollEl.value.scrollTop = top },
})
</script>
