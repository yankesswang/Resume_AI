<template>
  <div class="flex flex-col h-full overflow-hidden">

    <!-- Toolbar -->
    <div class="flex items-center gap-3 px-5 py-3 bg-surface border-b border-line shrink-0">
      <button
        @click="router.push('/')"
        class="p-1.5 rounded-control text-ink-faint hover:text-ink hover:bg-surface-2 transition"
      >
        <ChevronLeft class="h-4 w-4" :stroke-width="2.5" />
      </button>
      <div class="flex items-center gap-2">
        <Star class="h-4 w-4 text-warn-ink" />
        <h1 class="text-small font-semibold text-ink">感興趣人選</h1>
        <span class="text-micro bg-warn-soft text-warn-ink rounded-full px-2 py-0.5 font-semibold">{{ bookmarks.count }}</span>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <span v-if="batchQStatus" class="text-micro text-good-ink font-medium">{{ batchQStatus }}</span>
        <!-- Add Candidate manually -->
        <button
          @click="showAddModal = true"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-micro font-semibold border border-brand-line rounded-control text-brand-ink hover:border-brand hover:bg-brand-soft transition"
        >
          <Plus class="h-3.5 w-3.5" :stroke-width="2" />
          新增人選
        </button>
        <button
          :disabled="bookmarks.count === 0 || batchQRunning"
          @click="batchGenQuestions"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-micro font-semibold border border-good-line rounded-control text-good-ink hover:border-good-line hover:bg-good-soft disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <HelpCircle class="h-3.5 w-3.5" :class="{ 'animate-spin': batchQRunning }" :stroke-width="2" />
          {{ batchQRunning ? '生成中…' : '生成面試問題' }}
        </button>
        <button
          :disabled="bookmarks.count === 0 || exporting"
          @click="downloadCsv"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-micro font-semibold border border-line rounded-control text-ink-muted hover:border-line-strong hover:text-ink disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <Download class="h-3.5 w-3.5" :class="{ 'animate-spin': exporting }" :stroke-width="2" />
          {{ exporting ? '匯出中…' : '匯出 CSV' }}
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="bookmarks.count === 0" class="flex-1 flex flex-col items-center justify-center text-center px-6">
      <Star class="h-16 w-16 text-ink-faint mb-4" :stroke-width="1" />
      <h3 class="text-small font-semibold text-ink-muted mb-1">尚未標記任何人選</h3>
      <p class="text-micro text-ink-faint mb-5">Star candidates from the list to save them here.</p>
      <button
        @click="router.push('/')"
        class="inline-flex items-center gap-1.5 px-4 py-2 text-small font-semibold bg-brand text-white rounded-control hover:bg-brand-hover transition"
      >
        <ChevronLeft class="h-4 w-4" :stroke-width="2" />
        Back to List
      </button>
    </div>

    <!-- Table -->
    <div v-else class="flex-1 overflow-auto p-5">
      <div class="bg-surface border border-line rounded-card overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-small">
            <thead>
              <tr class="border-b border-line bg-surface-2">
                <th class="w-10 px-3 py-2.5"></th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">姓名</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">學歷</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">學校</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">總分</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">技能</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">面試進度</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">面試日期</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">作業繳交日期</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">可到職日</th>
                <th class="px-3 py-2.5 text-left text-micro font-semibold text-ink-muted whitespace-nowrap">簡歷備注</th>
              </tr>
            </thead>

            <tbody class="divide-y divide-line" @click="closeStatusDropdown">
              <tr
                v-for="item in candidates"
                :key="item.id"
                class="hover:bg-warn-soft/20 transition-colors group"
                :class="{ 'opacity-60': rowSaving[item.id] }"
              >
                <!-- Actions: unstar + delete -->
                <td class="px-3 py-2 text-center">
                  <div class="flex items-center justify-center gap-1">
                    <button
                      @click="removeBookmark(item.id)"
                      class="text-warn-ink hover:text-ink-faint transition opacity-50 group-hover:opacity-100"
                      title="Remove from interested"
                    >
                      <Star class="h-4 w-4" />
                    </button>
                    <button
                      @click="deleteRow(item.id, item.name)"
                      class="text-ink-faint hover:text-bad-ink transition opacity-0 group-hover:opacity-100"
                      title="Delete candidate permanently"
                    >
                      <Trash2 class="h-3.5 w-3.5" :stroke-width="2" />
                    </button>
                  </div>
                </td>

                <!-- Name -->
                <td class="px-3 py-2 cursor-pointer" @click="router.push(`/candidate/${item.id}`)">
                  <div class="flex items-center gap-2">
                    <div class="h-7 w-7 rounded-full bg-surface-2 text-ink-muted text-micro font-bold flex items-center justify-center shrink-0 overflow-hidden">
                      <img v-if="item.photo_url" :src="item.photo_url" class="h-full w-full object-cover" />
                      <span v-else>{{ item.name?.charAt(0) || '?' }}</span>
                    </div>
                    <span class="font-semibold text-ink whitespace-nowrap hover:text-brand-ink transition-colors">{{ item.name || '—' }}</span>
                    <span
                      v-if="item.candidate_type"
                      :class="[
                        'text-micro font-semibold border rounded-full px-2 py-0.5 whitespace-nowrap',
                        item.candidate_type === '實習'
                          ? 'bg-info-soft text-info-ink border-info-line'
                          : 'bg-neutral-soft text-neutral-ink border-neutral-line'
                      ]"
                    >{{ item.candidate_type === '實習' ? '實習' : '工程師' }}</span>
                    <!-- Per-row save indicator -->
                    <Check class="h-3.5 w-3.5 text-good-ink shrink-0" :stroke-width="3" v-if="rowSaved[item.id]" />
                    <RefreshCw class="h-3.5 w-3.5 text-ink-faint shrink-0 animate-spin" :stroke-width="2" v-if="rowSaving[item.id]" />
                  </div>
                </td>

                <!-- Education -->
                <td class="px-3 py-2 text-ink-muted text-micro whitespace-nowrap">{{ item.education_level || '—' }}</td>

                <!-- School -->
                <td class="px-3 py-2 text-ink-muted text-micro whitespace-nowrap">{{ item.school || '—' }}</td>

                <!-- Score -->
                <td class="px-3 py-2">
                  <ScoreBadge :score="item.overall_score" />
                </td>

                <!-- 技能 -->
                <td class="px-3 py-2">
                  <div class="flex flex-wrap gap-1">
                    <span
                      v-for="tag in (item.skill_tags || []).slice(0, 3)"
                      :key="tag"
                      class="text-micro bg-info-soft text-info-ink border border-info-line rounded-full px-2 py-0.5 whitespace-nowrap"
                    >{{ tag }}</span>
                    <span v-if="(item.skill_tags || []).length > 3" class="text-micro text-ink-faint px-1">+{{ item.skill_tags.length - 3 }}</span>
                  </div>
                </td>

                <!-- 面試進度 — inline dropdown -->
                <td class="px-2 py-2" @click.stop>
                  <div class="relative">
                    <button
                      @click.stop="toggleStatusDropdown(item.id)"
                      class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-control border transition text-micro w-full min-w-[120px] text-left"
                      :class="rowForms[item.id]?.status
                        ? 'border-line bg-surface hover:border-line-strong'
                        : 'border-dashed border-line bg-surface-2 hover:border-line-strong hover:bg-surface'"
                    >
                      <template v-if="rowForms[item.id]?.status">
                        <span :class="['h-2 w-2 rounded-full shrink-0', statusDotClass(rowForms[item.id].status)]"></span>
                        <span class="font-semibold flex-1 truncate" :class="statusTextClass(rowForms[item.id].status)">
                          {{ rowForms[item.id].status }}
                        </span>
                      </template>
                      <span v-else class="text-ink-faint italic flex-1">選擇進度…</span>
                      <ChevronDown class="h-3 w-3 text-ink-faint shrink-0" :stroke-width="2.5" />
                    </button>

                    <!-- Dropdown menu -->
                    <div
                      v-if="activeStatusDropdown === item.id"
                      class="absolute z-50 left-0 top-full mt-1 bg-surface border border-line rounded-card shadow-xl min-w-[180px] overflow-hidden"
                      @click.stop
                    >
                      <button
                        v-if="rowForms[item.id]?.status"
                        @click="selectStatus(item.id, null)"
                        class="w-full text-left px-3 py-2 text-micro text-ink-faint italic hover:bg-surface-2 border-b border-line"
                      >清除</button>

                      <button
                        v-for="s in store.statuses"
                        :key="s.id"
                        @click="selectStatus(item.id, s.label)"
                        class="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-surface-2 text-left"
                      >
                        <span :class="['h-2 w-2 rounded-full shrink-0', COLOR_DOTS[s.color] || 'bg-ink-faint']"></span>
                        <span class="text-small text-ink flex-1">{{ s.label }}</span>
                        <Check class="h-3.5 w-3.5 text-good-ink shrink-0" :stroke-width="3" v-if="rowForms[item.id]?.status === s.label" />
                      </button>

                      <!-- Add custom status -->
                      <div class="border-t border-line px-3 py-2.5 bg-surface-2">
                        <p class="text-micro font-semibold text-ink-faint mb-2">新增選項</p>
                        <div class="flex gap-1.5">
                          <input
                            v-model="newStatusLabel"
                            @keydown.enter.prevent="addStatusInline(item.id)"
                            @click.stop
                            placeholder="狀態名稱…"
                            class="field flex-1 text-micro"
                          />
                          <button
                            @click="addStatusInline(item.id)"
                            :disabled="!newStatusLabel.trim()"
                            class="btn btn-primary shrink-0 text-micro"
                          >+</button>
                        </div>
                      </div>
                    </div>
                  </div>
                </td>

                <!-- 面試日期 + 時間 -->
                <td class="px-2 py-2" @click.stop>
                  <div class="flex flex-col gap-1" v-if="rowForms[item.id]">
                    <input
                      type="date"
                      v-model="rowForms[item.id].date"
                      @change="saveRow(item.id)"
                      class="field w-[132px] text-micro"
                    />
                    <input
                      type="time"
                      v-model="rowForms[item.id].time"
                      @change="saveRow(item.id)"
                      class="field w-[132px] text-micro"
                    />
                  </div>
                </td>

                <!-- 作業繳交日期 -->
                <td class="px-2 py-2" @click.stop>
                  <input
                    v-if="rowForms[item.id]"
                    type="date"
                    v-model="rowForms[item.id].assignmentDueDate"
                    @change="saveRow(item.id)"
                    class="field w-[132px] text-micro"
                  />
                </td>

                <!-- 可到職日 -->
                <td class="px-2 py-2" @click.stop>
                  <input
                    v-if="rowForms[item.id]"
                    type="date"
                    v-model="rowForms[item.id].availableStartDate"
                    @change="saveRow(item.id)"
                    class="field w-[132px] text-micro"
                  />
                </td>

                <!-- 簡歷備注 -->
                <td class="px-2 py-2" @click.stop>
                  <input
                    v-if="rowForms[item.id]"
                    type="text"
                    v-model="rowForms[item.id].resumeNotes"
                    @blur="saveRow(item.id)"
                    @keydown.enter="saveRow(item.id); $event.target.blur()"
                    placeholder="備注…"
                    class="field w-full min-w-[140px] text-micro"
                  />
                </td>
              </tr>

              <tr v-if="loading">
                <td colspan="11" class="px-6 py-12 text-center text-ink-faint text-small">Loading…</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="px-4 py-2.5 border-t border-line text-micro text-ink-faint bg-surface-2">
          {{ candidates.length }} candidate{{ candidates.length !== 1 ? 's' : '' }} bookmarked
        </div>
      </div>
    </div>

    <!-- Add Candidate Modal -->
    <Teleport to="body">
      <div
        v-if="showAddModal"
        class="fixed inset-0 z-50 flex items-center justify-center"
        @click.self="closeAddModal"
      >
        <div class="absolute inset-0 bg-black/40 backdrop-blur-sm"></div>
        <div class="relative bg-surface rounded-card shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
          <!-- Modal header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-line">
            <h2 class="text-small font-semibold text-ink">手動新增人選</h2>
            <button @click="closeAddModal" class="p-1.5 rounded-control text-ink-faint hover:text-ink hover:bg-surface-2 transition">
              <X class="h-4 w-4" :stroke-width="2" />
            </button>
          </div>

          <!-- Modal form -->
          <form @submit.prevent="submitAddCandidate" class="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
            <!-- Name -->
            <div>
              <label class="block text-micro font-semibold text-ink-muted mb-1">姓名 <span class="text-bad-ink">*</span></label>
              <input
                v-model="addForm.name"
                type="text"
                required
                placeholder="Candidate full name"
                class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition"
              />
            </div>

            <!-- Email + Phone -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-micro font-semibold text-ink-muted mb-1">Email</label>
                <input
                  v-model="addForm.email"
                  type="email"
                  placeholder="email@example.com"
                  class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition"
                />
              </div>
              <div>
                <label class="block text-micro font-semibold text-ink-muted mb-1">聯絡電話</label>
                <input
                  v-model="addForm.mobile"
                  type="text"
                  placeholder="0912-345-678"
                  class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition"
                />
              </div>
            </div>

            <!-- Education + School -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-micro font-semibold text-ink-muted mb-1">最高學歷</label>
                <select
                  v-model="addForm.education_level"
                  class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition bg-surface"
                >
                  <option value="">請選擇</option>
                  <option value="高中">高中</option>
                  <option value="大專">大專</option>
                  <option value="大學">大學</option>
                  <option value="碩士">碩士</option>
                  <option value="博士">博士</option>
                </select>
              </div>
              <div>
                <label class="block text-micro font-semibold text-ink-muted mb-1">學校</label>
                <input
                  v-model="addForm.school"
                  type="text"
                  placeholder="University / College"
                  class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition"
                />
              </div>
            </div>

            <!-- Years of experience + Expected salary -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-micro font-semibold text-ink-muted mb-1">工作年資</label>
                <input
                  v-model="addForm.years_of_experience"
                  type="text"
                  placeholder="e.g. 5年"
                  class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition"
                />
              </div>
              <div>
                <label class="block text-micro font-semibold text-ink-muted mb-1">期望薪資</label>
                <input
                  v-model="addForm.desired_salary"
                  type="text"
                  placeholder="e.g. 80,000"
                  class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition"
                />
              </div>
            </div>

            <!-- Skills -->
            <div>
              <label class="block text-micro font-semibold text-ink-muted mb-1">技能 <span class="text-ink-faint font-normal">(comma-separated)</span></label>
              <input
                v-model="addForm.skillsInput"
                type="text"
                placeholder="Python, React, SQL, …"
                class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition"
              />
            </div>

            <!-- Notes -->
            <div>
              <label class="block text-micro font-semibold text-ink-muted mb-1">備註</label>
              <textarea
                v-model="addForm.notes"
                rows="3"
                placeholder="Any additional notes about this candidate…"
                class="w-full px-3 py-2 text-small border border-line rounded-control focus:outline-none focus:ring-2 focus:ring-brand focus:border-brand transition resize-none"
              ></textarea>
            </div>

            <!-- Error -->
            <p v-if="addError" class="text-micro text-bad-ink">{{ addError }}</p>
          </form>

          <!-- Modal footer -->
          <div class="flex items-center justify-end gap-2 px-6 py-4 border-t border-line bg-surface-2">
            <button
              type="button"
              @click="closeAddModal"
              class="px-4 py-2 text-micro font-semibold text-ink-muted hover:text-ink transition"
            >
              Cancel
            </button>
            <button
              type="button"
              :disabled="!addForm.name.trim() || addSubmitting"
              @click="submitAddCandidate"
              class="inline-flex items-center gap-1.5 px-4 py-2 text-micro font-semibold bg-brand text-white rounded-control hover:bg-brand-hover disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              <RefreshCw class="h-3.5 w-3.5 animate-spin" :stroke-width="2" v-if="addSubmitting" />
              {{ addSubmitting ? 'Adding…' : 'Add & Mark Interested' }}
            </button>
          </div>
        </div>
      </div>
    </Teleport>

  </div>
