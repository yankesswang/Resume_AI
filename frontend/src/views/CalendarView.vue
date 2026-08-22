<template>
  <div class="flex h-full overflow-hidden bg-surface">

    <!-- ── Calendar Column ── -->
    <div class="flex flex-col flex-1 overflow-hidden border-r border-line min-w-0">

      <!-- Month Header -->
      <div class="flex items-center justify-between px-5 py-3 border-b border-line shrink-0">
        <div class="flex items-center gap-2">
          <button @click="prevMonth" class="p-1.5 rounded-control text-ink-faint hover:text-ink hover:bg-surface-2 transition">
            <ChevronLeft class="h-4 w-4" :stroke-width="2.5" />
          </button>
          <h2 class="text-base font-semibold text-ink w-40 text-center">{{ monthLabel }}</h2>
          <button @click="nextMonth" class="p-1.5 rounded-control text-ink-faint hover:text-ink hover:bg-surface-2 transition">
            <ChevronRight class="h-4 w-4" :stroke-width="2.5" />
          </button>
          <button @click="goToday" class="text-micro px-2.5 py-1 rounded-md border border-line text-ink-muted hover:bg-surface-2 transition ml-1">今天</button>
        </div>
        <button
          @click="openAddModal(selectedDate)"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-micro font-semibold bg-brand text-white rounded-control hover:bg-brand-hover transition"
        >
          <Plus class="h-3.5 w-3.5" :stroke-width="2.5" />
          安排面試
        </button>
      </div>

      <!-- Weekday Headers -->
      <div class="grid grid-cols-7 border-b border-line bg-surface-2 shrink-0">
        <div v-for="d in ['日','一','二','三','四','五','六']" :key="d"
          class="py-2 text-center text-micro font-semibold text-ink-faint">{{ d }}</div>
      </div>

      <!-- Day Grid -->
      <div class="grid grid-cols-7 flex-1 overflow-y-auto" style="grid-auto-rows: minmax(100px, 1fr)">
        <div
          v-for="cell in calendarDays" :key="cell.key"
          @click="selectDay(cell.date)"
          :class="[
            'border-b border-r border-line p-1.5 cursor-pointer transition-colors overflow-hidden',
            !cell.currentMonth ? 'bg-surface-2/60' : 'hover:bg-brand-soft/20',
            isSameDay(cell.date, selectedDate) ? '!bg-brand-soft ring-1 ring-inset ring-brand' : '',
          ]"
        >
          <div class="flex items-center mb-1">
            <span :class="['h-6 w-6 flex items-center justify-center text-micro font-semibold rounded-full',
              isToday(cell.date) ? 'bg-brand text-white' : !cell.currentMonth ? 'text-ink-faint' : 'text-ink']">
              {{ cell.date.getDate() }}
            </span>
          </div>
          <div class="space-y-0.5">
            <div v-for="iv in cell.interviews.slice(0, 3)" :key="iv.id"
              :class="['flex items-center gap-1 text-micro px-1.5 py-0.5 rounded font-medium truncate leading-4',
                iv.status ? statusChipClass(iv.status) : typeChipClass(iv.interview_type)]">
              <span class="shrink-0">{{ formatTime(iv.interview_time) }}</span>
              <span class="truncate">{{ iv.candidate_name || '—' }}</span>
            </div>
            <div v-if="cell.interviews.length > 3" class="text-micro text-ink-faint pl-1.5">+{{ cell.interviews.length - 3 }} more</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Day Panel ── -->
    <div class="w-80 flex flex-col overflow-hidden bg-surface shrink-0">
      <div class="px-4 py-3 border-b border-line shrink-0">
        <div class="text-small font-semibold text-ink">{{ selectedDayLabel }}</div>
        <div class="text-micro text-ink-faint mt-0.5">
          {{ selectedDayInterviews.length > 0 ? `${selectedDayInterviews.length} 場面試` : '尚無面試' }}
        </div>
      </div>
      <div class="flex-1 overflow-y-auto p-3 space-y-2">
        <div v-for="iv in selectedDayInterviews" :key="iv.id"
          class="bg-surface border border-line rounded-card p-3 group hover:shadow-sm transition-shadow">
          <!-- Time + badges -->
          <div class="flex items-center gap-2 flex-wrap mb-2">
            <span class="text-small font-semibold text-ink">{{ formatTime(iv.interview_time) || 'TBD' }}</span>
            <span v-if="iv.status" :class="['text-micro font-semibold rounded-full px-2 py-0.5', statusBadgeClass(iv.status)]">{{ iv.status }}</span>
            <span :class="['text-micro font-semibold rounded-full px-2 py-0.5', typeChipClass(iv.interview_type)]">{{ typeLabel(iv.interview_type) }}</span>
          </div>

          <!-- Candidate -->
          <router-link v-if="iv.candidate_id" :to="{ name: 'detail', params: { id: iv.candidate_id } }"
            class="flex items-center gap-2 mb-2 group/link">
            <div class="h-7 w-7 rounded-full bg-brand-soft text-brand-ink text-micro font-bold flex items-center justify-center shrink-0 overflow-hidden">
              <img v-if="iv.photo_url" :src="iv.photo_url" class="h-full w-full object-cover" />
              <span v-else>{{ (iv.candidate_name || '?').charAt(0) }}</span>
            </div>
            <span class="text-small font-medium text-brand-ink group-hover/link:underline truncate">{{ iv.candidate_name }}</span>
          </router-link>
          <div v-else class="text-small text-ink-faint mb-2 italic">未關聯人選</div>

          <!-- Extra fields grid -->
          <div class="space-y-1 mb-2">
            <div v-if="iv.location" class="flex items-center gap-1.5 text-micro text-ink-muted">
              <MapPin class="h-3.5 w-3.5 shrink-0 text-ink-faint" :stroke-width="2" />
              <span class="truncate">{{ iv.location }}</span>
            </div>
            <div v-if="iv.assignment_due_date" class="flex items-center gap-1.5 text-micro text-ink-muted">
              <ClipboardList class="h-3.5 w-3.5 shrink-0 text-warn-ink" :stroke-width="2" />
              <span>作業繳交：{{ iv.assignment_due_date }}</span>
            </div>
            <div v-if="iv.available_start_date" class="flex items-center gap-1.5 text-micro text-ink-muted">
              <Calendar class="h-3.5 w-3.5 shrink-0 text-good-ink" :stroke-width="2" />
              <span>可到職：{{ iv.available_start_date }}</span>
            </div>
          </div>

          <!-- Notes -->
          <div v-if="iv.notes" class="text-micro text-ink-muted bg-surface-2 rounded-control px-2.5 py-1.5 mb-1">{{ iv.notes }}</div>
          <div v-if="iv.resume_notes" class="text-micro text-ink-muted bg-warn-soft border border-warn-line rounded-control px-2.5 py-1.5 mb-1">
            <span class="font-semibold text-warn-ink mr-1">簡歷備注：</span>{{ iv.resume_notes }}
          </div>

          <!-- Actions -->
          <div class="flex items-center gap-2 pt-2 opacity-0 group-hover:opacity-100 transition-opacity border-t border-line mt-2">
            <button @click="openEditModal(iv)" class="text-micro font-medium text-ink-muted hover:text-brand-ink transition">編輯</button>
            <span class="text-ink-faint">|</span>
            <button @click="doDelete(iv.id)" class="text-micro font-medium text-ink-muted hover:text-bad-ink transition">刪除</button>
          </div>
        </div>

        <div v-if="selectedDayInterviews.length === 0" class="text-center py-8">
          <Calendar class="h-10 w-10 mx-auto text-ink-faint mb-2" :stroke-width="1.5" />
          <p class="text-micro text-ink-faint">尚未安排面試</p>
        </div>

        <button @click="openAddModal(selectedDate)"
          class="w-full py-2.5 rounded-card border border-dashed border-line text-micro font-medium text-ink-faint hover:border-brand-line hover:text-brand-ink transition">
          + 新增面試
        </button>
      </div>
    </div>

    <!-- ── Modal ── -->
    <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="closeModal" />
      <div class="relative bg-surface rounded-card shadow-2xl w-full max-w-lg mx-4 max-h-[92vh] flex flex-col">

        <!-- Modal Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-line shrink-0">
          <h2 class="text-base font-semibold text-ink">{{ editingId ? '編輯面試' : '安排面試' }}</h2>
          <button @click="closeModal" class="p-1 rounded-control text-ink-faint hover:text-ink hover:bg-surface-2 transition">
            <X class="h-5 w-5" :stroke-width="2" />
          </button>
        </div>

        <!-- Modal Body -->
        <div class="overflow-y-auto flex-1 px-6 py-4 space-y-4">

          <!-- Date + Time -->
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-micro font-semibold text-ink-muted mb-1">日期 *</label>
              <input type="date" v-model="form.date"
                class="field w-full" />
            </div>
            <div>
              <label class="block text-micro font-semibold text-ink-muted mb-1">時間</label>
              <input type="time" v-model="form.time"
                class="field w-full" />
            </div>
          </div>

          <!-- Candidate -->
          <div>
            <label class="block text-micro font-semibold text-ink-muted mb-1">候選人</label>
            <div class="relative">
              <div v-if="form.candidateId"
                class="flex items-center gap-2 px-3 py-2 border border-brand-line bg-brand-soft rounded-control text-small">
                <div class="h-5 w-5 rounded-full bg-blue-200 text-brand-ink text-micro font-bold flex items-center justify-center shrink-0">
                  {{ selectedCandidateName.charAt(0) }}
                </div>
                <span class="text-brand-ink font-medium flex-1 truncate">{{ selectedCandidateName }}</span>
                <button @click="clearCandidate" class="text-brand-ink hover:text-brand-ink transition shrink-0">
                  <X class="h-3.5 w-3.5" :stroke-width="2.5" />
                </button>
              </div>
              <input v-else type="text" v-model="candidateSearch" @focus="showCandidateDropdown = true" @blur="hideCandidateDropdown"
                placeholder="Search by name or 104 code…"
                class="field w-full" />
              <div v-if="showCandidateDropdown && !form.candidateId && (filteredInterested.length || filteredOthers.length)"
                class="absolute z-20 top-full left-0 right-0 bg-surface border border-line rounded-card shadow-lg mt-1 max-h-56 overflow-y-auto">
                <!-- 感興趣 section -->
                <template v-if="filteredInterested.length">
                  <div class="px-3 py-1.5 flex items-center gap-1.5 text-micro font-semibold text-warn-ink bg-warn-soft border-b border-warn-line">
                    <Star class="h-3 w-3" />
                    感興趣
                  </div>
                  <button v-for="c in filteredInterested" :key="'int-' + c.id" @mousedown.prevent="pickCandidate(c)"
                    class="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-warn-soft text-left transition">
                    <div class="h-7 w-7 rounded-full bg-warn-soft text-warn-ink text-micro font-bold flex items-center justify-center shrink-0">
                      {{ c.name?.charAt(0) || '?' }}
                    </div>
                    <div class="min-w-0">
                      <div class="text-small font-medium text-ink truncate">{{ c.name }}</div>
                      <div v-if="c.code_104" class="text-micro text-ink-faint font-mono">{{ c.code_104 }}</div>
                    </div>
                  </button>
                </template>
                <!-- 其他候選人 section -->
                <template v-if="filteredOthers.length">
                  <div class="px-3 py-1.5 text-micro font-semibold text-ink-faint bg-surface-2 border-t border-line">全部候選人</div>
                  <button v-for="c in filteredOthers" :key="'oth-' + c.id" @mousedown.prevent="pickCandidate(c)"
                    class="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-brand-soft text-left transition">
                    <div class="h-7 w-7 rounded-full bg-brand-soft text-brand-ink text-micro font-bold flex items-center justify-center shrink-0">
                      {{ c.name?.charAt(0) || '?' }}
                    </div>
                    <div class="min-w-0">
                      <div class="text-small font-medium text-ink truncate">{{ c.name }}</div>
                      <div v-if="c.code_104" class="text-micro text-ink-faint font-mono">{{ c.code_104 }}</div>
                    </div>
                  </button>
                </template>
              </div>
            </div>
          </div>

          <!-- Interview Type -->
          <div>
            <label class="block text-micro font-semibold text-ink-muted mb-1.5">類型</label>
            <div class="flex gap-2">
              <button v-for="t in interviewTypes" :key="t.value" @click="form.type = t.value"
                :class="['flex-1 py-2 rounded-control text-micro font-semibold border transition',
                  form.type === t.value ? typeActiveClass(t) : 'border-line text-ink-muted hover:border-line-strong bg-surface']">
                {{ t.label }}
              </button>
            </div>
          </div>

          <!-- 面試進度 (Status Dropdown) -->
          <div>
            <label class="block text-micro font-semibold text-ink-muted mb-1.5">面試進度</label>
            <div class="relative">
              <!-- Trigger -->
              <button @click="showStatusDropdown = !showStatusDropdown" type="button"
                class="w-full flex items-center justify-between gap-2 px-3 py-2 border border-line rounded-control text-small hover:border-line-strong transition bg-surface">
                <span v-if="form.status" class="flex items-center gap-2">
                  <span :class="['h-2 w-2 rounded-full shrink-0', statusDotClass(form.status)]"></span>
                  <span class="text-ink">{{ form.status }}</span>
                </span>
                <span v-else class="text-ink-faint">Select progress…</span>
                <ChevronDown class="h-4 w-4 text-ink-faint shrink-0" :stroke-width="2" />
              </button>

              <!-- Dropdown Panel -->
              <div v-if="showStatusDropdown"
                class="absolute z-20 top-full left-0 right-0 bg-surface border border-line rounded-card shadow-lg mt-1 overflow-hidden">
                <!-- Clear option -->
                <button v-if="form.status" @mousedown.prevent="form.status = null; showStatusDropdown = false"
                  class="w-full flex items-center gap-2 px-3 py-2 hover:bg-surface-2 text-left text-micro text-ink-faint italic border-b border-line">
                  Clear selection
                </button>
                <!-- Status Options -->
                <div v-for="s in statuses" :key="s.id" class="flex items-center justify-between px-3 py-2 hover:bg-surface-2 group/status">
                  <button @mousedown.prevent="pickStatus(s.label)" class="flex items-center gap-2 flex-1 text-left">
                    <span :class="['h-2 w-2 rounded-full shrink-0', COLOR_DOTS[s.color] || 'bg-ink-faint']"></span>
                    <span class="text-small text-ink">{{ s.label }}</span>
                  </button>
                  <button @mousedown.prevent="removeStatus(s.id)"
                    class="text-ink-faint hover:text-bad-ink transition opacity-0 group-hover/status:opacity-100 shrink-0 ml-2">
                    <X class="h-3.5 w-3.5" :stroke-width="2.5" />
                  </button>
                </div>

                <!-- Add New Status -->
                <div class="border-t border-line px-3 py-2.5 bg-surface-2">
                  <div class="text-micro font-semibold text-ink-faint mb-2">新增自訂選項</div>
                  <div class="flex gap-2 items-center">
                    <input v-model="newStatusLabel" @keydown.enter.prevent="addStatus"
                      placeholder="Status name…"
                      class="field flex-1 text-micro" />
                    <!-- Color Picker -->
                    <div class="flex gap-1 shrink-0">
                      <button v-for="c in STATUS_COLOR_OPTIONS" :key="c.value" @mousedown.prevent="newStatusColor = c.value"
                        :class="['h-5 w-5 rounded-full transition border-2',
                          COLOR_DOTS[c.value] || 'bg-ink-faint',
                          newStatusColor === c.value ? 'border-line-strong scale-110' : 'border-transparent']">
                      </button>
                    </div>
                    <button @mousedown.prevent="addStatus" :disabled="!newStatusLabel.trim()"
                      class="text-micro px-2.5 py-1.5 bg-brand text-white rounded-control font-semibold disabled:opacity-40 hover:bg-brand-hover transition shrink-0">
                      Add
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Location -->
          <div>
            <label class="block text-micro font-semibold text-ink-muted mb-1">地點</label>
            <input type="text" v-model="form.location" placeholder="Meeting Room A, Zoom link, …"
              class="field w-full" />
          </div>

          <!-- 作業繳交日期 -->
          <div>
            <label class="block text-micro font-semibold text-ink-muted mb-1">
              作業繳交日期
              <span class="ml-1 text-ink-faint font-normal">作業繳交日</span>
            </label>
            <input type="date" v-model="form.assignmentDueDate"
              class="field w-full" />
          </div>

          <!-- 可到職日 -->
          <div>
            <label class="block text-micro font-semibold text-ink-muted mb-1">
              可到職日
              <span class="ml-1 text-ink-faint font-normal">可到職日</span>
            </label>
            <input type="date" v-model="form.availableStartDate"
              class="field w-full" />
          </div>

          <!-- 面試備注 -->
          <div>
            <label class="block text-micro font-semibold text-ink-muted mb-1">
              面試備注
              <span class="ml-1 text-ink-faint font-normal">面試備註</span>
            </label>
            <textarea v-model="form.notes" rows="2" placeholder="Topics to cover, agenda…"
              class="field w-full resize-none" />
          </div>

          <!-- 簡歷備注 -->
          <div>
            <label class="block text-micro font-semibold text-warn-ink mb-1">
              簡歷備注
              <span class="ml-1 text-ink-faint font-normal">履歷備註</span>
            </label>
            <textarea v-model="form.resumeNotes" rows="2" placeholder="Observations about the resume, red flags, highlights…"
              class="field w-full resize-none" />
          </div>

        </div>

        <!-- Modal Footer -->
        <div class="flex justify-end gap-2 px-6 py-4 border-t border-line shrink-0">
          <button @click="closeModal" class="px-4 py-2 text-small font-medium text-ink-muted rounded-control hover:bg-surface-2 transition">取消</button>
          <button @click="saveInterview" :disabled="!form.date || saving"
            class="px-4 py-2 text-small font-semibold bg-brand text-white rounded-control hover:bg-brand-hover disabled:opacity-50 disabled:cursor-not-allowed transition">
            {{ saving ? 'Saving…' : editingId ? 'Update' : 'Schedule' }}
          </button>
        </div>
      </div>
    </div>

  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { storeToRefs } from 'pinia'
