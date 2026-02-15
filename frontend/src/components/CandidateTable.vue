<template>
  <v-card flat rounded="lg" class="candidate-table-card">
    <v-data-table
      :headers="headers"
      :items="filteredCandidates"
      :items-per-page="50"
      hover
      class="candidate-table"
      @click:row="(_event, { item }) => $router.push({ name: 'detail', params: { id: item.id } })"
    >
      <template #item.bookmarked="{ item }">
        <v-checkbox-btn
          :model-value="bookmarks.has(item.id)"
          color="amber-darken-2"
          density="compact"
          hide-details
          @click.stop
          @update:model-value="bookmarks.toggle(item.id)"
        />
      </template>
      <template #item.name="{ item }">
        <div class="d-flex align-center">
          <v-avatar size="32" color="primary" variant="tonal" class="mr-3">
            <v-img v-if="item.photo_url" :src="item.photo_url" :alt="item.name" cover />
            <span v-else class="text-caption font-weight-bold">{{ item.name?.charAt(0) }}</span>
          </v-avatar>
          <span class="font-weight-bold text-body-1">{{ item.name }}</span>
        </div>
      </template>
      <template #item.code_104="{ item }">
        <span v-if="item.code_104" class="text-body-2 font-weight-medium">{{ item.code_104 }}</span>
        <span v-else class="text-body-2 text-grey">—</span>
      </template>
      <template #item.age="{ item }">
        <span v-if="calcAge(item.birth_year) != null" class="text-body-2">{{ calcAge(item.birth_year) }}</span>
        <span v-else class="text-body-2 text-grey">—</span>
      </template>
      <template #item.university="{ item }">
        <div v-if="getEdu(item, 'university')" class="text-body-2">
          <div class="font-weight-medium">{{ getEdu(item, 'university').school }}</div>
          <div class="text-grey-darken-1">{{ getEdu(item, 'university').department }}</div>
        </div>
        <span v-else class="text-body-2 text-grey">無</span>
      </template>
      <template #item.masters="{ item }">
        <div v-if="getEdu(item, 'masters')" class="text-body-2">
          <div class="font-weight-medium">{{ getEdu(item, 'masters').school }}</div>
          <div class="text-grey-darken-1">{{ getEdu(item, 'masters').department }}</div>
        </div>
        <span v-else class="text-body-2 text-grey">無</span>
      </template>
      <template #item.years_of_experience="{ item }">
        <span class="text-body-1">{{ item.years_of_experience || '無工作經驗' }}</span>
      </template>
      <template #item.ai_tier="{ item }">
        <TierBadge
          v-if="item.experience_detail?.tier"
          :tier="item.experience_detail.tier"
          :tier-label="item.experience_detail.tier_label"
          size="small"
          variant="tonal"
          :show-icon="false"
        />
        <span v-else class="text-body-2 text-grey">—</span>
      </template>
      <template #item.skill_tags="{ item }">
        <v-chip
          v-for="tag in item.skill_tags.slice(0, 5)"
          :key="tag"
          size="small"
          class="mr-1 mb-1"
          color="accent"
          variant="tonal"
        >
          {{ tag }}
        </v-chip>
        <v-chip
          v-if="item.skill_tags.length > 5"
          size="small"
          color="grey"
          variant="text"
        >
          +{{ item.skill_tags.length - 5 }}
        </v-chip>
      </template>
      <template #item.overall_score="{ item }">
        <ScoreBadge :score="item.overall_score" />
      </template>
    </v-data-table>
  </v-card>
</template>

<script setup>
import { computed } from 'vue'
import { useFilterStore } from '../stores/filters'
import { useBookmarkStore } from '../stores/bookmarks'
import ScoreBadge from './ScoreBadge.vue'
import TierBadge from './TierBadge.vue'

const props = defineProps({
  candidates: { type: Array, default: () => [] },
})

const filters = useFilterStore()
const bookmarks = useBookmarkStore()

const headers = [
  { title: '', key: 'bookmarked', sortable: false, width: '48px', align: 'center' },
  { title: '姓名', key: 'name', sortable: true, width: '160px' },
  { title: '年齡', key: 'age', sortable: true, width: '70px' },
  { title: '104代碼', key: 'code_104', sortable: true, width: '140px' },
  { title: '大學', key: 'university', sortable: false, width: '180px' },
  { title: '碩士', key: 'masters', sortable: false, width: '180px' },
  { title: '年資', key: 'years_of_experience', sortable: true, width: '90px' },
  { title: 'AI Tier', key: 'ai_tier', sortable: true, width: '140px' },
  { title: '技能', key: 'skill_tags', sortable: false },
  { title: '分數', key: 'overall_score', sortable: true, width: '80px' },
]

const mastersKeywords = ['碩', '研究所', 'Master', 'MBA', 'MS', 'MA']
const universityKeywords = ['大學', '⼤學', '學士', 'Bachelor', 'BS', 'BA']