</template>

<script>
export default { name: 'BookmarksView' }
</script>

<script setup>
import { ref, watch, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useBookmarkStore } from '../stores/bookmarks'
import { useInterviewStore } from '../stores/interviews'
import { exportCandidates, exportCandidatesCsv, batchInterviewQuestions, createManualCandidate, deleteCandidate } from '../api'
import ScoreBadge from '../components/ScoreBadge.vue'
import { Check, ChevronDown, ChevronLeft, Download, HelpCircle, Plus, RefreshCw, Star, Trash2, X } from 'lucide-vue-next'

// ── Color maps (fully spelled-out so Tailwind won't purge) ──
const COLOR_DOTS = {
  blue: 'bg-blue-500', purple: 'bg-purple-500', indigo: 'bg-indigo-500',
  green: 'bg-green-500', emerald: 'bg-emerald-500', teal: 'bg-teal-500',
  yellow: 'bg-yellow-400', orange: 'bg-orange-500', red: 'bg-red-500',
  pink: 'bg-pink-500', gray: 'bg-ink-faint',
}
const COLOR_TEXT = {
  blue: 'text-brand-ink', purple: 'text-expert-ink', indigo: 'text-info-ink',
  green: 'text-good-ink', emerald: 'text-good-ink', teal: 'text-info-ink',
  yellow: 'text-yellow-700', orange: 'text-orange-700', red: 'text-bad-ink',
  pink: 'text-pink-700', gray: 'text-ink-muted',
}

