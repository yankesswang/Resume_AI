<template>
  <div class="scorecard">
    <!-- Hard Filter Status -->
    <v-alert
      v-if="match.passed_hard_filter === false"
      type="error"
      variant="tonal"
      density="compact"
      class="mb-4"
    >
      <div class="font-weight-bold">Hard Filter: FAILED</div>
      <ul v-if="match.hard_filter_failures?.length" class="mt-1 pl-4">
        <li v-for="(f, i) in match.hard_filter_failures" :key="i" class="text-body-2">{{ f }}</li>
      </ul>
    </v-alert>
    <v-alert
      v-else-if="match.passed_hard_filter === true"
      type="success"
      variant="tonal"
      density="compact"
      class="mb-4"
    >
      Hard Filter: PASSED
    </v-alert>

    <!-- Score Overview -->
    <v-row class="mb-4">
      <v-col cols="12">
        <v-card variant="tonal" color="primary" class="pa-4 text-center">
          <div class="text-caption font-weight-bold text-uppercase">Total Score</div>
          <div class="text-h4 font-weight-bold mt-1">{{ round(match.overall_score) }}<span class="text-h6 font-weight-regular"> / 100</span></div>
        </v-card>
      </v-col>
    </v-row>

    <!-- Score Breakdown -->
    <div class="mb-4">
      <div class="text-subtitle-2 font-weight-bold mb-3">Score Breakdown</div>
      <div v-for="dim in scoreDimensions" :key="dim.label" class="mb-2">
        <div class="d-flex justify-space-between align-center mb-1">
          <span class="text-body-2">{{ dim.label }} ({{ dim.weight }}%)</span>
          <span class="text-body-2 font-weight-bold">{{ dim.points }}</span>
        </div>
        <v-progress-linear
          :model-value="dim.percent"
          :color="dim.color"
          height="8"
          rounded
        />
      </div>
    </div>

    <!-- AI Tier + Engineering in a row -->
    <v-row class="mb-4">
      <v-col cols="12" md="6">
        <!-- AI Tier Section -->
        <v-card variant="outlined" class="pa-4 h-100">
          <div class="text-subtitle-2 font-weight-bold mb-3">
            <v-icon size="small" class="mr-1">mdi-triangle</v-icon>
            AI Experience Pyramid
          </div>
          <div v-if="expDetail" class="d-flex align-center mb-3">
            <TierBadge
              :tier="expDetail.tier"
              :tier-label="expDetail.tier_label"
              size="default"
            />
            <span class="text-h6 font-weight-bold ml-3">{{ round(expDetail.score) }} pts</span>
          </div>
          <div v-if="expDetail?.evidence?.length" class="mb-2">
            <div class="text-caption font-weight-bold mb-1">Evidence:</div>
            <v-chip
              v-for="(e, i) in expDetail.evidence.slice(0, 8)"
              :key="i"
              size="x-small"
              variant="outlined"
              class="mr-1 mb-1"
            >
              {{ e }}
            </v-chip>
          </div>
          <div v-if="expDetail" class="d-flex flex-wrap ga-3 mt-2">
            <div class="text-caption">
              <strong>Tech Stack:</strong> {{ expDetail.tech_stack_score }}
            </div>
            <div class="text-caption">
              <strong>Complexity:</strong> {{ expDetail.complexity_score }}
            </div>
            <div class="text-caption">
              <strong>Metrics:</strong> {{ expDetail.metric_score }}
            </div>
          </div>
        </v-card>
      </v-col>
      <v-col cols="12" md="6">
        <!-- Engineering Matrix -->
        <v-card variant="outlined" class="pa-4 h-100">
          <EngineeringMatrix :detail="engDetail" />
        </v-card>
      </v-col>
    </v-row>

    <!-- Tags -->
    <div v-if="match.tags?.length" class="mb-4">
      <div class="text-subtitle-2 font-weight-bold mb-2">
        <v-icon size="small" class="mr-1">mdi-tag-multiple</v-icon>
        Tags
      </div>
      <v-chip
        v-for="tag in match.tags"
        :key="tag"
        size="small"
        color="primary"
        variant="tonal"
        class="mr-1 mb-1"
      >
        {{ tag }}
      </v-chip>
    </div>

    <!-- Semantic Similarity -->
    <div v-if="match.semantic_similarity > 0" class="mb-4">
      <div class="text-subtitle-2 font-weight-bold mb-2">
        <v-icon size="small" class="mr-1">mdi-vector-combine</v-icon>
        Semantic Similarity
      </div>
      <v-progress-linear
        :model-value="match.semantic_similarity * 100"
        color="indigo"
        height="12"
        rounded
      >
        <template #default>
          <span class="text-caption font-weight-bold white--text">{{ round(match.semantic_similarity * 100) }}%</span>
        </template>
      </v-progress-linear>
    </div>

    <!-- Analysis Text -->
    <div v-if="match.analysis_text" class="mb-4">
      <div class="text-subtitle-2 font-weight-bold mb-2">
        <v-icon size="small" class="mr-1">mdi-text-box-outline</v-icon>
        Analysis
      </div>
      <MarkdownContent :content="match.analysis_text" />
    </div>

    <!-- Strengths & Gaps -->
    <v-row v-if="match.strengths?.length || match.gaps?.length" class="mb-4">
      <v-col v-if="match.strengths?.length" cols="12" md="6">
        <div class="text-subtitle-2 font-weight-bold mb-2">
          <v-icon color="success" size="small" class="mr-1">mdi-check-circle</v-icon>
          Strengths
        </div>
        <ul class="text-body-2 pl-4" style="line-height: 1.8">
          <li v-for="(s, i) in match.strengths" :key="i">{{ s }}</li>
        </ul>
      </v-col>
      <v-col v-if="match.gaps?.length" cols="12" md="6">
        <div class="text-subtitle-2 font-weight-bold mb-2">
          <v-icon color="error" size="small" class="mr-1">mdi-alert-circle</v-icon>
          Gaps
        </div>
        <ul class="text-body-2 pl-4" style="line-height: 1.8">
          <li v-for="(g, i) in match.gaps" :key="i">{{ g }}</li>
        </ul>
      </v-col>
    </v-row>

    <!-- Interview Suggestions -->
    <div v-if="match.interview_suggestions?.length" class="mb-4">
      <div class="text-subtitle-2 font-weight-bold mb-2">
        <v-icon color="info" size="small" class="mr-1">mdi-lightbulb-on-outline</v-icon>
        Interview Suggestions
      </div>
      <v-alert
        v-for="(sug, i) in match.interview_suggestions"
        :key="i"
        type="info"
        variant="tonal"
        density="compact"
        class="mb-2"
      >
        {{ sug }}
      </v-alert>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import TierBadge from './TierBadge.vue'