function getEdu(item, type) {
  const records = item.education || []

  for (const ed of records) {
    const dl = ed.degree_level || ''
    if (type === 'masters' && mastersKeywords.some((k) => dl.includes(k))) {
      return ed
    }
    if (type === 'university' && universityKeywords.some((k) => dl.includes(k))) {
      const dept = ed.department || ''
      const parts = dept.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
      const undergradPart = parts.find((p) => !mastersKeywords.some((k) => p.includes(k)))
      if (undergradPart) {
        return { school: ed.school, department: undergradPart }
      }
      return ed
    }
  }

  if (type === 'masters') {
    for (const ed of records) {
      const dept = ed.department || ''
      const parts = dept.split(/[、,，]/).map((s) => s.trim()).filter(Boolean)
      const mastersPart = parts.find((p) => mastersKeywords.some((k) => p.includes(k)))
      if (mastersPart) {
        return { school: ed.school, department: mastersPart }
      }
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
  '台灣大學', '臺灣大學', '台大', '臺大',
  'National Taiwan University', 'NTU',
  // 清華大學 (NTHU)
  '清華大學', '清大',
  'National Tsing Hua University', 'NTHU',
  // 交通大學 / 陽明交通大學 (NCTU / NYCU)
  '交通大學', '交大', '陽明交通大學', '陽明交大',
  'National Chiao Tung University', 'National Yang Ming Chiao Tung University',
  'NCTU', 'NYCU',
  // 成功大學 (NCKU)
  '成功大學', '成大',
  'National Cheng Kung University', 'NCKU',
  // 政治大學 (NCCU)
  '政治大學', '政大',
  'National Chengchi University', 'NCCU',
  // 台灣科技大學 (NTUST)
  '台灣科技大學', '臺灣科技大學', '台科大', '臺科大',
  'National Taiwan University of Science and Technology', 'Taiwan Tech', 'NTUST',
  // 陽明大學 (合併前校名)
  '陽明大學',
  'National Yang-Ming University', 'National Yang Ming University',
]

function isTopUniversity(candidate) {
  const edu = candidate.education || []
  for (const e of edu) {
    const school = e.school || ''
    if (TOP_UNIVERSITY_KEYWORDS.some((k) => school.includes(k))) return true
  }
  const school = candidate.school || ''
  if (TOP_UNIVERSITY_KEYWORDS.some((k) => school.includes(k))) return true
  return false
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

const filteredCandidates = computed(() => {
  return props.candidates.filter((c) => {
    if (filters.searchName) {
      const query = filters.searchName.toLowerCase()
      const nameMatch = c.name && c.name.toLowerCase().includes(query)
      const codeMatch = c.code_104 && c.code_104.includes(query)
      if (!nameMatch && !codeMatch) return false
    }
    if (filters.educationLevel && c.education_level !== filters.educationLevel) return false
    if (filters.selectedSkills.length > 0) {
      const tags = c.skill_tags || []
      if (!filters.selectedSkills.every((s) => tags.includes(s))) return false
    }
    if (filters.experienceRange) {
      const years = parseYearsOfExperience(c.years_of_experience)
      if (!matchExperienceRange(years, filters.experienceRange)) return false
    }
    if (filters.scoreRange) {
      const displayScore = c.overall_score ?? null
      if (!matchScoreRange(displayScore, filters.scoreRange)) return false
    }
    if (filters.topUniversityOnly) {
      if (!isTopUniversity(c)) return false
    }
    if (filters.aiTier) {
      const tier = c.experience_detail?.tier
      if (tier !== filters.aiTier) return false
    }
    if (filters.hardFilterPassedOnly) {
      if (c.passed_hard_filter === false) return false
    }
    if (filters.bookmarkedOnly) {
      if (!bookmarks.has(c.id)) return false
    }
    return true
  }).map((c) => ({
    ...c,
    age: calcAge(c.birth_year),
    overall_score: c.overall_score ?? null,
  }))
})
</script>

<style scoped>
.candidate-table-card {
  overflow: hidden;
}

.candidate-table :deep(.v-data-table tbody tr) {
  cursor: pointer;
  transition: background-color 0.15s ease, box-shadow 0.15s ease;
}

.candidate-table :deep(.v-data-table tbody tr:nth-child(even)) {
  background-color: rgba(var(--v-theme-primary), 0.02);
}

.candidate-table :deep(.v-data-table tbody tr:hover) {
  background-color: rgba(var(--v-theme-primary), 0.06) !important;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.06);
}

.candidate-table :deep(.v-data-table-header th) {
  font-size: 0.85rem !important;
  font-weight: 700 !important;
  text-transform: uppercase;
  letter-spacing: 0.02em;
  color: rgba(var(--v-theme-on-surface), 0.65) !important;
}

.candidate-table :deep(td) {
  padding-top: 14px !important;
  padding-bottom: 14px !important;
}
</style>