const router = useRouter()
const bookmarks = useBookmarkStore()
const store = useInterviewStore()

const candidates = ref([])
const loading = ref(false)
const exporting = ref(false)
const batchQRunning = ref(false)
const batchQStatus = ref('')

// ── Inline edit state ──
const rowForms = ref({})   // { [candidateId]: { date, time, type, status, assignmentDueDate, availableStartDate, resumeNotes } }
const rowSaving = ref({})  // { [candidateId]: true }
const rowSaved = ref({})   // { [candidateId]: true } — briefly shown after save
const activeStatusDropdown = ref(null)
const newStatusLabel = ref('')

// ── Add Candidate Modal ──
const showAddModal = ref(false)
const addSubmitting = ref(false)
const addError = ref('')
const addForm = ref({
  name: '',
  email: '',
  mobile: '',
  education_level: '',
  school: '',
  years_of_experience: '',
  desired_salary: '',
  skillsInput: '',
  notes: '',
})

function closeAddModal() {
  showAddModal.value = false
  addError.value = ''
  addForm.value = {
    name: '', email: '', mobile: '', education_level: '', school: '',
    years_of_experience: '', desired_salary: '', skillsInput: '', notes: '',
  }
}

async function submitAddCandidate() {
  if (!addForm.value.name.trim()) return
  addSubmitting.value = true
  addError.value = ''
  try {
    const skillTags = addForm.value.skillsInput
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
    await createManualCandidate({
      name: addForm.value.name.trim(),
      email: addForm.value.email || null,
      mobile: addForm.value.mobile || null,
      education_level: addForm.value.education_level || null,
      school: addForm.value.school || null,
      years_of_experience: addForm.value.years_of_experience || null,
      desired_salary: addForm.value.desired_salary || null,
      skills_text: addForm.value.skillsInput || null,
      skill_tags: skillTags,
    })
    await bookmarks.load()
    closeAddModal()
  } catch (err) {
    console.error('Failed to add candidate:', err)
    addError.value = 'Failed to add candidate. Please try again.'
  } finally {
    addSubmitting.value = false
  }
}

