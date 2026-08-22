<template>
  <div class="space-y-5">
    <!-- Hard Filter Status -->
    <div
      v-if="match.passed_hard_filter === false"
      class="flex gap-3 p-3 bg-bad-soft border border-bad-line rounded-control text-small"
    >
      <div class="text-bad-ink font-semibold shrink-0">未通過硬性條件</div>
      <ul v-if="match.hard_filter_failures?.length" class="list-disc pl-4 text-bad-ink space-y-0.5">
        <li v-for="(f, i) in match.hard_filter_failures" :key="i">{{ f }}</li>
      </ul>
    </div>
    <div
      v-else-if="match.passed_hard_filter === true"
      class="flex items-center gap-2 p-3 bg-good-soft border border-good-line rounded-control text-small text-good-ink"
    >
      <Check class="h-4 w-4 shrink-0" :stroke-width="2.5" />
      通過硬性條件
    </div>

    <!-- Total Score -->
    <div class="flex items-baseline justify-between rounded-card border border-line bg-surface-2 px-4 py-3">
      <span class="text-small text-ink-muted">總分</span>
      <ScoreBadge :score="match.overall_score" size="large" />
    </div>

    <!-- Score Breakdown -->
    <div>
      <div class="text-micro font-semibold text-ink-muted mb-3">分數組成</div>
      <div v-for="dim in scoreDimensions" :key="dim.label" class="mb-3">
        <div class="flex justify-between items-center mb-1">
          <span class="text-small text-ink">{{ dim.label }} <span class="text-ink-faint">({{ dim.weight }}%)</span></span>
          <span class="text-small font-semibold text-ink">{{ dim.points }}</span>
        </div>
        <div class="bg-surface-2 rounded-full h-2 overflow-hidden">
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
      <div class="bg-surface-2 border border-line rounded-card p-4">
        <div class="text-micro font-semibold text-ink-muted mb-3">AI 經驗分級</div>
        <div v-if="expDetail" class="flex items-center gap-3 mb-3">
          <TierBadge :tier="expDetail.tier" :tier-label="expDetail.tier_label" />
          <span class="text-title font-bold text-ink">{{ round(expDetail.score) }} 分</span>
        </div>
        <div v-if="expDetail?.evidence?.length" class="mb-3">
          <div class="text-micro text-ink-faint mb-1.5">判定依據</div>
          <div class="flex flex-wrap gap-1">
            <span
              v-for="(e, i) in expDetail.evidence.slice(0, 8)"
              :key="i"
              class="inline-block text-micro bg-surface-2 text-ink-muted rounded-full px-2 py-0.5 border border-line"
            >{{ e }}</span>
          </div>
        </div>
        <div v-if="expDetail" class="flex flex-wrap gap-3 text-micro text-ink-muted">
          <div><span class="text-ink-faint">技術棧</span> {{ expDetail.tech_stack_score }}</div>
          <div><span class="text-ink-faint">複雜度</span> {{ expDetail.complexity_score }}</div>
          <div><span class="text-ink-faint">量化成果</span> {{ expDetail.metric_score }}</div>
        </div>
      </div>

      <!-- Engineering Matrix -->
      <div class="bg-surface-2 border border-line rounded-card p-4">
        <EngineeringMatrix :detail="engDetail" />
      </div>
    </div>

    <!-- Tags -->
    <div v-if="match.tags?.length">
      <div class="text-micro font-semibold text-ink-muted mb-2">標籤</div>
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="tag in match.tags"
          :key="tag"
          class="text-micro bg-brand-soft text-brand-ink border border-brand-line rounded-full px-2.5 py-0.5 font-medium"
        >{{ tag }}</span>
      </div>
    </div>

    <!-- Semantic Similarity -->
    <div v-if="match.semantic_similarity > 0">
      <div class="text-micro font-semibold text-ink-muted mb-2">語意匹配度</div>
      <div class="flex items-center gap-3">
        <div class="flex-1 bg-surface-2 rounded-full h-3 overflow-hidden">
          <div
            class="h-3 rounded-full bg-indigo-500 transition-all duration-500"
            :style="{ width: `${match.semantic_similarity * 100}%` }"
          />
        </div>
        <span class="text-small font-semibold text-ink tabular-nums w-10 text-right">
          {{ round(match.semantic_similarity * 100) }}%
        </span>
      </div>
    </div>

    <!-- Analysis Text -->
    <div v-if="match.analysis_text">
      <div class="text-micro font-semibold text-ink-muted mb-2">綜合分析</div>
      <MarkdownContent :content="match.analysis_text" />
    </div>

    <!-- Strengths & Gaps -->
    <div v-if="match.strengths?.length || match.gaps?.length" class="grid grid-cols-1 md:grid-cols-2 gap-4">
      <div v-if="match.strengths?.length">
        <div class="text-micro font-semibold text-good-ink mb-2">優勢</div>
        <ul class="space-y-1 text-base text-ink list-disc list-inside leading-relaxed">
          <li v-for="(s, i) in match.strengths" :key="i">{{ s }}</li>
        </ul>
      </div>
      <div v-if="match.gaps?.length">
        <div class="text-micro font-semibold text-bad-ink mb-2">落差</div>
        <ul class="space-y-1 text-base text-ink list-disc list-inside leading-relaxed">
          <li v-for="(g, i) in match.gaps" :key="i">{{ g }}</li>
        </ul>
      </div>
    </div>

    <!-- Interview Suggestions -->
    <div v-if="match.interview_suggestions?.length">
      <div class="text-micro font-semibold text-ink-muted mb-2">面試建議</div>
      <div class="space-y-2">
        <div
          v-for="(sug, i) in match.interview_suggestions"
          :key="i"
          class="p-3 bg-brand-soft border border-brand-line rounded-control text-base text-brand-ink"
        >{{ sug }}</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import ScoreBadge from './ScoreBadge.vue'
import TierBadge from './TierBadge.vue'
import EngineeringMatrix from './EngineeringMatrix.vue'
import MarkdownContent from './MarkdownContent.vue'
import { Check } from 'lucide-vue-next'

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
    { label: '教育背景', weight: 15, raw: edu, points: (edu * 0.15).toFixed(1), percent: edu, barColor: 'bg-warn-ink' },
    { label: '技能驗證', weight: 10, raw: skill, points: (skill * 0.10).toFixed(1), percent: skill, barColor: 'bg-neutral-ink' },
  ]
})

function round(val) {
  if (val == null) return '—'
  return Math.round(val)
}
</script>