import { fetchCandidates } from '../api'
import { useInterviewStore } from '../stores/interviews'
import { useBookmarkStore } from '../stores/bookmarks'
import { Calendar, ChevronDown, ChevronLeft, ChevronRight, ClipboardList, MapPin, Plus, Star, X } from 'lucide-vue-next'

// ── Color maps (fully spelled out so Tailwind won't purge) ──
const COLOR_DOTS = {
  blue:    'bg-blue-500',
  purple:  'bg-purple-500',
  indigo:  'bg-indigo-500',
  green:   'bg-green-500',
  emerald: 'bg-emerald-500',
  teal:    'bg-teal-500',
  yellow:  'bg-yellow-400',
  orange:  'bg-orange-500',
  red:     'bg-red-500',
  pink:    'bg-pink-500',
  gray:    'bg-ink-faint',
}
const COLOR_BADGES = {
  blue:    'bg-brand-soft text-brand-ink',
  purple:  'bg-expert-soft text-expert-ink',
  indigo:  'bg-info-soft text-info-ink',
  green:   'bg-good-soft text-good-ink',
  emerald: 'bg-good-soft text-good-ink',
  teal:    'bg-info-soft text-info-ink',
  yellow:  'bg-yellow-100 text-yellow-700',
  orange:  'bg-orange-100 text-orange-700',
  red:     'bg-bad-soft text-bad-ink',
  pink:    'bg-pink-100 text-pink-700',
  gray:    'bg-surface-2 text-ink-muted',
}
const STATUS_COLOR_OPTIONS = [
  { value: 'blue' }, { value: 'purple' }, { value: 'indigo' },
  { value: 'emerald' }, { value: 'green' }, { value: 'teal' },
  { value: 'orange' }, { value: 'yellow' }, { value: 'red' },
]

