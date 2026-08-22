<template>
  <div class="h-full overflow-y-auto">
    <!-- Header bar -->
    <div class="sticky top-0 z-10 flex items-center gap-3 border-b border-line bg-surface/95 px-6 py-4 backdrop-blur">
      <button
        @click="goBack"
        class="p-1.5 rounded-control text-ink-faint hover:text-ink hover:bg-surface-2 transition"
      >
        <ChevronLeft class="h-4 w-4" :stroke-width="2.5" />
      </button>
      <span class="text-small font-semibold text-ink">{{ candidate?.name || '人選資料' }}</span>
      <span
        v-if="isInterested"
        class="text-micro font-semibold bg-warn-soft text-warn-ink border border-warn-line rounded-full px-2 py-0.5"
      >感興趣</span>
      <span
        v-if="isInvited"
        class="text-micro font-semibold bg-good-soft text-good-ink border border-good-line rounded-full px-2 py-0.5"
      >邀請已發</span>
      <div class="ml-auto flex items-center gap-2">
        <!-- Bookmark / Interested toggle -->
        <button
          v-if="candidate"
          @click="bookmarkStore.toggle(Number(id))"
          :title="isInterested ? '取消標記' : '標記為感興趣'"
          :class="[
            'p-1.5 rounded-control transition',
            isInterested ? 'text-warn-ink hover:text-warn-ink' : 'text-ink-faint hover:text-ink-muted hover:bg-surface-2'
          ]"
        >
          <Star class="h-5 w-5" :stroke-width="1.5" :fill="isInterested ? 'currentColor' : 'none'" />
        </button>
        <!-- Invitation sent toggle -->
        <button
          v-if="candidate"
          @click="invitationStore.toggle(Number(id))"
          :title="isInvited ? '取消邀請標記' : '標記已發邀請'"
          :class="[
            'p-1.5 rounded-control transition',
            isInvited ? 'text-good-ink hover:text-good-ink' : 'text-ink-faint hover:text-ink-muted hover:bg-surface-2'
          ]"
        >
          <Mail class="h-5 w-5" :stroke-width="1.5" :fill="isInvited ? 'currentColor' : 'none'" />
        </button>
        <!-- Compose an email from a saved template -->
        <button
          v-if="candidate"
          @click="showEmail = true"
          title="產生信件"
          class="inline-flex items-center gap-1.5 rounded-control border border-line px-2.5 py-1.5 text-micro font-medium text-ink-muted transition hover:border-line-strong hover:text-ink"
        >
          <Mail class="h-4 w-4" :stroke-width="1.5" />
          寄信
        </button>
        <ScoreBadge v-if="match" :score="match.overall_score" size="default" />
      </div>
    </div>

    <EmailComposeModal
      v-if="showEmail"
      :candidate-id="id"
      :candidate-name="candidate?.name || ''"
      @close="showEmail = false"
    />

    <!-- Loading -->
    <div v-if="!candidate" class="flex items-center justify-center min-h-[400px]">
      <div class="flex flex-col items-center gap-3 text-ink-faint">
        <RefreshCw class="h-8 w-8 animate-spin" :stroke-width="1.5" />
        <span class="text-small">載入中…</span>
      </div>
    </div>

    <!-- Content -->
    <div v-else class="mx-auto max-w-5xl space-y-0 px-6 py-8">

      <!-- Hero card -->
      <div class="mb-6 rounded-card border border-line-strong bg-surface p-7 shadow-sm">
        <div class="flex items-start gap-5">
          <!-- Avatar -->
          <div class="h-20 w-20 rounded-card bg-brand-soft text-brand-ink font-bold text-display flex items-center justify-center shrink-0 overflow-hidden">
            <img v-if="candidate.photo_url" :src="candidate.photo_url" class="h-full w-full object-cover" />
            <span v-else>{{ candidate.name?.charAt(0) || '?' }}</span>
          </div>

          <div class="flex-1 min-w-0">
            <!-- Name row -->
            <div class="flex items-center gap-2 flex-wrap">
              <h1 class="text-display font-bold text-ink">{{ candidate.name }}</h1>
              <button
                class="p-1 rounded text-ink-faint hover:text-ink-muted transition"
                @click="copyText(candidate.name, 'name')"
                title="複製姓名"
              >
                <Copy class="h-4 w-4" :stroke-width="2" v-if="!nameCopied" />
                <Check v-else class="h-4 w-4 text-good-ink" :stroke-width="2.5" />
              </button>
              <span v-if="candidate.english_name" class="text-base text-ink-faint font-normal">{{ candidate.english_name }}</span>
              <span
                v-if="candidate.candidate_type"
                :class="[
                  'text-micro font-semibold border rounded-full px-2 py-0.5 whitespace-nowrap',
                  candidate.candidate_type === '實習'
                    ? 'bg-info-soft text-info-ink border-info-line'
                    : 'bg-neutral-soft text-neutral-ink border-neutral-line'
                ]"
              >{{ candidate.candidate_type === '實習' ? '實習' : '工程師' }}</span>
            </div>

            <!-- 104 Code -->
            <div v-if="candidate.code_104" class="flex items-center gap-1.5 mt-1 text-small text-ink-muted">
              <span class="font-mono text-micro bg-surface-2 rounded px-1.5 py-0.5 text-ink-muted">{{ candidate.code_104 }}</span>
              <button @click="copyText(candidate.code_104, 'code')" class="text-ink-faint hover:text-ink-muted transition">
                <Copy class="h-3.5 w-3.5" :stroke-width="2" v-if="!codeCopied" />
                <Check v-else class="h-3.5 w-3.5 text-good-ink" :stroke-width="2.5" />
              </button>
            </div>

            <!-- Summary line -->
            <div class="mt-2 text-small text-ink-muted flex flex-wrap gap-1.5 items-center">
              <span v-if="calculatedAge != null" class="font-semibold text-ink">{{ calculatedAge }} 歲</span>
              <span v-if="calculatedAge != null" class="text-ink-faint">·</span>
              <span class="font-semibold text-ink">{{ candidate.education_level }}</span>
              <span v-if="candidate.school" class="text-ink-faint">·</span>
              <span v-if="candidate.school">{{ candidate.school }}</span>
              <span class="text-ink-faint">·</span>
              <span>{{ candidate.years_of_experience || '無工作經驗' }}</span>
            </div>

            <div v-if="candidate.ideal_positions?.length" class="mt-1 text-small text-ink-muted">
              {{ candidate.ideal_positions.join(' / ') }}
            </div>

            <!-- Score badges -->
            <div v-if="match" class="mt-3 flex items-center gap-2 flex-wrap">
              <span class="text-micro font-semibold text-ink-faint">總分</span>
              <ScoreBadge :score="match.overall_score" size="large" />
              <TierBadge
                v-if="match.experience_detail?.tier != null"
                :tier="match.experience_detail.tier"
                :tier-label="match.experience_detail.tier_label"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Basic Information -->
      <SectionCard title="基本資料">
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-x-4">
          <DetailField label="出生年" :value="candidate.birth_year" />
          <DetailField label="年齡" :value="calculatedAge != null ? `${calculatedAge} 歲` : candidate.age" />
          <DetailField label="國籍" :value="candidate.nationality" />
          <DetailField label="目前狀態" :value="candidate.current_status" />
          <DetailField label="最快到職" :value="candidate.earliest_start" />
          <DetailField label="兵役狀況" :value="candidate.military_status" />
          <DetailField label="期望薪資" :value="candidate.desired_salary" copyable />
          <DetailField label="求職身份" :value="candidate.work_type" />
          <DetailField label="居住地區" :value="candidate.district" />
          <DetailField label="期望產業" :value="candidate.desired_industry" />
        </div>
        <div v-if="candidate.desired_locations?.length" class="mt-3">
          <div class="text-micro font-semibold text-ink-faint mb-1.5">期望工作地點</div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="loc in candidate.desired_locations" :key="loc" class="text-micro bg-expert-soft text-expert-ink border border-expert-line rounded-full px-2.5 py-0.5">{{ loc }}</span>
          </div>
        </div>
        <div v-if="candidate.desired_job_categories?.length" class="mt-3">
          <div class="text-micro font-semibold text-ink-faint mb-1.5">期望職務類別</div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="cat in candidate.desired_job_categories" :key="cat" class="text-micro bg-surface-2 text-ink-muted border border-line rounded-full px-2.5 py-0.5">{{ cat }}</span>
          </div>
        </div>
      </SectionCard>

      <!-- Contact -->
      <SectionCard title="聯絡方式">
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-x-4">
          <DetailField label="Email" :value="candidate.email" copyable />
          <DetailField label="手機 1" :value="candidate.mobile1" copyable />
          <DetailField label="手機 2" :value="candidate.mobile2" copyable />
          <DetailField label="住家電話" :value="candidate.phone_home" copyable />
          <DetailField label="公司電話" :value="candidate.phone_work" copyable />
          <DetailField label="通訊地址" :value="candidate.mailing_address" copyable />
        </div>
        <div v-if="candidate.linkedin_url" class="mt-3">
          <div class="text-micro font-semibold text-ink-faint mb-1">LinkedIn</div>
          <div class="flex items-center gap-2">
            <a :href="candidate.linkedin_url" target="_blank" class="text-small text-brand-ink hover:underline truncate max-w-xs">
              {{ candidate.linkedin_url }}
            </a>
            <button @click="copyText(candidate.linkedin_url, 'linkedin')" class="text-ink-faint hover:text-ink-muted transition shrink-0">
              <Copy class="h-3.5 w-3.5" :stroke-width="2" v-if="!linkedinCopied" />
              <Check v-else class="h-3.5 w-3.5 text-good-ink" :stroke-width="2.5" />
            </button>
          </div>
        </div>
      </SectionCard>

      <!-- Work Experience -->
      <SectionCard title="工作經歷">
        <div v-if="!candidate.work_experiences?.length" class="text-small text-ink-faint py-2">無工作經驗</div>
        <div
          v-for="we in candidate.work_experiences"
          :key="we.id"
          class="bg-surface-2 border border-line rounded-control p-4 mb-3 last:mb-0"
        >
          <div class="flex justify-between items-start gap-3 flex-wrap mb-2">
            <div>
              <div class="text-title font-semibold text-ink">{{ we.job_title }}</div>
              <div class="text-base text-ink-muted mt-0.5">{{ we.company_name }}</div>
            </div>
            <span class="text-micro bg-brand-soft text-brand-ink border border-brand-line rounded-full px-2.5 py-1 shrink-0">
              {{ we.date_start }} ~ {{ we.date_end }}
              <span v-if="we.duration"> ({{ we.duration }})</span>
            </span>
          </div>
          <div v-if="we.industry || we.company_size || we.job_category || we.management_responsibility" class="flex flex-wrap gap-1.5 mb-2">
            <span v-if="we.industry" class="text-micro bg-surface-2 text-ink-muted rounded-full px-2 py-0.5">{{ we.industry }}</span>
            <span v-if="we.company_size" class="text-micro bg-surface-2 text-ink-muted rounded-full px-2 py-0.5">{{ we.company_size }}</span>
            <span v-if="we.job_category" class="text-micro bg-surface-2 text-ink-muted rounded-full px-2 py-0.5">{{ we.job_category }}</span>
            <span v-if="we.management_responsibility && we.management_responsibility !== '無'" class="text-micro bg-warn-soft text-warn-ink border border-warn-line rounded-full px-2 py-0.5">{{ we.management_responsibility }}</span>
          </div>
          <div v-if="we.job_description" class="text-base text-ink whitespace-pre-wrap leading-relaxed">{{ we.job_description }}</div>
        </div>
      </SectionCard>

      <!-- Education -->
      <SectionCard title="學歷">
        <div v-if="!candidate.education?.length" class="text-small text-ink-faint py-2">無學歷資料</div>
        <div
          v-for="ed in candidate.education"
          :key="ed.id"
          class="bg-surface-2 border border-line rounded-control p-4 mb-3 last:mb-0"
        >
          <div class="flex justify-between items-start gap-3 flex-wrap mb-2">
            <div>
              <div class="text-title font-semibold text-ink">{{ ed.school }}</div>
              <div class="text-base text-ink-muted mt-0.5">
                {{ ed.department }}<span v-if="ed.degree_level"> · {{ ed.degree_level }}</span>
              </div>
            </div>
            <span class="text-micro bg-brand-soft text-brand-ink border border-brand-line rounded-full px-2.5 py-1 shrink-0">
              {{ ed.date_start }} ~ {{ ed.date_end }}
            </span>
          </div>
          <div v-if="ed.region || ed.status" class="flex flex-wrap gap-1.5">
            <span v-if="ed.region" class="text-micro bg-surface-2 text-ink-muted rounded-full px-2 py-0.5">{{ ed.region }}</span>
            <span v-if="ed.status" class="text-micro bg-info-soft text-info-ink border border-info-line rounded-full px-2 py-0.5">{{ ed.status }}</span>
          </div>
        </div>
      </SectionCard>

      <!-- Skills -->
      <SectionCard title="技能專長">
        <div v-if="candidate.skill_tags?.length" class="flex flex-wrap gap-1.5 mb-4">
          <span
            v-for="tag in candidate.skill_tags"
            :key="tag"
            class="text-small bg-brand-soft text-brand-ink border border-brand-line rounded-full px-3 py-1 font-medium"
          >{{ tag }}</span>
        </div>
        <MarkdownContent v-if="candidate.skills_text" :content="candidate.skills_text" />
      </SectionCard>

      <!-- Self Introduction -->
      <SectionCard v-if="candidate.self_introduction" title="個人簡介">
        <MarkdownContent :content="candidate.self_introduction" />
      </SectionCard>

      <!-- Personal Motto -->
      <SectionCard v-if="candidate.personal_motto" title="個人格言">
        <MarkdownContent :content="candidate.personal_motto" />
      </SectionCard>

      <!-- Personal Traits -->
      <SectionCard v-if="candidate.personal_traits" title="個人特色">
        <MarkdownContent :content="candidate.personal_traits" />
      </SectionCard>

      <!-- Autobiography -->
      <SectionCard v-if="candidate.autobiography" title="自傳">
        <MarkdownContent :content="candidate.autobiography" />
      </SectionCard>

      <!-- Match Analysis -->
      <SectionCard title="評分分析">
        <div v-if="!match" class="flex items-center gap-4 py-2">
          <span class="text-small text-ink-faint">尚未產生評分結果</span>
          <button
            @click="doMatch"
            :disabled="matching"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 text-small font-semibold bg-brand text-white rounded-control hover:bg-brand-hover disabled:opacity-50 transition"
          >
            <PlayCircle class="h-4 w-4" :class="{ 'animate-spin': matching }" :stroke-width="2" />
            {{ matching ? '評分中…' : '執行評分' }}
          </button>
        </div>
        <template v-else>
          <ScoreCard :match="match" />
          <button
            @click="doMatch"
            :disabled="matching"
            class="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 text-small font-medium border border-line rounded-control text-ink-muted hover:border-line-strong hover:text-ink disabled:opacity-50 transition"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': matching }" :stroke-width="2" />
            {{ matching ? '評分中…' : '重新評分' }}
          </button>
        </template>
      </SectionCard>

      <!-- Interview Questions (shown only when bookmarked / "interested") -->
      <SectionCard v-if="isInterested" title="面試問題">
        <div v-if="!interviewQuestions && !generatingQuestions" class="flex items-center gap-4 py-2">
          <span class="text-small text-ink-faint">點擊生成針對此候選人量身訂製的中文面試問題。</span>
          <button
            @click="doGenerateQuestions"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 text-small font-semibold border border-good-line bg-good-soft text-good-ink rounded-control hover:border-good-ink transition"
          >
            <HelpCircle class="h-4 w-4" :stroke-width="2" />
            生成面試問題
          </button>
        </div>

        <div v-else-if="questionsError" class="flex items-start gap-3 py-3">
          <AlertTriangle class="h-5 w-5 text-bad-ink shrink-0 mt-0.5" :stroke-width="2" />
          <div>
            <div class="text-small text-bad-ink font-medium">生成失敗</div>
            <div class="text-micro text-ink-faint mt-0.5">{{ questionsError }}</div>
            <button @click="doGenerateQuestions" class="mt-2 text-micro text-brand-ink hover:underline">重試</button>
          </div>
        </div>

        <div v-else-if="generatingQuestions" class="flex items-center gap-3 py-4 text-ink-faint">
          <RefreshCw class="h-5 w-5 animate-spin" :stroke-width="1.5" />
          <span class="text-small">AI 正在生成面試問題…</span>
        </div>

        <template v-else-if="interviewQuestions">
          <!-- Group by category -->
          <div v-for="(group, cat) in groupedQuestions" :key="cat" class="mb-5 last:mb-0">
            <div class="text-micro font-semibold text-ink-faint mb-2 flex items-center gap-2">
              <span class="h-2 w-2 rounded-full bg-emerald-400 inline-block"></span>
              {{ cat }}
            </div>
            <div v-for="(q, idx) in group" :key="idx" class="bg-surface-2 border border-line rounded-control p-4 mb-2 last:mb-0">
              <div class="text-small font-medium text-ink leading-relaxed">{{ q.question }}</div>
              <div v-if="q.purpose" class="mt-1.5 text-micro text-ink-faint italic">目的：{{ q.purpose }}</div>
            </div>
          </div>
          <button
            @click="doGenerateQuestions"
            :disabled="generatingQuestions"
            class="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 text-small font-medium border border-line rounded-control text-ink-muted hover:border-line-strong hover:text-ink disabled:opacity-50 transition"
          >
            <RefreshCw class="h-4 w-4" :class="{ 'animate-spin': generatingQuestions }" :stroke-width="2" />
            重新生成
          </button>
        </template>
      </SectionCard>

      <!-- Attachments -->
      <SectionCard v-if="candidate.attachments?.length" title="附件">
        <div class="space-y-2">
          <div
            v-for="att in candidate.attachments"
            :key="att.id"
            class="flex items-center gap-3 p-3 bg-surface-2 rounded-control border border-line"
          >
            <div class="h-8 w-8 bg-surface-2 rounded-control flex items-center justify-center shrink-0">
              <FileText class="h-4 w-4 text-ink-muted" :stroke-width="1.5" />
            </div>
            <div>
              <div class="text-small font-semibold text-ink">{{ att.name || att.attachment_type }}</div>
              <div v-if="att.description" class="text-micro text-ink-muted">{{ att.description }}</div>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { fetchCandidate, fetchMatchResult, triggerMatch, generateInterviewQuestions } from '../api'