// ── Helpers ──
function toDateStr(d) {
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const dd = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${dd}`
}

function statusColorFor(label) {
  return store.statuses.find((s) => s.label === label)?.color || 'gray'
}
function statusDotClass(label) {
  return COLOR_DOTS[statusColorFor(label)] || 'bg-ink-faint'
}
function statusTextClass(label) {
  return COLOR_TEXT[statusColorFor(label)] || 'text-ink'
}

// ── Form init ──
function initRowForm(candidateId) {
  const iv = store.latestByCandidate[candidateId]
  rowForms.value[candidateId] = {
    date: iv?.interview_date || '',
    time: iv?.interview_time?.slice(0, 5) || '',
    type: iv?.interview_type || 'onsite',
    status: iv?.status || null,
    assignmentDueDate: iv?.assignment_due_date || '',
    availableStartDate: iv?.available_start_date || '',
    resumeNotes: iv?.resume_notes || '',
  }
}

function syncForms() {
  for (const c of candidates.value) initRowForm(c.id)
}

// Re-sync when candidates list or interview data changes
watch(candidates, syncForms, { immediate: true })
watch(() => store.interviews, syncForms)

// ── Save ──
async function saveRow(candidateId) {
  const form = rowForms.value[candidateId]
  if (!form) return
  const existingId = store.latestByCandidate[candidateId]?.id
  const date = form.date || toDateStr(new Date())

  rowSaving.value[candidateId] = true
  try {
    await store.saveInterview({
      candidate_id: candidateId,
      interview_date: date,
      interview_time: form.time || null,
      interview_type: form.type,
      status: form.status || null,
      assignment_due_date: form.assignmentDueDate || null,
      available_start_date: form.availableStartDate || null,
      resume_notes: form.resumeNotes || null,
    }, existingId)
    rowSaved.value[candidateId] = true
    setTimeout(() => { delete rowSaved.value[candidateId] }, 1500)
  } catch (err) {
    console.error('Save failed:', err)
  } finally {
    delete rowSaving.value[candidateId]
  }
}

// ── Status dropdown ──
function toggleStatusDropdown(candidateId) {
  activeStatusDropdown.value = activeStatusDropdown.value === candidateId ? null : candidateId
  newStatusLabel.value = ''
}

function closeStatusDropdown() {
  activeStatusDropdown.value = null
}

function selectStatus(candidateId, label) {
  if (rowForms.value[candidateId]) rowForms.value[candidateId].status = label
  activeStatusDropdown.value = null
  saveRow(candidateId)
}

async function addStatusInline(candidateId) {
  const label = newStatusLabel.value.trim()
  if (!label) return
  await store.addStatus(label, 'blue')
  if (rowForms.value[candidateId]) rowForms.value[candidateId].status = label
  newStatusLabel.value = ''
  activeStatusDropdown.value = null
  saveRow(candidateId)
}

// Close dropdown when clicking anywhere outside
onMounted(() => {
  store.load()
  document.addEventListener('click', closeStatusDropdown)
})
onUnmounted(() => {
  document.removeEventListener('click', closeStatusDropdown)
})

// ── Data loading ──
async function loadCandidates() {
  const ids = bookmarks.allIds
  if (ids.length === 0) { candidates.value = []; return }
  loading.value = true
  try {
    candidates.value = await exportCandidates(ids)
  } catch (err) {
    console.error('Failed to load bookmarked candidates:', err)
  } finally {
    loading.value = false
  }
}

async function downloadCsv() {
  const ids = bookmarks.allIds
  if (ids.length === 0) return
  exporting.value = true
  try {
    await exportCandidatesCsv(ids)
  } catch (err) {
    console.error('CSV export failed:', err)
  } finally {
    exporting.value = false
  }
}

async function batchGenQuestions() {
  batchQRunning.value = true
  batchQStatus.value = ''
  try {
    const res = await batchInterviewQuestions()
    batchQStatus.value = res.count === 0 ? '沒有感興趣的候選人' : `已排入 ${res.count} 位，背景執行中…`
    setTimeout(() => { batchQStatus.value = '' }, 4000)
  } catch (err) {
    batchQStatus.value = '生成失敗'
    console.error(err)
  } finally {
    batchQRunning.value = false
  }
}

function removeBookmark(id) {
  bookmarks.toggle(id)
  candidates.value = candidates.value.filter((c) => c.id !== id)
  delete rowForms.value[id]
}

async function deleteRow(id, name) {
  if (!confirm(`Delete "${name}" permanently? This cannot be undone.`)) return
  try {
    await deleteCandidate(id)
    // Also remove from bookmark store if present
    if (bookmarks.has(id)) bookmarks.toggle(id)
    candidates.value = candidates.value.filter((c) => c.id !== id)
    delete rowForms.value[id]
  } catch (err) {
    console.error('Delete failed:', err)
  }
}

watch(() => bookmarks.count, loadCandidates, { immediate: true })
</script>

<style scoped>
input[type="time"]::-webkit-calendar-picker-indicator {
  cursor: pointer;
  opacity: 0.5;
}
</style>