// ── Shared stores ──
const store = useInterviewStore()
const { interviews, statuses, types: interviewTypes } = storeToRefs(store)
const bookmarks = useBookmarkStore()

// ── Local UI state ──
const allCandidates = ref([])

const todayDate = new Date()
const currentYear = ref(todayDate.getFullYear())
const currentMonth = ref(todayDate.getMonth())
const selectedDate = ref(new Date(todayDate))

const showModal = ref(false)
const editingId = ref(null)
const saving = ref(false)
const candidateSearch = ref('')
const showCandidateDropdown = ref(false)
const showStatusDropdown = ref(false)
const newStatusLabel = ref('')
const newStatusColor = ref('blue')

const form = ref({
  date: '',
  time: '',
  candidateId: null,
  type: 'onsite',
  status: null,
  location: '',
  notes: '',
  assignmentDueDate: '',
  availableStartDate: '',
  resumeNotes: '',
})

// Interview types come from the store (and so from the DB), like statuses.
// The selected-state classes are derived from the row's colour rather than
// stored as Tailwind strings: a class string in the database would be markup
// in a data column, and would silently break if a utility class were renamed.
const TYPE_ACTIVE_CLASSES = {
  blue:    'border-brand bg-brand-soft text-brand-ink',
  purple:  'border-expert-line bg-expert-soft text-expert-ink',
  indigo:  'border-info-line bg-info-soft text-info-ink',
  green:   'border-good-line bg-good-soft text-good-ink',
  emerald: 'border-good-line bg-good-soft text-good-ink',
  teal:    'border-info-line bg-info-soft text-info-ink',
  yellow:  'border-yellow-400 bg-yellow-100 text-yellow-700',
  orange:  'border-orange-400 bg-orange-100 text-orange-700',
  red:     'border-bad-line bg-bad-soft text-bad-ink',
  pink:    'border-pink-400 bg-pink-100 text-pink-700',
  gray:    'border-line-strong bg-surface-2 text-ink-muted',
}
function typeActiveClass(t) {
  return TYPE_ACTIVE_CLASSES[t?.color] || TYPE_ACTIVE_CLASSES.gray
}