import { useBookmarkStore } from '../stores/bookmarks'
import { useInvitationStore } from '../stores/invitations'
import ScoreBadge from '../components/ScoreBadge.vue'
import TierBadge from '../components/TierBadge.vue'
import ScoreCard from '../components/ScoreCard.vue'
import SectionCard from '../components/SectionCard.vue'
import DetailField from '../components/DetailField.vue'
import MarkdownContent from '../components/MarkdownContent.vue'
import EmailComposeModal from '../components/EmailComposeModal.vue'
import { AlertTriangle, Check, ChevronLeft, Copy, FileText, HelpCircle, Mail, PlayCircle, RefreshCw, Star } from 'lucide-vue-next'

const props = defineProps({
  id: { type: [String, Number], required: true },
})

const router = useRouter()
const bookmarkStore = useBookmarkStore()
const invitationStore = useInvitationStore()
const isInterested = computed(() => bookmarkStore.has(Number(props.id)))
const isInvited = computed(() => invitationStore.has(Number(props.id)))

// Return to wherever the candidate was opened from (import batch, bookmarks,
// list). Falls back to the candidate list when there is no history to go back
// to, e.g. when the detail URL was opened directly.
function goBack() {
  if (window.history.state?.back) router.back()
  else router.push({ name: 'list' })
}

