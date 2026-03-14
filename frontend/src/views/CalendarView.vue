<template>
  <div class="flex h-full overflow-hidden bg-white">

    <!-- ── Calendar Column ── -->
    <div class="flex flex-col flex-1 overflow-hidden border-r border-gray-200 min-w-0">

      <!-- Month Header -->
      <div class="flex items-center justify-between px-5 py-3 border-b border-gray-100 shrink-0">
        <div class="flex items-center gap-2">
          <button @click="prevMonth" class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
            </svg>
          </button>
          <h2 class="text-base font-semibold text-gray-900 w-40 text-center">{{ monthLabel }}</h2>
          <button @click="nextMonth" class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition">
            <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
              <path stroke-linecap="round" stroke-linejoin="round" d="M9 5l7 7-7 7" />
            </svg>
          </button>
          <button @click="goToday" class="text-xs px-2.5 py-1 rounded-md border border-gray-200 text-gray-500 hover:bg-gray-50 transition ml-1">Today</button>
        </div>
        <button
          @click="openAddModal(selectedDate)"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Schedule Interview
        </button>
      </div>

      <!-- Weekday Headers -->
      <div class="grid grid-cols-7 border-b border-gray-100 bg-gray-50 shrink-0">
        <div v-for="d in ['Sun','Mon','Tue','Wed','Thu','Fri','Sat']" :key="d"
          class="py-2 text-center text-xs font-semibold text-gray-400 uppercase tracking-wide">{{ d }}</div>
      </div>

      <!-- Day Grid -->
      <div class="grid grid-cols-7 flex-1 overflow-y-auto" style="grid-auto-rows: minmax(100px, 1fr)">
        <div
          v-for="cell in calendarDays" :key="cell.key"
          @click="selectDay(cell.date)"
          :class="[
            'border-b border-r border-gray-100 p-1.5 cursor-pointer transition-colors overflow-hidden',
            !cell.currentMonth ? 'bg-gray-50/60' : 'hover:bg-blue-50/20',
            isSameDay(cell.date, selectedDate) ? '!bg-blue-50 ring-1 ring-inset ring-blue-200' : '',
          ]"
        >
          <div class="flex items-center mb-1">
            <span :class="['w-6 h-6 flex items-center justify-center text-xs font-semibold rounded-full',
              isToday(cell.date) ? 'bg-blue-600 text-white' : !cell.currentMonth ? 'text-gray-300' : 'text-gray-700']">
              {{ cell.date.getDate() }}
            </span>
          </div>
          <div class="space-y-0.5">
            <div v-for="iv in cell.interviews.slice(0, 3)" :key="iv.id"
              :class="['flex items-center gap-1 text-xs px-1.5 py-0.5 rounded font-medium truncate leading-4',
                iv.status ? statusChipClass(iv.status) : typeChipClass(iv.interview_type)]">
              <span class="shrink-0">{{ formatTime(iv.interview_time) }}</span>
              <span class="truncate">{{ iv.candidate_name || '—' }}</span>
            </div>
            <div v-if="cell.interviews.length > 3" class="text-xs text-gray-400 pl-1.5">+{{ cell.interviews.length - 3 }} more</div>
          </div>
        </div>
      </div>
    </div>

    <!-- ── Day Panel ── -->
    <div class="w-80 flex flex-col overflow-hidden bg-white shrink-0">
      <div class="px-4 py-3 border-b border-gray-100 shrink-0">
        <div class="text-sm font-semibold text-gray-900">{{ selectedDayLabel }}</div>
        <div class="text-xs text-gray-400 mt-0.5">
          {{ selectedDayInterviews.length > 0 ? `${selectedDayInterviews.length} interview${selectedDayInterviews.length !== 1 ? 's' : ''}` : 'No interviews' }}
        </div>
      </div>
      <div class="flex-1 overflow-y-auto p-3 space-y-2">
        <div v-for="iv in selectedDayInterviews" :key="iv.id"
          class="bg-white border border-gray-200 rounded-xl p-3 group hover:shadow-sm transition-shadow">
          <!-- Time + badges -->
          <div class="flex items-center gap-2 flex-wrap mb-2">
            <span class="text-sm font-semibold text-gray-900">{{ formatTime(iv.interview_time) || 'TBD' }}</span>
            <span v-if="iv.status" :class="['text-xs font-semibold rounded-full px-2 py-0.5', statusBadgeClass(iv.status)]">{{ iv.status }}</span>
            <span :class="['text-xs font-semibold rounded-full px-2 py-0.5', typeChipClass(iv.interview_type)]">{{ typeLabel(iv.interview_type) }}</span>
          </div>

          <!-- Candidate -->
          <router-link v-if="iv.candidate_id" :to="{ name: 'detail', params: { id: iv.candidate_id } }"
            class="flex items-center gap-2 mb-2 group/link">
            <div class="w-7 h-7 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center shrink-0 overflow-hidden">
              <img v-if="iv.photo_url" :src="iv.photo_url" class="w-full h-full object-cover" />
              <span v-else>{{ (iv.candidate_name || '?').charAt(0) }}</span>
            </div>
            <span class="text-sm font-medium text-blue-600 group-hover/link:underline truncate">{{ iv.candidate_name }}</span>
          </router-link>
          <div v-else class="text-sm text-gray-400 mb-2 italic">No candidate linked</div>

          <!-- Extra fields grid -->
          <div class="space-y-1 mb-2">
            <div v-if="iv.location" class="flex items-center gap-1.5 text-xs text-gray-500">
              <svg class="w-3.5 h-3.5 shrink-0 text-gray-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M17.657 16.657L13.414 20.9a1.998 1.998 0 01-2.827 0l-4.244-4.243a8 8 0 1111.314 0z" /><path stroke-linecap="round" stroke-linejoin="round" d="M15 11a3 3 0 11-6 0 3 3 0 016 0z" />
              </svg>
              <span class="truncate">{{ iv.location }}</span>
            </div>
            <div v-if="iv.assignment_due_date" class="flex items-center gap-1.5 text-xs text-gray-500">
              <svg class="w-3.5 h-3.5 shrink-0 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <span>作業繳交：{{ iv.assignment_due_date }}</span>
            </div>
            <div v-if="iv.available_start_date" class="flex items-center gap-1.5 text-xs text-gray-500">
              <svg class="w-3.5 h-3.5 shrink-0 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
              </svg>
              <span>可到職：{{ iv.available_start_date }}</span>
            </div>
          </div>

          <!-- Notes -->
          <div v-if="iv.notes" class="text-xs text-gray-500 bg-gray-50 rounded-lg px-2.5 py-1.5 mb-1">{{ iv.notes }}</div>
          <div v-if="iv.resume_notes" class="text-xs text-gray-500 bg-amber-50 border border-amber-100 rounded-lg px-2.5 py-1.5 mb-1">
            <span class="font-semibold text-amber-600 mr-1">簡歷備注：</span>{{ iv.resume_notes }}
          </div>

          <!-- Actions -->
          <div class="flex items-center gap-2 pt-2 opacity-0 group-hover:opacity-100 transition-opacity border-t border-gray-100 mt-2">
            <button @click="openEditModal(iv)" class="text-xs font-medium text-gray-500 hover:text-blue-600 transition">Edit</button>
            <span class="text-gray-200">|</span>
            <button @click="doDelete(iv.id)" class="text-xs font-medium text-gray-500 hover:text-red-500 transition">Delete</button>
          </div>
        </div>

        <div v-if="selectedDayInterviews.length === 0" class="text-center py-8">
          <svg class="w-10 h-10 mx-auto text-gray-200 mb-2" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8 7V3m8 4V3m-9 8h10M5 21h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
          </svg>
          <p class="text-xs text-gray-400">No interviews scheduled</p>
        </div>

        <button @click="openAddModal(selectedDate)"
          class="w-full py-2.5 rounded-xl border border-dashed border-gray-200 text-xs font-medium text-gray-400 hover:border-blue-300 hover:text-blue-500 transition">
          + Add Interview
        </button>
      </div>
    </div>

    <!-- ── Modal ── -->
    <div v-if="showModal" class="fixed inset-0 z-50 flex items-center justify-center">
      <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="closeModal" />
      <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 max-h-[92vh] flex flex-col">

        <!-- Modal Header -->
        <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100 shrink-0">
          <h2 class="text-base font-semibold text-gray-900">{{ editingId ? 'Edit Interview' : 'Schedule Interview' }}</h2>
          <button @click="closeModal" class="p-1 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition">
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Modal Body -->
        <div class="overflow-y-auto flex-1 px-6 py-4 space-y-4">

          <!-- Date + Time -->
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Date *</label>
              <input type="date" v-model="form.date"
                class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
            <div>
              <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Time</label>
              <input type="time" v-model="form.time"
                class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
            </div>
          </div>

          <!-- Candidate -->
          <div>
            <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Candidate</label>
            <div class="relative">
              <div v-if="form.candidateId"
                class="flex items-center gap-2 px-3 py-2 border border-blue-300 bg-blue-50 rounded-lg text-sm">
                <div class="w-5 h-5 rounded-full bg-blue-200 text-blue-800 text-xs font-bold flex items-center justify-center shrink-0">
                  {{ selectedCandidateName.charAt(0) }}
                </div>
                <span class="text-blue-800 font-medium flex-1 truncate">{{ selectedCandidateName }}</span>
                <button @click="clearCandidate" class="text-blue-400 hover:text-blue-700 transition shrink-0">
                  <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                    <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                  </svg>
                </button>
              </div>
              <input v-else type="text" v-model="candidateSearch" @focus="showCandidateDropdown = true" @blur="hideCandidateDropdown"
                placeholder="Search by name or 104 code…"
                class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
              <div v-if="showCandidateDropdown && !form.candidateId && (filteredInterested.length || filteredOthers.length)"
                class="absolute z-20 top-full left-0 right-0 bg-white border border-gray-200 rounded-xl shadow-lg mt-1 max-h-56 overflow-y-auto">
                <!-- 感興趣 section -->
                <template v-if="filteredInterested.length">
                  <div class="px-3 py-1.5 flex items-center gap-1.5 text-xs font-semibold text-amber-600 uppercase tracking-wide bg-amber-50 border-b border-amber-100">
                    <svg class="w-3 h-3" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                    </svg>
                    感興趣
                  </div>
                  <button v-for="c in filteredInterested" :key="'int-' + c.id" @mousedown.prevent="pickCandidate(c)"
                    class="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-amber-50 text-left transition">
                    <div class="w-7 h-7 rounded-full bg-amber-100 text-amber-700 text-xs font-bold flex items-center justify-center shrink-0">
                      {{ c.name?.charAt(0) || '?' }}
                    </div>
                    <div class="min-w-0">
                      <div class="text-sm font-medium text-gray-900 truncate">{{ c.name }}</div>
                      <div v-if="c.code_104" class="text-xs text-gray-400 font-mono">{{ c.code_104 }}</div>
                    </div>
                  </button>
                </template>
                <!-- 其他候選人 section -->
                <template v-if="filteredOthers.length">
                  <div class="px-3 py-1.5 text-xs font-semibold text-gray-400 uppercase tracking-wide bg-gray-50 border-t border-gray-100">全部候選人</div>
                  <button v-for="c in filteredOthers" :key="'oth-' + c.id" @mousedown.prevent="pickCandidate(c)"
                    class="w-full flex items-center gap-2.5 px-3 py-2 hover:bg-blue-50 text-left transition">
                    <div class="w-7 h-7 rounded-full bg-blue-100 text-blue-700 text-xs font-bold flex items-center justify-center shrink-0">
                      {{ c.name?.charAt(0) || '?' }}
                    </div>
                    <div class="min-w-0">
                      <div class="text-sm font-medium text-gray-900 truncate">{{ c.name }}</div>
                      <div v-if="c.code_104" class="text-xs text-gray-400 font-mono">{{ c.code_104 }}</div>
                    </div>
                  </button>
                </template>
              </div>
            </div>
          </div>

          <!-- Interview Type -->
          <div>
            <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">Type</label>
            <div class="flex gap-2">
              <button v-for="t in interviewTypes" :key="t.value" @click="form.type = t.value"
                :class="['flex-1 py-2 rounded-lg text-xs font-semibold border transition',
                  form.type === t.value ? t.active : 'border-gray-200 text-gray-500 hover:border-gray-300 bg-white']">
                {{ t.label }}
              </button>
            </div>
          </div>

          <!-- 面試進度 (Status Dropdown) -->
          <div>
            <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1.5">面試進度</label>
            <div class="relative">
              <!-- Trigger -->
              <button @click="showStatusDropdown = !showStatusDropdown" type="button"
                class="w-full flex items-center justify-between gap-2 px-3 py-2 border border-gray-200 rounded-lg text-sm hover:border-gray-300 transition bg-white">
                <span v-if="form.status" class="flex items-center gap-2">
                  <span :class="['w-2 h-2 rounded-full shrink-0', statusDotClass(form.status)]"></span>
                  <span class="text-gray-800">{{ form.status }}</span>
                </span>
                <span v-else class="text-gray-400">Select progress…</span>
                <svg class="w-4 h-4 text-gray-400 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                  <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                </svg>
              </button>

              <!-- Dropdown Panel -->
              <div v-if="showStatusDropdown"
                class="absolute z-20 top-full left-0 right-0 bg-white border border-gray-200 rounded-xl shadow-lg mt-1 overflow-hidden">
                <!-- Clear option -->
                <button v-if="form.status" @mousedown.prevent="form.status = null; showStatusDropdown = false"
                  class="w-full flex items-center gap-2 px-3 py-2 hover:bg-gray-50 text-left text-xs text-gray-400 italic border-b border-gray-100">
                  Clear selection
                </button>
                <!-- Status Options -->
                <div v-for="s in statuses" :key="s.id" class="flex items-center justify-between px-3 py-2 hover:bg-gray-50 group/status">
                  <button @mousedown.prevent="pickStatus(s.label)" class="flex items-center gap-2 flex-1 text-left">
                    <span :class="['w-2 h-2 rounded-full shrink-0', COLOR_DOTS[s.color] || 'bg-gray-400']"></span>
                    <span class="text-sm text-gray-800">{{ s.label }}</span>
                  </button>
                  <button @mousedown.prevent="removeStatus(s.id)"
                    class="text-gray-200 hover:text-red-400 transition opacity-0 group-hover/status:opacity-100 shrink-0 ml-2">
                    <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>

                <!-- Add New Status -->
                <div class="border-t border-gray-100 px-3 py-2.5 bg-gray-50">
                  <div class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">Add custom option</div>
                  <div class="flex gap-2 items-center">
                    <input v-model="newStatusLabel" @keydown.enter.prevent="addStatus"
                      placeholder="Status name…"
                      class="flex-1 text-xs border border-gray-200 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white" />
                    <!-- Color Picker -->
                    <div class="flex gap-1 shrink-0">
                      <button v-for="c in STATUS_COLOR_OPTIONS" :key="c.value" @mousedown.prevent="newStatusColor = c.value"
                        :class="['w-5 h-5 rounded-full transition border-2',
                          COLOR_DOTS[c.value] || 'bg-gray-400',
                          newStatusColor === c.value ? 'border-gray-600 scale-110' : 'border-transparent']">
                      </button>
                    </div>
                    <button @mousedown.prevent="addStatus" :disabled="!newStatusLabel.trim()"
                      class="text-xs px-2.5 py-1.5 bg-gray-800 text-white rounded-lg font-semibold disabled:opacity-40 hover:bg-gray-700 transition shrink-0">
                      Add
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>

          <!-- Location -->
          <div>
            <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">Location</label>
            <input type="text" v-model="form.location" placeholder="Meeting Room A, Zoom link, …"
              class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <!-- 作業繳交日期 -->
          <div>
            <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
              作業繳交日期
              <span class="ml-1 text-gray-300 normal-case font-normal tracking-normal">Assignment due date</span>
            </label>
            <input type="date" v-model="form.assignmentDueDate"
              class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <!-- 可到職日 -->
          <div>
            <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
              可到職日
              <span class="ml-1 text-gray-300 normal-case font-normal tracking-normal">Available start date</span>
            </label>
            <input type="date" v-model="form.availableStartDate"
              class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500" />
          </div>

          <!-- 面試備注 -->
          <div>
            <label class="block text-xs font-semibold text-gray-500 uppercase tracking-wide mb-1">
              面試備注
              <span class="ml-1 text-gray-300 normal-case font-normal tracking-normal">Interview notes</span>
            </label>
            <textarea v-model="form.notes" rows="2" placeholder="Topics to cover, agenda…"
              class="w-full text-sm border border-gray-200 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-blue-500 resize-none" />
          </div>

          <!-- 簡歷備注 -->
          <div>
            <label class="block text-xs font-semibold text-amber-600 uppercase tracking-wide mb-1">
              簡歷備注
              <span class="ml-1 text-gray-300 normal-case font-normal tracking-normal">Resume notes</span>
            </label>
            <textarea v-model="form.resumeNotes" rows="2" placeholder="Observations about the resume, red flags, highlights…"
              class="w-full text-sm border border-amber-200 bg-amber-50/50 rounded-lg px-3 py-2 focus:outline-none focus:ring-2 focus:ring-amber-400 resize-none placeholder:text-amber-300" />
          </div>

        </div>

        <!-- Modal Footer -->
        <div class="flex justify-end gap-2 px-6 py-4 border-t border-gray-100 shrink-0">
          <button @click="closeModal" class="px-4 py-2 text-sm font-medium text-gray-600 rounded-lg hover:bg-gray-100 transition">Cancel</button>
          <button @click="saveInterview" :disabled="!form.date || saving"
            class="px-4 py-2 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition">
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
  gray:    'bg-gray-400',
}
const COLOR_BADGES = {
  blue:    'bg-blue-100 text-blue-700',
  purple:  'bg-purple-100 text-purple-700',
  indigo:  'bg-indigo-100 text-indigo-700',
  green:   'bg-green-100 text-green-700',
  emerald: 'bg-emerald-100 text-emerald-700',
  teal:    'bg-teal-100 text-teal-700',
  yellow:  'bg-yellow-100 text-yellow-700',
  orange:  'bg-orange-100 text-orange-700',
  red:     'bg-red-100 text-red-700',
  pink:    'bg-pink-100 text-pink-700',
  gray:    'bg-gray-100 text-gray-600',
}
const STATUS_COLOR_OPTIONS = [
  { value: 'blue' }, { value: 'purple' }, { value: 'indigo' },
  { value: 'emerald' }, { value: 'green' }, { value: 'teal' },
  { value: 'orange' }, { value: 'yellow' }, { value: 'red' },
]