import EngineeringMatrix from './EngineeringMatrix.vue'
import MarkdownContent from './MarkdownContent.vue'

const props = defineProps({
  match: { type: Object, required: true },
})

const expDetail = computed(() => props.match?.experience_detail || null)
const engDetail = computed(() => props.match?.engineering_detail || {})

const scoreDimensions = computed(() => {
  const m = props.match
  const sAi = m.s_ai ?? m.experience_score ?? 0
  const mEng = m.m_eng ?? 0
  const engNorm = Math.min(mEng / 0.5, 1) * 100
  const semNorm = (m.semantic_similarity ?? 0) * 100
  const edu = m.education_score ?? 0
  const skill = m.skills_score ?? 0

  return [
    { label: 'AI 經驗深度', weight: 35, raw: sAi, points: (sAi * 0.35).toFixed(1), percent: sAi, color: 'deep-purple' },
    { label: '工程落地能力', weight: 20, raw: engNorm, points: (engNorm * 0.20).toFixed(1), percent: engNorm, color: 'teal' },
    { label: '語意匹配度', weight: 20, raw: semNorm, points: (semNorm * 0.20).toFixed(1), percent: semNorm, color: 'indigo' },
    { label: '教育背景', weight: 15, raw: edu, points: (edu * 0.15).toFixed(1), percent: edu, color: 'amber-darken-2' },
    { label: '技能驗證', weight: 10, raw: skill, points: (skill * 0.10).toFixed(1), percent: skill, color: 'blue-grey' },
  ]
})

function round(val) {
  if (val == null) return '—'
  return Math.round(val)
}
</script>

<style scoped>
</style>