// ── Helpers ──
function toDateStr(date) {
  const y = date.getFullYear()
  const m = String(date.getMonth() + 1).padStart(2, '0')
  const d = String(date.getDate()).padStart(2, '0')
  return `${y}-${m}-${d}`
}
function formatTime(t) { return t ? t.slice(0, 5) : '' }
function isToday(date) { return isSameDay(date, todayDate) }
function isSameDay(a, b) {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate()
}

function typeChipClass(type) {
  return type === 'phone' ? 'bg-brand-soft text-brand-ink'
    : type === 'video' ? 'bg-expert-soft text-expert-ink'
    : 'bg-good-soft text-good-ink'
}
function typeLabel(type) {
  return type === 'phone' ? 'Phone' : type === 'video' ? 'Video' : 'Onsite'
}

function statusColorFor(label) {
  const s = statuses.value.find((x) => x.label === label)
  return s?.color || 'gray'
}
function statusDotClass(label) { return COLOR_DOTS[statusColorFor(label)] || 'bg-ink-faint' }
function statusChipClass(label) { return COLOR_BADGES[statusColorFor(label)] || 'bg-surface-2 text-ink-muted' }
function statusBadgeClass(label) { return COLOR_BADGES[statusColorFor(label)] || 'bg-surface-2 text-ink-muted' }