const candidate = ref(null)
const calculatedAge = computed(() => {
  const by = candidate.value?.birth_year
  if (!by) return null
  const year = parseInt(by, 10)
  if (isNaN(year) || year < 1900) return null
  return new Date().getFullYear() - year
})
const match = ref(null)
const matching = ref(false)
const showEmail = ref(false)
const nameCopied = ref(false)
const codeCopied = ref(false)
const linkedinCopied = ref(false)

const interviewQuestions = ref(null)
const generatingQuestions = ref(false)
const questionsError = ref(null)
const groupedQuestions = computed(() => {
  if (!interviewQuestions.value?.questions) return {}
  return interviewQuestions.value.questions.reduce((acc, q) => {
    const cat = q.category || '其他'
    if (!acc[cat]) acc[cat] = []
    acc[cat].push(q)
    return acc
  }, {})
})

async function copyText(text, key) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  if (key === 'name') { nameCopied.value = true; setTimeout(() => { nameCopied.value = false }, 1500) }
  if (key === 'code') { codeCopied.value = true; setTimeout(() => { codeCopied.value = false }, 1500) }
  if (key === 'linkedin') { linkedinCopied.value = true; setTimeout(() => { linkedinCopied.value = false }, 1500) }
}

async function loadData() {
  candidate.value = await fetchCandidate(props.id)
  if (candidate.value?.interview_questions) {
    interviewQuestions.value = candidate.value.interview_questions
  }
  const result = await fetchMatchResult(props.id)
  match.value = result.match
}

async function doGenerateQuestions() {
  generatingQuestions.value = true
  questionsError.value = null
  try {
    const result = await generateInterviewQuestions(props.id)
    if (result.error) {
      questionsError.value = result.error
    } else {
      interviewQuestions.value = result
    }
  } catch (e) {
    questionsError.value = e.response?.data?.error || e.message || 'Unknown error'
  } finally {
    generatingQuestions.value = false
  }
}

async function doMatch() {
  matching.value = true
  try {
    await triggerMatch(props.id)
    for (let i = 0; i < 30; i++) {
      await new Promise((r) => setTimeout(r, 2000))
      const result = await fetchMatchResult(props.id)
      if (result.match) {
        match.value = result.match
        break
      }
    }
  } finally {
    matching.value = false
  }
}

onMounted(loadData)
</script>
