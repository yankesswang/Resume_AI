<template>
  <div class="flex flex-col h-full overflow-hidden">

    <!-- Toolbar -->
    <div class="flex items-center gap-3 px-5 py-3 bg-white border-b border-gray-100 shrink-0">
      <button
        @click="router.push('/')"
        class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
      </button>
      <div class="flex items-center gap-2">
        <svg class="w-4 h-4 text-amber-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
        </svg>
        <h1 class="text-sm font-semibold text-gray-900">Interested Candidates</h1>
        <span class="text-xs bg-amber-100 text-amber-700 rounded-full px-2 py-0.5 font-semibold">{{ bookmarks.count }}</span>
      </div>
      <div class="ml-auto flex items-center gap-2">
        <span v-if="batchQStatus" class="text-xs text-emerald-600 font-medium">{{ batchQStatus }}</span>
        <!-- Add Candidate manually -->
        <button
          @click="showAddModal = true"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border border-blue-200 rounded-lg text-blue-700 hover:border-blue-400 hover:bg-blue-50 transition"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 4v16m8-8H4" />
          </svg>
          Add Candidate
        </button>
        <button
          :disabled="bookmarks.count === 0 || batchQRunning"
          @click="batchGenQuestions"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border border-emerald-200 rounded-lg text-emerald-700 hover:border-emerald-400 hover:bg-emerald-50 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <svg class="w-3.5 h-3.5" :class="{ 'animate-spin': batchQRunning }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          {{ batchQRunning ? '生成中…' : '生成面試問題' }}
        </button>
        <button
          :disabled="bookmarks.count === 0 || exporting"
          @click="downloadCsv"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border border-gray-200 rounded-lg text-gray-600 hover:border-gray-300 hover:text-gray-800 disabled:opacity-50 disabled:cursor-not-allowed transition"
        >
          <svg class="w-3.5 h-3.5" :class="{ 'animate-spin': exporting }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4" />
          </svg>
          {{ exporting ? 'Exporting…' : 'Export CSV' }}
        </button>
      </div>
    </div>

    <!-- Empty state -->
    <div v-if="bookmarks.count === 0" class="flex-1 flex flex-col items-center justify-center text-center px-6">
      <svg class="w-16 h-16 text-gray-200 mb-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1">
        <path stroke-linecap="round" stroke-linejoin="round" d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
      </svg>
      <h3 class="text-sm font-semibold text-gray-500 mb-1">No bookmarked candidates</h3>
      <p class="text-xs text-gray-400 mb-5">Star candidates from the list to save them here.</p>
      <button
        @click="router.push('/')"
        class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
      >
        <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
          <path stroke-linecap="round" stroke-linejoin="round" d="M15 19l-7-7 7-7" />
        </svg>
        Back to List
      </button>
    </div>

    <!-- Table -->
    <div v-else class="flex-1 overflow-auto p-5">
      <div class="bg-white border border-gray-200 rounded-xl overflow-hidden">
        <div class="overflow-x-auto">
          <table class="w-full text-sm">
            <thead>
              <tr class="border-b border-gray-200 bg-gray-50">
                <th class="w-10 px-3 py-2.5"></th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">Name</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">Education</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">School</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">Score</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">技能</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">面試進度</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">面試日期</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">作業繳交日期</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">可到職日</th>
                <th class="px-3 py-2.5 text-left text-xs font-semibold text-gray-500 uppercase tracking-wide whitespace-nowrap">簡歷備注</th>
              </tr>
            </thead>

            <tbody class="divide-y divide-gray-100" @click="closeStatusDropdown">
              <tr
                v-for="item in candidates"
                :key="item.id"
                class="hover:bg-amber-50/20 transition-colors group"
                :class="{ 'opacity-60': rowSaving[item.id] }"
              >
                <!-- Actions: unstar + delete -->
                <td class="px-3 py-2 text-center">
                  <div class="flex items-center justify-center gap-1">
                    <button
                      @click="removeBookmark(item.id)"
                      class="text-amber-400 hover:text-gray-400 transition opacity-50 group-hover:opacity-100"
                      title="Remove from interested"
                    >
                      <svg class="w-4 h-4" fill="currentColor" viewBox="0 0 24 24">
                        <path d="M11.48 3.499a.562.562 0 011.04 0l2.125 5.111a.563.563 0 00.475.345l5.518.442c.499.04.701.663.321.988l-4.204 3.602a.563.563 0 00-.182.557l1.285 5.385a.562.562 0 01-.84.61l-4.725-2.885a.563.563 0 00-.586 0L6.982 20.54a.562.562 0 01-.84-.61l1.285-5.386a.562.562 0 00-.182-.557l-4.204-3.602a.563.563 0 01.321-.988l5.518-.442a.563.563 0 00.475-.345L11.48 3.5z" />
                      </svg>
                    </button>
                    <button
                      @click="deleteRow(item.id, item.name)"
                      class="text-gray-300 hover:text-red-500 transition opacity-0 group-hover:opacity-100"
                      title="Delete candidate permanently"
                    >
                      <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                      </svg>
                    </button>
                  </div>
                </td>

                <!-- Name -->
                <td class="px-3 py-2 cursor-pointer" @click="router.push(`/candidate/${item.id}`)">
                  <div class="flex items-center gap-2">
                    <div class="w-7 h-7 rounded-full bg-gray-100 text-gray-600 text-xs font-bold flex items-center justify-center shrink-0 overflow-hidden">
                      <img v-if="item.photo_url" :src="item.photo_url" class="w-full h-full object-cover" />
                      <span v-else>{{ item.name?.charAt(0) || '?' }}</span>
                    </div>
                    <span class="font-semibold text-gray-900 whitespace-nowrap hover:text-blue-600 transition-colors">{{ item.name || '—' }}</span>
                    <!-- Per-row save indicator -->
                    <svg v-if="rowSaved[item.id]" class="w-3.5 h-3.5 text-emerald-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                    </svg>
                    <svg v-if="rowSaving[item.id]" class="w-3.5 h-3.5 text-gray-300 shrink-0 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                      <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                    </svg>
                  </div>
                </td>

                <!-- Education -->
                <td class="px-3 py-2 text-gray-500 text-xs whitespace-nowrap">{{ item.education_level || '—' }}</td>

                <!-- School -->
                <td class="px-3 py-2 text-gray-500 text-xs whitespace-nowrap">{{ item.school || '—' }}</td>

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
                      class="text-xs bg-indigo-50 text-indigo-700 border border-indigo-100 rounded-full px-2 py-0.5 whitespace-nowrap"
                    >{{ tag }}</span>
                    <span v-if="(item.skill_tags || []).length > 3" class="text-xs text-gray-400 px-1">+{{ item.skill_tags.length - 3 }}</span>
                  </div>
                </td>

                <!-- 面試進度 — inline dropdown -->
                <td class="px-2 py-2" @click.stop>
                  <div class="relative">
                    <button
                      @click.stop="toggleStatusDropdown(item.id)"
                      class="flex items-center gap-1.5 px-2.5 py-1.5 rounded-lg border transition text-xs w-full min-w-[120px] text-left"
                      :class="rowForms[item.id]?.status
                        ? 'border-gray-200 bg-white hover:border-gray-300'
                        : 'border-dashed border-gray-200 bg-gray-50 hover:border-gray-300 hover:bg-white'"
                    >
                      <template v-if="rowForms[item.id]?.status">
                        <span :class="['w-2 h-2 rounded-full shrink-0', statusDotClass(rowForms[item.id].status)]"></span>
                        <span class="font-semibold flex-1 truncate" :class="statusTextClass(rowForms[item.id].status)">
                          {{ rowForms[item.id].status }}
                        </span>
                      </template>
                      <span v-else class="text-gray-300 italic flex-1">選擇進度…</span>
                      <svg class="w-3 h-3 text-gray-300 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2.5">
                        <path stroke-linecap="round" stroke-linejoin="round" d="M19 9l-7 7-7-7" />
                      </svg>
                    </button>

                    <!-- Dropdown menu -->
                    <div
                      v-if="activeStatusDropdown === item.id"
                      class="absolute z-50 left-0 top-full mt-1 bg-white border border-gray-200 rounded-xl shadow-xl min-w-[180px] overflow-hidden"
                      @click.stop
                    >
                      <button
                        v-if="rowForms[item.id]?.status"
                        @click="selectStatus(item.id, null)"
                        class="w-full text-left px-3 py-2 text-xs text-gray-400 italic hover:bg-gray-50 border-b border-gray-100"
                      >清除</button>

                      <button
                        v-for="s in store.statuses"
                        :key="s.id"
                        @click="selectStatus(item.id, s.label)"
                        class="w-full flex items-center gap-2.5 px-3 py-2.5 hover:bg-gray-50 text-left"
                      >
                        <span :class="['w-2 h-2 rounded-full shrink-0', COLOR_DOTS[s.color] || 'bg-gray-400']"></span>
                        <span class="text-sm text-gray-800 flex-1">{{ s.label }}</span>
                        <svg v-if="rowForms[item.id]?.status === s.label" class="w-3.5 h-3.5 text-emerald-500 shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="3">
                          <path stroke-linecap="round" stroke-linejoin="round" d="M4.5 12.75l6 6 9-13.5" />
                        </svg>
                      </button>

                      <!-- Add custom status -->
                      <div class="border-t border-gray-100 px-3 py-2.5 bg-gray-50">
                        <p class="text-xs font-semibold text-gray-400 uppercase tracking-wide mb-2">新增選項</p>
                        <div class="flex gap-1.5">
                          <input
                            v-model="newStatusLabel"
                            @keydown.enter.prevent="addStatusInline(item.id)"
                            @click.stop
                            placeholder="狀態名稱…"
                            class="flex-1 text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-500 bg-white"
                          />
                          <button
                            @click="addStatusInline(item.id)"
                            :disabled="!newStatusLabel.trim()"
                            class="text-xs px-2.5 py-1.5 bg-gray-800 text-white rounded-lg disabled:opacity-40 hover:bg-gray-700 transition shrink-0"
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
                      class="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400 w-[132px] bg-white"
                    />
                    <input
                      type="time"
                      v-model="rowForms[item.id].time"
                      @change="saveRow(item.id)"
                      class="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400 w-[132px] bg-white"
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
                    class="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400 w-[132px] bg-white"
                  />
                </td>

                <!-- 可到職日 -->
                <td class="px-2 py-2" @click.stop>
                  <input
                    v-if="rowForms[item.id]"
                    type="date"
                    v-model="rowForms[item.id].availableStartDate"
                    @change="saveRow(item.id)"
                    class="text-xs border border-gray-200 rounded-lg px-2 py-1.5 focus:outline-none focus:ring-2 focus:ring-blue-400 w-[132px] bg-white"
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
                    class="text-xs border border-amber-200 bg-amber-50/40 rounded-lg px-2.5 py-1.5 focus:outline-none focus:ring-2 focus:ring-amber-400 placeholder:text-amber-200 w-full min-w-[140px]"
                  />
                </td>
              </tr>

              <tr v-if="loading">
                <td colspan="11" class="px-6 py-12 text-center text-gray-400 text-sm">Loading…</td>
              </tr>
            </tbody>
          </table>
        </div>

        <div class="px-4 py-2.5 border-t border-gray-100 text-xs text-gray-400 bg-gray-50">
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
        <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-lg mx-4 overflow-hidden">
          <!-- Modal header -->
          <div class="flex items-center justify-between px-6 py-4 border-b border-gray-100">
            <h2 class="text-sm font-semibold text-gray-900">Add Candidate Manually</h2>
            <button @click="closeAddModal" class="p-1.5 rounded-lg text-gray-400 hover:text-gray-700 hover:bg-gray-100 transition">
              <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>

          <!-- Modal form -->
          <form @submit.prevent="submitAddCandidate" class="px-6 py-4 space-y-3 max-h-[70vh] overflow-y-auto">
            <!-- Name -->
            <div>
              <label class="block text-xs font-semibold text-gray-600 mb-1">Name <span class="text-red-500">*</span></label>
              <input
                v-model="addForm.name"
                type="text"
                required
                placeholder="Candidate full name"
                class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition"
              />
            </div>

            <!-- Email + Phone -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1">Email</label>
                <input
                  v-model="addForm.email"
                  type="email"
                  placeholder="email@example.com"
                  class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition"
                />
              </div>
              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1">Phone</label>
                <input
                  v-model="addForm.mobile"
                  type="text"
                  placeholder="0912-345-678"
                  class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition"
                />
              </div>
            </div>

            <!-- Education + School -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1">Education Level</label>
                <select
                  v-model="addForm.education_level"
                  class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition bg-white"
                >
                  <option value="">— Select —</option>
                  <option value="高中">高中</option>
                  <option value="大專">大專</option>
                  <option value="大學">大學</option>
                  <option value="碩士">碩士</option>
                  <option value="博士">博士</option>
                </select>
              </div>
              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1">School</label>
                <input
                  v-model="addForm.school"
                  type="text"
                  placeholder="University / College"
                  class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition"
                />
              </div>
            </div>

            <!-- Years of experience + Expected salary -->
            <div class="grid grid-cols-2 gap-3">
              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1">Years of Experience</label>
                <input
                  v-model="addForm.years_of_experience"
                  type="text"
                  placeholder="e.g. 5年"
                  class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition"
                />
              </div>
              <div>
                <label class="block text-xs font-semibold text-gray-600 mb-1">Expected Salary</label>
                <input
                  v-model="addForm.desired_salary"
                  type="text"
                  placeholder="e.g. 80,000"
                  class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition"
                />
              </div>
            </div>

            <!-- Skills -->
            <div>
              <label class="block text-xs font-semibold text-gray-600 mb-1">Skills <span class="text-gray-400 font-normal">(comma-separated)</span></label>
              <input
                v-model="addForm.skillsInput"
                type="text"
                placeholder="Python, React, SQL, …"
                class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition"
              />
            </div>

            <!-- Notes -->
            <div>
              <label class="block text-xs font-semibold text-gray-600 mb-1">Notes</label>
              <textarea
                v-model="addForm.notes"
                rows="3"
                placeholder="Any additional notes about this candidate…"
                class="w-full px-3 py-2 text-sm border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-300 focus:border-blue-400 transition resize-none"
              ></textarea>
            </div>

            <!-- Error -->
            <p v-if="addError" class="text-xs text-red-500">{{ addError }}</p>
          </form>

          <!-- Modal footer -->
          <div class="flex items-center justify-end gap-2 px-6 py-4 border-t border-gray-100 bg-gray-50">
            <button
              type="button"
              @click="closeAddModal"
              class="px-4 py-2 text-xs font-semibold text-gray-600 hover:text-gray-800 transition"
            >
              Cancel
            </button>
            <button
              type="button"
              :disabled="!addForm.name.trim() || addSubmitting"
              @click="submitAddCandidate"
              class="inline-flex items-center gap-1.5 px-4 py-2 text-xs font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition"
            >
              <svg v-if="addSubmitting" class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
                <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
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

// ── Color maps (fully spelled-out so Tailwind won't purge) ──
const COLOR_DOTS = {
  blue: 'bg-blue-500', purple: 'bg-purple-500', indigo: 'bg-indigo-500',
  green: 'bg-green-500', emerald: 'bg-emerald-500', teal: 'bg-teal-500',
  yellow: 'bg-yellow-400', orange: 'bg-orange-500', red: 'bg-red-500',
  pink: 'bg-pink-500', gray: 'bg-gray-400',
}
const COLOR_TEXT = {
  blue: 'text-blue-700', purple: 'text-purple-700', indigo: 'text-indigo-700',
  green: 'text-green-700', emerald: 'text-emerald-700', teal: 'text-teal-700',
  yellow: 'text-yellow-700', orange: 'text-orange-700', red: 'text-red-700',
  pink: 'text-pink-700', gray: 'text-gray-600',
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
  return COLOR_DOTS[statusColorFor(label)] || 'bg-gray-400'
}
function statusTextClass(label) {
  return COLOR_TEXT[statusColorFor(label)] || 'text-gray-700'
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