// ── Calendar ──
const monthLabel = computed(() =>
  new Date(currentYear.value, currentMonth.value, 1)
    .toLocaleDateString('zh-TW', { year: 'numeric', month: 'long' })
)

const calendarDays = computed(() => {
  const year = currentYear.value
  const month = currentMonth.value
  const firstDow = new Date(year, month, 1).getDay()
  const daysInMonth = new Date(year, month + 1, 0).getDate()
  const cells = []

  for (let i = firstDow - 1; i >= 0; i--) {
    const date = new Date(year, month, -i)
    cells.push({ date, currentMonth: false, key: toDateStr(date) + 'p' })
  }
  for (let d = 1; d <= daysInMonth; d++) {
    const date = new Date(year, month, d)
    cells.push({ date, currentMonth: true, key: toDateStr(date) })
  }
  let next = 1
  while (cells.length < 42) {
    const date = new Date(year, month + 1, next++)
    cells.push({ date, currentMonth: false, key: toDateStr(date) + 'n' })
  }

  return cells.map((cell) => {
    const dateStr = toDateStr(cell.date)
    const dayInterviews = interviews.value
      .filter((iv) => iv.interview_date === dateStr)
      .sort((a, b) => (a.interview_time || '').localeCompare(b.interview_time || ''))
    return { ...cell, interviews: dayInterviews }
  })
})

