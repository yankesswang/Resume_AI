<template>
  <div class="space-y-5">
    <!-- Hard Filter Status -->
    <div
      v-if="match.passed_hard_filter === false"
      class="flex gap-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm"
    >
      <div class="text-red-600 font-semibold shrink-0">Hard Filter: FAILED</div>
      <ul v-if="match.hard_filter_failures?.length" class="list-disc pl-4 text-red-700 space-y-0.5">
        <li v-for="(f, i) in match.hard_filter_failures" :key="i">{{ f }}</li>
      </ul>
    </div>
    <div
      v-else-if="match.passed_hard_filter === true"
      class="flex items-center gap-2 p-3 bg-green-50 border border-green-200 rounded-lg text-sm text-green-700"
    >
      <svg class="w-4 h-4 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
      </svg>
      Hard Filter: PASSED
    </div>

    <!-- Total Score -->
    <div class="p-4 bg-blue-600 rounded-xl text-center text-white">
      <div class="text-xs font-semibold uppercase tracking-widest text-blue-200 mb-1">Total Score</div>
      <div class="text-4xl font-bold tabular-nums">
        {{ round(match.overall_score) }}<span class="text-xl font-normal text-blue-300"> / 100</span>
      </div>
    </div>

    <!-- Score Breakdown -->
    <div>
      <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">Score Breakdown</div>
      <div v-for="dim in scoreDimensions" :key="dim.label" class="mb-3">
        <div class="flex justify-between items-center mb-1">
          <span class="text-sm text-gray-700">{{ dim.label }} <span class="text-gray-400">({{ dim.weight }}%)</span></span>
          <span class="text-sm font-semibold text-gray-900">{{ dim.points }}</span>
        </div>
        <div class="bg-gray-100 rounded-full h-2 overflow-hidden">
          <div
            class="h-2 rounded-full transition-all duration-500"
            :class="dim.barColor"
            :style="{ width: `${dim.percent}%` }"
          />
        </div>
      </div>
    </div>

    <!-- AI Tier + Engineering Matrix -->
    <div class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <!-- AI Tier -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl p-4">
        <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-3">AI Experience Pyramid</div>
        <div v-if="expDetail" class="flex items-center gap-3 mb-3">
          <TierBadge :tier="expDetail.tier" :tier-label="expDetail.tier_label" />
          <span class="text-lg font-bold text-gray-900">{{ round(expDetail.score) }} pts</span>
        </div>
        <div v-if="expDetail?.evidence?.length" class="mb-3">
          <div class="text-xs text-gray-400 mb-1.5">Evidence</div>
          <div class="flex flex-wrap gap-1">
            <span
              v-for="(e, i) in expDetail.evidence.slice(0, 8)"
              :key="i"
              class="inline-block text-xs bg-gray-100 text-gray-600 rounded-full px-2 py-0.5 border border-gray-200"
            >{{ e }}</span>
          </div>
        </div>
        <div v-if="expDetail" class="flex flex-wrap gap-3 text-xs text-gray-600">
          <div><span class="font-semibold">Tech Stack:</span> {{ expDetail.tech_stack_score }}</div>
          <div><span class="font-semibold">Complexity:</span> {{ expDetail.complexity_score }}</div>
          <div><span class="font-semibold">Metrics:</span> {{ expDetail.metric_score }}</div>
        </div>
      </div>

      <!-- Engineering Matrix -->
      <div class="bg-gray-50 border border-gray-200 rounded-xl p-4">
        <EngineeringMatrix :detail="engDetail" />
      </div>
    </div>

    <!-- Tags -->
    <div v-if="match.tags?.length">
      <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Tags</div>
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="tag in match.tags"
          :key="tag"
          class="text-xs bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-2.5 py-0.5 font-medium"
        >{{ tag }}</span>
      </div>
    </div>

    <!-- Semantic Similarity -->
    <div v-if="match.semantic_similarity > 0">
      <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Semantic Similarity</div>
      <div class="flex items-center gap-3">
        <div class="flex-1 bg-gray-100 rounded-full h-3 overflow-hidden">
          <div
            class="h-3 rounded-full bg-indigo-500 transition-all duration-500"
            :style="{ width: `${match.semantic_similarity * 100}%` }"
          />
        </div>
        <span class="text-sm font-semibold text-gray-700 tabular-nums w-10 text-right">
          {{ round(match.semantic_similarity * 100) }}%
        </span>
      </div>
    </div>

    <!-- Analysis Text -->
    <div v-if="match.analysis_text">
      <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Analysis</div>
      <MarkdownContent :content="match.analysis_text" />
    </div>

    <!-- Strengths & Gaps -->
    <div v-if="match.strengths?.length || match.gaps?.length" class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div v-if="match.strengths?.length">
        <div class="text-xs font-semibold text-green-600 uppercase tracking-wide mb-2">Strengths</div>
        <ul class="space-y-1 text-sm text-gray-700 list-disc list-inside leading-relaxed">
          <li v-for="(s, i) in match.strengths" :key="i">{{ s }}</li>
        </ul>
      </div>
      <div v-if="match.gaps?.length">
        <div class="text-xs font-semibold text-red-500 uppercase tracking-wide mb-2">Gaps</div>
        <ul class="space-y-1 text-sm text-gray-700 list-disc list-inside leading-relaxed">
          <li v-for="(g, i) in match.gaps" :key="i">{{ g }}</li>
        </ul>
      </div>
    </div>

    <!-- Interview Suggestions -->
    <div v-if="match.interview_suggestions?.length">
      <div class="text-xs font-semibold text-gray-500 uppercase tracking-wide mb-2">Interview Suggestions</div>
      <div class="space-y-2">
        <div
          v-for="(sug, i) in match.interview_suggestions"
          :key="i"
          class="p-3 bg-blue-50 border border-blue-100 rounded-lg text-sm text-blue-800"
        >{{ sug }}</div>
      </div>
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
    { label: 'AI 經驗深度', weight: 35, raw: sAi, points: (sAi * 0.35).toFixed(1), percent: sAi, barColor: 'bg-purple-500' },
    { label: '工程落地能力', weight: 20, raw: engNorm, points: (engNorm * 0.20).toFixed(1), percent: engNorm, barColor: 'bg-teal-500' },
    { label: '語意匹配度', weight: 20, raw: semNorm, points: (semNorm * 0.20).toFixed(1), percent: semNorm, barColor: 'bg-indigo-500' },
    { label: '教育背景', weight: 15, raw: edu, points: (edu * 0.15).toFixed(1), percent: edu, barColor: 'bg-amber-500' },
    { label: '技能驗證', weight: 10, raw: skill, points: (skill * 0.10).toFixed(1), percent: skill, barColor: 'bg-slate-400' },
  ]
})

function round(val) {
  if (val == null) return '—'
  return Math.round(val)
}
</script>