// ── Shared stores ──
const store = useInterviewStore()
const { interviews, statuses } = storeToRefs(store)
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

const interviewTypes = [
  { value: 'phone',  label: 'Phone',  active: 'border-blue-400 bg-blue-50 text-blue-700' },
  { value: 'video',  label: 'Video',  active: 'border-purple-400 bg-purple-50 text-purple-700' },
  { value: 'onsite', label: 'Onsite', active: 'border-emerald-400 bg-emerald-50 text-emerald-700' },
]

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
  return type === 'phone' ? 'bg-blue-100 text-blue-700'
    : type === 'video' ? 'bg-purple-100 text-purple-700'
    : 'bg-emerald-100 text-emerald-700'
}
function typeLabel(type) {
  return type === 'phone' ? 'Phone' : type === 'video' ? 'Video' : 'Onsite'
}

function statusColorFor(label) {
  const s = statuses.value.find((x) => x.label === label)
  return s?.color || 'gray'
}
function statusDotClass(label) { return COLOR_DOTS[statusColorFor(label)] || 'bg-gray-400' }
function statusChipClass(label) { return COLOR_BADGES[statusColorFor(label)] || 'bg-gray-100 text-gray-600' }
function statusBadgeClass(label) { return COLOR_BADGES[statusColorFor(label)] || 'bg-gray-100 text-gray-600' }

// ── Calendar ──
const monthLabel = computed(() =>
  new Date(currentYear.value, currentMonth.value, 1)
    .toLocaleDateString('en-US', { year: 'numeric', month: 'long' })
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
  selectedDate.value.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric', year: 'numeric' })
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