const selectedDayLabel = computed(() =>
  selectedDate.value.toLocaleDateString('zh-TW', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
)
const selectedDayInterviews = computed(() => {
  const dateStr = toDateStr(selectedDate.value)
  return interviews.value
    .filter((iv) => iv.interview_date === dateStr)
    .sort((a, b) => (a.interview_time || '').localeCompare(b.interview_time || ''))
})

// 感興趣的候選人（優先顯示在搜尋下拉）
const filteredInterested = computed(() => {
  const q = candidateSearch.value.toLowerCase().trim()
  return allCandidates.value
    .filter((c) => bookmarks.has(c.id) &&
      (!q || c.name?.toLowerCase().includes(q) || c.code_104?.toLowerCase().includes(q)))
    .slice(0, 5)
})
// 其他候選人
const filteredOthers = computed(() => {
  const q = candidateSearch.value.toLowerCase().trim()
  return allCandidates.value
    .filter((c) => !bookmarks.has(c.id) &&
      (!q || c.name?.toLowerCase().includes(q) || c.code_104?.toLowerCase().includes(q)))
    .slice(0, 8)
})
const selectedCandidateName = computed(() =>
  allCandidates.value.find((c) => c.id === form.value.candidateId)?.name || ''
)

// ── Navigation ──
function prevMonth() {
  if (currentMonth.value === 0) { currentMonth.value = 11; currentYear.value-- }
  else currentMonth.value--
}
function nextMonth() {
  if (currentMonth.value === 11) { currentMonth.value = 0; currentYear.value++ }
  else currentMonth.value++
}
function goToday() {
  const t = new Date()
  currentYear.value = t.getFullYear()
  currentMonth.value = t.getMonth()
  selectedDate.value = new Date(t)
}
function selectDay(date) {
  selectedDate.value = new Date(date)
  showStatusDropdown.value = false
  if (date.getFullYear() !== currentYear.value || date.getMonth() !== currentMonth.value) {
    currentYear.value = date.getFullYear()
    currentMonth.value = date.getMonth()
  }
}

// ── Modal ──
function blankForm(date) {
  return {
    date: toDateStr(date || selectedDate.value),
    time: '10:00',
    candidateId: null,
    type: 'onsite',
    status: null,
    location: '',
    notes: '',
    assignmentDueDate: '',
    availableStartDate: '',
    resumeNotes: '',
  }
}
function openAddModal(date) {
  editingId.value = null
  form.value = blankForm(date)
  candidateSearch.value = ''
  showStatusDropdown.value = false
  showModal.value = true
}
function openEditModal(iv) {
  editingId.value = iv.id
  form.value = {
    date: iv.interview_date,
    time: iv.interview_time || '',
    candidateId: iv.candidate_id || null,
    type: iv.interview_type || 'onsite',
    status: iv.status || null,
    location: iv.location || '',
    notes: iv.notes || '',
    assignmentDueDate: iv.assignment_due_date || '',
    availableStartDate: iv.available_start_date || '',
    resumeNotes: iv.resume_notes || '',
  }
  candidateSearch.value = ''
  showStatusDropdown.value = false
  showModal.value = true
}
function closeModal() {
  showModal.value = false
  editingId.value = null
  showStatusDropdown.value = false
}

function pickCandidate(c) { form.value.candidateId = c.id; candidateSearch.value = ''; showCandidateDropdown.value = false }
function clearCandidate() { form.value.candidateId = null; candidateSearch.value = '' }
function hideCandidateDropdown() { setTimeout(() => { showCandidateDropdown.value = false }, 150) }

function pickStatus(label) { form.value.status = label; showStatusDropdown.value = false }

async function addStatus() {
  const label = newStatusLabel.value.trim()
  if (!label) return
  await store.addStatus(label, newStatusColor.value)
  form.value.status = label
  newStatusLabel.value = ''
  showStatusDropdown.value = false
}

async function removeStatus(id) {
  const removed = statuses.value.find((s) => s.id === id)
  await store.removeStatus(id)
  if (removed && form.value.status === removed.label) form.value.status = null
}

// ── CRUD ──
async function saveInterview() {
  if (!form.value.date) return
  saving.value = true
  try {
    const payload = {
      candidate_id: form.value.candidateId,
      interview_date: form.value.date,
      interview_time: form.value.time || null,
      interview_type: form.value.type,
      status: form.value.status || null,
      location: form.value.location || null,
      notes: form.value.notes || null,
      assignment_due_date: form.value.assignmentDueDate || null,
      available_start_date: form.value.availableStartDate || null,
      resume_notes: form.value.resumeNotes || null,
    }
    await store.saveInterview(payload, editingId.value)
    closeModal()
  } finally {
    saving.value = false
  }
}

async function doDelete(id) {
  if (!confirm('Delete this interview?')) return
  await store.removeInterview(id)
}

onMounted(async () => {
  await Promise.all([
    store.load(),
    bookmarks.load(),
    fetchCandidates().then((list) => { allCandidates.value = list }),
  ])
})
</script>
