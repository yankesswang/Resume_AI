<template>
  <v-card flat class="mb-4 pa-4 filter-panel" rounded="lg">
    <v-row dense align="center">
      <v-col cols="12" sm="6" md="2">
        <v-text-field
          v-model="filters.searchName"
          label="Search Name / 104 Code"
          prepend-inner-icon="mdi-magnify"
          variant="outlined"
          clearable
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" sm="6" md="2">
        <v-select
          v-model="filters.educationLevel"
          :items="educationLevels"
          label="Education Level"
          variant="outlined"
          clearable
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" sm="6" md="3">
        <v-autocomplete
          v-model="filters.selectedSkills"
          :items="skillTags"
          label="Skills"
          variant="outlined"
          multiple
          chips
          closable-chips
          clearable
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" sm="6" md="2">
        <v-select
          v-model="filters.experienceRange"
          :items="experienceRanges"
          label="Experience"
          variant="outlined"
          clearable
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" sm="6" md="2">
        <v-select
          v-model="filters.scoreRange"
          :items="scoreRanges"
          label="Score"
          variant="outlined"
          clearable
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="12" sm="6" md="2">
        <v-select
          v-model="filters.aiTier"
          :items="tierItems"
          label="AI Tier"
          variant="outlined"
          clearable
          density="compact"
          hide-details
        />
      </v-col>
      <v-col cols="auto" class="d-flex align-center">
        <v-btn
          :variant="filters.topUniversityOnly ? 'flat' : 'outlined'"
          :color="filters.topUniversityOnly ? 'primary' : undefined"
          size="small"
          prepend-icon="mdi-school"
          @click="filters.topUniversityOnly = !filters.topUniversityOnly"
        >
          頂大
        </v-btn>
      </v-col>
      <v-col cols="auto" class="d-flex align-center">
        <v-btn
          :variant="filters.hardFilterPassedOnly ? 'flat' : 'outlined'"
          :color="filters.hardFilterPassedOnly ? 'success' : undefined"
          size="small"
          prepend-icon="mdi-check-circle"
          @click="filters.hardFilterPassedOnly = !filters.hardFilterPassedOnly"
        >
          Passed
        </v-btn>
      </v-col>
      <v-col cols="auto" class="d-flex align-center">
        <v-btn
          :variant="filters.bookmarkedOnly ? 'flat' : 'outlined'"
          :color="filters.bookmarkedOnly ? 'amber-darken-2' : undefined"
          size="small"
          prepend-icon="mdi-star"
          @click="filters.bookmarkedOnly = !filters.bookmarkedOnly"
        >
          有興趣
        </v-btn>
      </v-col>
      <v-col cols="auto" class="d-flex align-center">
        <v-btn variant="text" size="small" @click="filters.clearAll()">Clear All</v-btn>
      </v-col>
    </v-row>
  </v-card>
</template>

<script setup>
import { useFilterStore } from '../stores/filters'

const filters = useFilterStore()

const tierItems = [
  { title: 'Tier 1 - Wrapper', value: 1 },
  { title: 'Tier 2 - RAG Architect', value: 2 },
  { title: 'Tier 3 - Model Tuner', value: 3 },
  { title: 'Tier 4 - Inference Ops', value: 4 },
]

defineProps({
  educationLevels: { type: Array, default: () => [] },
  skillTags: { type: Array, default: () => [] },
  experienceRanges: { type: Array, default: () => ['0-2年', '3-5年', '5-10年', '10年+'] },
  scoreRanges: { type: Array, default: () => ['80+', '60-79', '40-59', '<40', 'No Score'] },
})
</script>

<style scoped>
.filter-panel {
  background: rgba(var(--v-theme-surface-variant), 0.35) !important;
  border: 1px solid rgba(var(--v-theme-on-surface), 0.06);
}
</style>
