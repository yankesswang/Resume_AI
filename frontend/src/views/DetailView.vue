<template>
  <v-layout>
    <v-app-bar color="primary" density="comfortable">
      <v-btn icon @click="$router.push({ name: 'list' })">
        <v-icon>mdi-arrow-left</v-icon>
      </v-btn>
      <v-app-bar-title class="text-h6 font-weight-bold">Resume AI</v-app-bar-title>
    </v-app-bar>

    <v-main>
      <v-container v-if="candidate" class="py-8" style="max-width: 1100px">
        <!-- Header Card -->
        <v-card class="mb-6 pa-6" elevation="2">
          <div class="d-flex align-center">
            <v-avatar v-if="candidate.photo_url" size="100" class="mr-5" rounded="lg">
              <v-img :src="candidate.photo_url" cover />
            </v-avatar>
            <v-avatar v-else size="100" color="grey-lighten-3" class="mr-5" rounded="lg">
              <v-icon size="48" color="grey">mdi-account</v-icon>
            </v-avatar>
            <div>
              <div class="text-h4 font-weight-bold d-flex align-center">
                {{ candidate.name }}
                <v-btn
                  :icon="nameCopied ? 'mdi-check' : 'mdi-content-copy'"
                  :color="nameCopied ? 'success' : undefined"
                  size="x-small"
                  variant="text"
                  class="ml-2 copy-btn-header"
                  @click="copyText(candidate.name, 'name')"
                />
                <span v-if="candidate.english_name" class="text-h6 text-grey-darken-1 ml-3 font-weight-regular">
                  {{ candidate.english_name }}
                </span>
              </div>
              <div v-if="candidate.code_104" class="text-body-2 text-grey-darken-1 mt-1 d-flex align-center">
                <v-icon size="x-small" class="mr-1">mdi-identifier</v-icon>
                <span class="font-weight-medium">104 Code: {{ candidate.code_104 }}</span>
                <v-btn
                  :icon="codeCopied ? 'mdi-check' : 'mdi-content-copy'"
                  :color="codeCopied ? 'success' : undefined"
                  size="x-small"
                  variant="text"
                  density="compact"
                  class="ml-1 copy-btn-header"
                  @click="copyText(candidate.code_104, 'code')"
                />
              </div>
              <div class="text-body-1 text-grey-darken-1 mt-2">
                <span v-if="calculatedAge != null"><strong>{{ calculatedAge }} 歲</strong> &middot; </span>
                <strong>{{ candidate.education_level }}</strong>
                <span v-if="candidate.school" class="ml-1">&middot; {{ candidate.school }}</span>
                <span> &middot; <strong>{{ candidate.years_of_experience || '無工作經驗' }}</strong></span>
              </div>
              <div v-if="candidate.ideal_positions?.length" class="text-body-1 text-grey-darken-1 mt-1">
                {{ candidate.ideal_positions.join(' / ') }}
              </div>
              <div v-if="match" class="mt-3 d-flex align-center flex-wrap ga-2">
                <span class="text-body-1 font-weight-bold mr-3">Match Score:</span>
                <ScoreBadge :score="match.overall_score" size="large" />
                <TierBadge
                  v-if="match.experience_detail?.tier"
                  :tier="match.experience_detail.tier"
                  :tier-label="match.experience_detail.tier_label"
                  size="small"
                  class="ml-2"
                />
              </div>
            </div>
          </div>
        </v-card>

        <!-- Basic Information -->
        <SectionCard title="Basic Information" icon="mdi-account-details">
          <v-row>
            <DetailField label="Birth Year" :value="candidate.birth_year" />
            <DetailField label="Age" :value="calculatedAge != null ? `${calculatedAge} 歲` : candidate.age" />
            <DetailField label="Nationality" :value="candidate.nationality" />
            <DetailField label="Current Status" :value="candidate.current_status" />
            <DetailField label="Earliest Start" :value="candidate.earliest_start" />
            <DetailField label="Military Status" :value="candidate.military_status" />
            <DetailField label="Desired Salary" :value="candidate.desired_salary" copyable />
            <DetailField label="Work Type" :value="candidate.work_type" />
            <DetailField label="District" :value="candidate.district" />
            <DetailField label="Desired Industry" :value="candidate.desired_industry" />
          </v-row>
          <div v-if="candidate.desired_locations?.length" class="mt-3">
            <span class="field-label">Desired Locations</span>
            <div class="mt-1">
              <v-chip v-for="loc in candidate.desired_locations" :key="loc" size="small" color="secondary" variant="outlined" class="mr-1">{{ loc }}</v-chip>
            </div>
          </div>
          <div v-if="candidate.desired_job_categories?.length" class="mt-3">
            <span class="field-label">Job Categories</span>
            <div class="mt-1">
              <v-chip v-for="cat in candidate.desired_job_categories" :key="cat" size="small" color="accent" variant="outlined" class="mr-1">{{ cat }}</v-chip>
            </div>
          </div>
        </SectionCard>

        <!-- Contact -->
        <SectionCard title="Contact" icon="mdi-card-account-phone">
          <v-row>
            <DetailField label="Email" :value="candidate.email" cols="12" sm="6" copyable />
            <DetailField label="Mobile 1" :value="candidate.mobile1" copyable />
            <DetailField label="Mobile 2" :value="candidate.mobile2" copyable />
            <DetailField label="Phone (Home)" :value="candidate.phone_home" copyable />
            <DetailField label="Phone (Work)" :value="candidate.phone_work" copyable />
            <DetailField label="Address" :value="candidate.mailing_address" cols="12" sm="12" copyable />
          </v-row>
          <div v-if="candidate.linkedin_url" class="mt-3">
            <span class="field-label">LinkedIn</span>
            <div class="mt-1 d-flex align-center">
              <a :href="candidate.linkedin_url" target="_blank" class="text-primary text-body-1">
                <v-icon size="small" class="mr-1">mdi-linkedin</v-icon>{{ candidate.linkedin_url }}
              </a>
              <v-btn
                :icon="linkedinCopied ? 'mdi-check' : 'mdi-content-copy'"
                :color="linkedinCopied ? 'success' : undefined"
                size="x-small"
                variant="text"
                density="compact"
                class="ml-1 copy-btn-header"
                @click="copyText(candidate.linkedin_url, 'linkedin')"
              />
            </div>
          </div>
        </SectionCard>

        <!-- Work Experience -->
        <SectionCard title="Work Experience" icon="mdi-briefcase">
          <v-alert v-if="!candidate.work_experiences?.length" type="info" variant="tonal" density="compact" class="mb-2">
            無工作經驗
          </v-alert>
          <v-card
            v-for="(we, idx) in candidate.work_experiences"
            :key="we.id"
            variant="outlined"
            class="mb-4 pa-4"
          >
            <div class="d-flex justify-space-between align-start flex-wrap">
              <div>
                <div class="text-h6 font-weight-bold" style="font-size: 1.05rem !important">{{ we.job_title }}</div>
                <div class="text-body-1 font-weight-medium mt-1">
                  <v-icon size="x-small" class="mr-1">mdi-office-building</v-icon>{{ we.company_name }}
                </div>
              </div>
              <v-chip variant="tonal" color="primary" size="small">
                {{ we.date_start }} ~ {{ we.date_end }}
                <span v-if="we.duration"> ({{ we.duration }})</span>
              </v-chip>
            </div>
            <div v-if="we.industry || we.company_size || we.job_category" class="mt-2 d-flex flex-wrap ga-2">
              <v-chip v-if="we.industry" size="x-small" variant="outlined">{{ we.industry }}</v-chip>
              <v-chip v-if="we.company_size" size="x-small" variant="outlined">{{ we.company_size }}</v-chip>
              <v-chip v-if="we.job_category" size="x-small" variant="outlined">{{ we.job_category }}</v-chip>
              <v-chip v-if="we.management_responsibility && we.management_responsibility !== '無'" size="x-small" color="warning" variant="outlined">{{ we.management_responsibility }}</v-chip>
            </div>
            <div v-if="we.job_description" class="text-body-1 mt-3" style="white-space: pre-wrap; line-height: 1.7">
              {{ we.job_description }}
            </div>
          </v-card>
        </SectionCard>

        <!-- Education -->
        <SectionCard title="Education" icon="mdi-school">
          <div v-if="!candidate.education?.length" class="text-body-1 text-grey">
            No education records.
          </div>
          <v-card
            v-for="ed in candidate.education"
            :key="ed.id"
            variant="outlined"
            class="mb-4 pa-4"
          >
            <div class="d-flex justify-space-between align-start flex-wrap">
              <div>
                <div class="text-h6 font-weight-bold" style="font-size: 1.05rem !important">
                  <v-icon size="small" class="mr-1">mdi-school</v-icon>{{ ed.school }}
                </div>
                <div class="text-body-1 mt-1">
                  <strong>{{ ed.department }}</strong>
                  <span v-if="ed.degree_level"> &middot; {{ ed.degree_level }}</span>
                </div>
              </div>
              <v-chip variant="tonal" color="primary" size="small">
                {{ ed.date_start }} ~ {{ ed.date_end }}
              </v-chip>
            </div>
            <div v-if="ed.region || ed.status" class="mt-2 d-flex flex-wrap ga-2">
              <v-chip v-if="ed.region" size="x-small" variant="outlined">{{ ed.region }}</v-chip>
              <v-chip v-if="ed.status" size="x-small" variant="outlined" color="info">{{ ed.status }}</v-chip>
            </div>
          </v-card>
        </SectionCard>

        <!-- Skills -->
        <SectionCard title="Skills" icon="mdi-lightbulb-on">
          <div v-if="candidate.skill_tags?.length" class="mb-4">
            <v-chip
              v-for="tag in candidate.skill_tags"
              :key="tag"
              color="primary"
              variant="tonal"
              class="mr-2 mb-2"
            >
              {{ tag }}
            </v-chip>
          </div>
          <MarkdownContent v-if="candidate.skills_text" :content="candidate.skills_text" />
        </SectionCard>

        <!-- Self Introduction -->
        <SectionCard v-if="candidate.self_introduction" title="個人簡介" icon="mdi-text-box">
          <MarkdownContent :content="candidate.self_introduction" />
        </SectionCard>

        <!-- Personal Motto -->
        <SectionCard v-if="candidate.personal_motto" title="個人格言" icon="mdi-format-quote-close">
          <MarkdownContent :content="candidate.personal_motto" />
        </SectionCard>

        <!-- Personal Traits -->
        <SectionCard v-if="candidate.personal_traits" title="個人特色" icon="mdi-star-face">
          <MarkdownContent :content="candidate.personal_traits" />
        </SectionCard>

        <!-- Autobiography -->
        <SectionCard v-if="candidate.autobiography" title="自傳" icon="mdi-book-open-page-variant">
          <MarkdownContent :content="candidate.autobiography" />
        </SectionCard>

        <!-- Match Analysis (Enhanced ScoreCard) -->
        <SectionCard title="Match Analysis" icon="mdi-chart-bar">
          <div v-if="!match" class="d-flex align-center">
            <span class="text-body-1 text-grey mr-4">No match result yet.</span>
            <v-btn color="primary" :loading="matching" @click="doMatch">
              <v-icon start>mdi-play</v-icon> Run Match
            </v-btn>
          </div>
          <template v-else>
            <ScoreCard :match="match" />
            <v-btn color="primary" variant="outlined" class="mt-4" :loading="matching" @click="doMatch">
              <v-icon start>mdi-refresh</v-icon> Re-run Match
            </v-btn>
          </template>
        </SectionCard>

        <!-- Attachments -->
        <SectionCard v-if="candidate.attachments?.length" title="Attachments" icon="mdi-paperclip">
          <v-list lines="two">
            <v-list-item v-for="att in candidate.attachments" :key="att.id" class="px-0">
              <template #prepend>
                <v-avatar color="grey-lighten-3" size="40" rounded>
                  <v-icon color="grey-darken-1">mdi-file-document</v-icon>
                </v-avatar>
              </template>
              <v-list-item-title class="font-weight-bold">{{ att.name || att.attachment_type }}</v-list-item-title>
              <v-list-item-subtitle v-if="att.description">{{ att.description }}</v-list-item-subtitle>
            </v-list-item>
          </v-list>
        </SectionCard>
      </v-container>

      <!-- Loading state -->
      <v-container v-else class="d-flex justify-center align-center" style="min-height: 400px">
        <v-progress-circular indeterminate color="primary" size="48" />
      </v-container>
    </v-main>
  </v-layout>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchCandidate, fetchMatchResult, triggerMatch } from '../api'
import ScoreBadge from '../components/ScoreBadge.vue'
import TierBadge from '../components/TierBadge.vue'
import ScoreCard from '../components/ScoreCard.vue'
import SectionCard from '../components/SectionCard.vue'
import DetailField from '../components/DetailField.vue'
import MarkdownContent from '../components/MarkdownContent.vue'

const props = defineProps({
  id: { type: [String, Number], required: true },
})

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
const nameCopied = ref(false)
const codeCopied = ref(false)
const linkedinCopied = ref(false)

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
  const result = await fetchMatchResult(props.id)
  match.value = result.match
}

async function doMatch() {
  matching.value = true
  try {
    await triggerMatch(props.id)
    // Poll for result
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

<style scoped>
.field-label {
  font-size: 0.78rem;
  font-weight: 600;
  color: #757575;
  text-transform: uppercase;
  letter-spacing: 0.03em;
}
.copy-btn-header {
  opacity: 0.35;
  transition: opacity 0.15s;
}
.copy-btn-header:hover {
  opacity: 1;
}
</style>
