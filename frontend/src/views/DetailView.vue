<template>
  <div class="h-full overflow-y-auto">
    <!-- Header bar -->
    <div class="sticky top-0 z-10 flex items-center gap-3 px-5 py-3 bg-white/90 backdrop-blur border-b border-gray-200">
      <button
        @click="$router.push({ name: 'list' })"
        class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
      </button>
      <span class="text-sm font-semibold text-gray-900">{{ candidate?.name || 'Candidate' }}</span>
      <span
        v-if="isInterested"
        class="text-xs font-semibold bg-amber-50 text-amber-600 border border-amber-200 rounded-full px-2 py-0.5"
      >感興趣</span>
      <span
        v-if="isInvited"
        class="text-xs font-semibold bg-emerald-50 text-emerald-600 border border-emerald-200 rounded-full px-2 py-0.5"
      >邀請已發</span>
      <div class="ml-auto flex items-center gap-2">
        <!-- Bookmark / Interested toggle -->
        <button
          v-if="candidate"
          @click="bookmarkStore.toggle(Number(id))"
          :title="isInterested ? '取消標記' : '標記為感興趣'"
          :class="[
            'p-1.5 rounded-lg transition',
            isInterested ? 'text-amber-400 hover:text-amber-500' : 'text-gray-300 hover:text-gray-500 hover:bg-gray-100'
          ]"
        >
          <svg class="w-5 h-5" :fill="isInterested ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
          </svg>
        </button>
        <!-- Invitation sent toggle -->
        <button
          v-if="candidate"
          @click="invitationStore.toggle(Number(id))"
          :title="isInvited ? '取消邀請標記' : '標記已發邀請'"
          :class="[
            'p-1.5 rounded-lg transition',
            isInvited ? 'text-emerald-500 hover:text-emerald-600' : 'text-gray-300 hover:text-gray-500 hover:bg-gray-100'
          ]"
        >
          <svg class="w-5 h-5" :fill="isInvited ? 'currentColor' : 'none'" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M21.75 6.75v10.5a2.25 2.25 0 01-2.25 2.25h-15a2.25 2.25 0 01-2.25-2.25V6.75m19.5 0A2.25 2.25 0 0019.5 4.5h-15a2.25 2.25 0 00-2.25 2.25m19.5 0v.243a2.25 2.25 0 01-1.07 1.916l-7.5 4.615a2.25 2.25 0 01-2.36 0L3.32 8.91a2.25 2.25 0 01-1.07-1.916V6.75" />
          </svg>
        </button>
        <ScoreBadge v-if="match" :score="match.overall_score" size="default" />
      </div>
    </div>

    <!-- Loading -->
    <div v-if="!candidate" class="flex items-center justify-center min-h-[400px]">
      <div class="flex flex-col items-center gap-3 text-gray-400">
        <svg class="w-8 h-8 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
        </svg>
        <span class="text-sm">Loading…</span>
      </div>
    </div>

    <!-- Content -->
    <div v-else class="max-w-4xl mx-auto px-5 py-6 space-y-0">

      <!-- Hero card -->
      <div class="rounded-xl border border-gray-300 bg-white shadow-sm mb-5 p-6">
        <div class="flex items-start gap-5">
          <!-- Avatar -->
          <div class="w-20 h-20 rounded-xl bg-blue-100 text-blue-700 font-bold text-2xl flex items-center justify-center shrink-0 overflow-hidden">
            <img v-if="candidate.photo_url" :src="candidate.photo_url" class="w-full h-full object-cover" />
            <span v-else>{{ candidate.name?.charAt(0) || '?' }}</span>
          </div>

          <div class="flex-1 min-w-0">
            <!-- Name row -->
            <div class="flex items-center gap-2 flex-wrap">
              <h1 class="text-2xl font-bold text-gray-900">{{ candidate.name }}</h1>
              <button
                class="p-1 rounded text-gray-300 hover:text-gray-600 transition"
                @click="copyText(candidate.name, 'name')"
                title="Copy name"
              >
                <svg v-if="!nameCopied" class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <svg v-else class="w-4 h-4 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </button>
              <span v-if="candidate.english_name" class="text-base text-gray-400 font-normal">{{ candidate.english_name }}</span>
            </div>

            <!-- 104 Code -->
            <div v-if="candidate.code_104" class="flex items-center gap-1.5 mt-1 text-sm text-gray-500">
              <span class="font-mono text-xs bg-gray-100 rounded px-1.5 py-0.5 text-gray-600">{{ candidate.code_104 }}</span>
              <button @click="copyText(candidate.code_104, 'code')" class="text-gray-300 hover:text-gray-600 transition">
                <svg v-if="!codeCopied" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
                </svg>
                <svg v-else class="w-3.5 h-3.5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
                </svg>
              </button>
            </div>

            <!-- Summary line -->
            <div class="mt-2 text-sm text-gray-600 flex flex-wrap gap-1.5 items-center">
              <span v-if="calculatedAge != null" class="font-semibold text-gray-800">{{ calculatedAge }} 歲</span>
              <span v-if="calculatedAge != null" class="text-gray-300">·</span>
              <span class="font-semibold text-gray-800">{{ candidate.education_level }}</span>
              <span v-if="candidate.school" class="text-gray-300">·</span>
              <span v-if="candidate.school">{{ candidate.school }}</span>
              <span class="text-gray-300">·</span>
              <span>{{ candidate.years_of_experience || '無工作經驗' }}</span>
            </div>

            <div v-if="candidate.ideal_positions?.length" class="mt-1 text-sm text-gray-500">
              {{ candidate.ideal_positions.join(' / ') }}
            </div>

            <!-- Score badges -->
            <div v-if="match" class="mt-3 flex items-center gap-2 flex-wrap">
              <span class="text-xs font-semibold text-gray-400 uppercase tracking-wide">Match Score</span>
              <ScoreBadge :score="match.overall_score" size="large" />
              <TierBadge
                v-if="match.experience_detail?.tier"
                :tier="match.experience_detail.tier"
                :tier-label="match.experience_detail.tier_label"
              />
            </div>
          </div>
        </div>
      </div>

      <!-- Basic Information -->
      <SectionCard title="Basic Information">
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-x-4">
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
        </div>
        <div v-if="candidate.desired_locations?.length" class="mt-3">
          <div class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Desired Locations</div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="loc in candidate.desired_locations" :key="loc" class="text-xs bg-purple-50 text-purple-700 border border-purple-100 rounded-full px-2.5 py-0.5">{{ loc }}</span>
          </div>
        </div>
        <div v-if="candidate.desired_job_categories?.length" class="mt-3">
          <div class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1.5">Job Categories</div>
          <div class="flex flex-wrap gap-1.5">
            <span v-for="cat in candidate.desired_job_categories" :key="cat" class="text-xs bg-gray-100 text-gray-600 border border-gray-200 rounded-full px-2.5 py-0.5">{{ cat }}</span>
          </div>
        </div>
      </SectionCard>

      <!-- Contact -->
      <SectionCard title="Contact">
        <div class="grid grid-cols-2 sm:grid-cols-3 gap-x-4">
          <DetailField label="Email" :value="candidate.email" copyable />
          <DetailField label="Mobile 1" :value="candidate.mobile1" copyable />
          <DetailField label="Mobile 2" :value="candidate.mobile2" copyable />
          <DetailField label="Phone (Home)" :value="candidate.phone_home" copyable />
          <DetailField label="Phone (Work)" :value="candidate.phone_work" copyable />
          <DetailField label="Address" :value="candidate.mailing_address" copyable />
        </div>
        <div v-if="candidate.linkedin_url" class="mt-3">
          <div class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-1">LinkedIn</div>
          <div class="flex items-center gap-2">
            <a :href="candidate.linkedin_url" target="_blank" class="text-sm text-blue-600 hover:underline truncate max-w-xs">
              {{ candidate.linkedin_url }}
            </a>
            <button @click="copyText(candidate.linkedin_url, 'linkedin')" class="text-gray-300 hover:text-gray-600 transition shrink-0">
              <svg v-if="!linkedinCopied" class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8 16H6a2 2 0 01-2-2V6a2 2 0 012-2h8a2 2 0 012 2v2m-6 12h8a2 2 0 002-2v-8a2 2 0 00-2-2h-8a2 2 0 00-2 2v8a2 2 0 002 2z" />
              </svg>
              <svg v-else class="w-3.5 h-3.5 text-green-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </button>
          </div>
        </div>
      </SectionCard>

      <!-- Work Experience -->
      <SectionCard title="Work Experience">
        <div v-if="!candidate.work_experiences?.length" class="text-sm text-gray-400 py-2">無工作經驗</div>
        <div
          v-for="we in candidate.work_experiences"
          :key="we.id"
          class="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-3 last:mb-0"
        >
          <div class="flex justify-between items-start gap-3 flex-wrap mb-2">
            <div>
              <div class="font-semibold text-gray-900">{{ we.job_title }}</div>
              <div class="text-sm text-gray-600 mt-0.5">{{ we.company_name }}</div>
            </div>
            <span class="text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded-full px-2.5 py-1 shrink-0">
              {{ we.date_start }} ~ {{ we.date_end }}
              <span v-if="we.duration"> ({{ we.duration }})</span>
            </span>
          </div>
          <div v-if="we.industry || we.company_size || we.job_category || we.management_responsibility" class="flex flex-wrap gap-1.5 mb-2">
            <span v-if="we.industry" class="text-xs bg-gray-100 text-gray-600 rounded-full px-2 py-0.5">{{ we.industry }}</span>
            <span v-if="we.company_size" class="text-xs bg-gray-100 text-gray-600 rounded-full px-2 py-0.5">{{ we.company_size }}</span>
            <span v-if="we.job_category" class="text-xs bg-gray-100 text-gray-600 rounded-full px-2 py-0.5">{{ we.job_category }}</span>
            <span v-if="we.management_responsibility && we.management_responsibility !== '無'" class="text-xs bg-amber-50 text-amber-700 border border-amber-100 rounded-full px-2 py-0.5">{{ we.management_responsibility }}</span>
          </div>
          <div v-if="we.job_description" class="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">{{ we.job_description }}</div>
        </div>
      </SectionCard>

      <!-- Education -->
      <SectionCard title="Education">
        <div v-if="!candidate.education?.length" class="text-sm text-gray-400 py-2">No education records.</div>
        <div
          v-for="ed in candidate.education"
          :key="ed.id"
          class="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-3 last:mb-0"
        >
          <div class="flex justify-between items-start gap-3 flex-wrap mb-2">
            <div>
              <div class="font-semibold text-gray-900">{{ ed.school }}</div>
              <div class="text-sm text-gray-600 mt-0.5">
                {{ ed.department }}<span v-if="ed.degree_level"> · {{ ed.degree_level }}</span>
              </div>
            </div>
            <span class="text-xs bg-blue-50 text-blue-700 border border-blue-100 rounded-full px-2.5 py-1 shrink-0">
              {{ ed.date_start }} ~ {{ ed.date_end }}
            </span>
          </div>
          <div v-if="ed.region || ed.status" class="flex flex-wrap gap-1.5">
            <span v-if="ed.region" class="text-xs bg-gray-100 text-gray-600 rounded-full px-2 py-0.5">{{ ed.region }}</span>
            <span v-if="ed.status" class="text-xs bg-sky-50 text-sky-700 border border-sky-100 rounded-full px-2 py-0.5">{{ ed.status }}</span>
          </div>
        </div>
      </SectionCard>

      <!-- Skills -->
      <SectionCard title="Skills">
        <div v-if="candidate.skill_tags?.length" class="flex flex-wrap gap-1.5 mb-4">
          <span
            v-for="tag in candidate.skill_tags"
            :key="tag"
            class="text-sm bg-blue-50 text-blue-700 border border-blue-200 rounded-full px-3 py-1 font-medium"
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
      <SectionCard title="Match Analysis">
        <div v-if="!match" class="flex items-center gap-4 py-2">
          <span class="text-sm text-gray-400">No match result yet.</span>
          <button
            @click="doMatch"
            :disabled="matching"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
          >
            <svg class="w-4 h-4" :class="{ 'animate-spin': matching }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" />
              <path stroke-linecap="round" stroke-linejoin="round" d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {{ matching ? 'Running…' : 'Run Match' }}
          </button>
        </div>
        <template v-else>
          <ScoreCard :match="match" />
          <button
            @click="doMatch"
            :disabled="matching"
            class="mt-4 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium border border-gray-200 rounded-lg text-gray-600 hover:border-gray-300 hover:text-gray-800 disabled:opacity-50 transition"
          >
            <svg class="w-4 h-4" :class="{ 'animate-spin': matching }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {{ matching ? 'Running…' : 'Re-run Match' }}
          </button>
        </template>
      </SectionCard>

      <!-- Interview Questions (shown only when bookmarked / "interested") -->
      <SectionCard v-if="isInterested" title="面試問題">
        <div v-if="!interviewQuestions && !generatingQuestions" class="flex items-center gap-4 py-2">
          <span class="text-sm text-gray-400">點擊生成針對此候選人量身訂製的中文面試問題。</span>
          <button
            @click="doGenerateQuestions"
            class="inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-semibold bg-emerald-600 text-white rounded-lg hover:bg-emerald-700 transition"
          >
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            生成面試問題
          </button>
        </div>

        <div v-else-if="questionsError" class="flex items-start gap-3 py-3">
          <svg class="w-5 h-5 text-red-400 shrink-0 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
          <div>
            <div class="text-sm text-red-600 font-medium">生成失敗</div>
            <div class="text-xs text-gray-400 mt-0.5">{{ questionsError }}</div>
            <button @click="doGenerateQuestions" class="mt-2 text-xs text-blue-600 hover:underline">重試</button>
          </div>
        </div>

        <div v-else-if="generatingQuestions" class="flex items-center gap-3 py-4 text-gray-400">
          <svg class="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          <span class="text-sm">AI 正在生成面試問題…</span>
        </div>

        <template v-else-if="interviewQuestions">
          <!-- Group by category -->
          <div v-for="(group, cat) in groupedQuestions" :key="cat" class="mb-5 last:mb-0">
            <div class="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-2 flex items-center gap-2">
              <span class="w-2 h-2 rounded-full bg-emerald-400 inline-block"></span>
              {{ cat }}
            </div>
            <div v-for="(q, idx) in group" :key="idx" class="bg-gray-50 border border-gray-200 rounded-lg p-4 mb-2 last:mb-0">
              <div class="text-sm font-medium text-gray-800 leading-relaxed">{{ q.question }}</div>
              <div v-if="q.purpose" class="mt-1.5 text-xs text-gray-400 italic">目的：{{ q.purpose }}</div>
            </div>
          </div>
          <button
            @click="doGenerateQuestions"
            :disabled="generatingQuestions"
            class="mt-2 inline-flex items-center gap-1.5 px-3 py-1.5 text-sm font-medium border border-gray-200 rounded-lg text-gray-600 hover:border-gray-300 hover:text-gray-800 disabled:opacity-50 transition"
          >
            <svg class="w-4 h-4" :class="{ 'animate-spin': generatingQuestions }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            重新生成
          </button>
        </template>
      </SectionCard>

      <!-- Attachments -->
      <SectionCard v-if="candidate.attachments?.length" title="Attachments">
        <div class="space-y-2">
          <div
            v-for="att in candidate.attachments"
            :key="att.id"
            class="flex items-center gap-3 p-3 bg-gray-50 rounded-lg border border-gray-100"
          >
            <div class="w-8 h-8 bg-gray-200 rounded-lg flex items-center justify-center shrink-0">
              <svg class="w-4 h-4 text-gray-500" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
              </svg>
            </div>
            <div>
              <div class="text-sm font-semibold text-gray-800">{{ att.name || att.attachment_type }}</div>
              <div v-if="att.description" class="text-xs text-gray-500">{{ att.description }}</div>
            </div>
          </div>
        </div>
      </SectionCard>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchCandidate, fetchMatchResult, triggerMatch, generateInterviewQuestions } from '../api'
import { useBookmarkStore } from '../stores/bookmarks'
import { useInvitationStore } from '../stores/invitations'
import ScoreBadge from '../components/ScoreBadge.vue'
import TierBadge from '../components/TierBadge.vue'
import ScoreCard from '../components/ScoreCard.vue'
import SectionCard from '../components/SectionCard.vue'
import DetailField from '../components/DetailField.vue'
import MarkdownContent from '../components/MarkdownContent.vue'

const props = defineProps({
  id: { type: [String, Number], required: true },
})

const bookmarkStore = useBookmarkStore()
const invitationStore = useInvitationStore()
const isInterested = computed(() => bookmarkStore.has(Number(props.id)))
const isInvited = computed(() => invitationStore.has(Number(props.id)))

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
