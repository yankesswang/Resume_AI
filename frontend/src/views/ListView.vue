<template>
  <div class="flex flex-col h-full overflow-hidden">
    <!-- Toolbar -->
    <div class="flex items-center justify-between px-5 py-3 bg-white border-b border-gray-100 shrink-0">
      <div class="flex items-center gap-2 text-sm text-gray-500 min-w-0">
        <span class="font-semibold text-gray-900 whitespace-nowrap">{{ props.title }}</span>
        <span class="text-gray-300">/</span>
        <template v-if="candidates.length">
          <span class="font-semibold text-gray-700">{{ tableRef?.filteredCount ?? candidates.length }}</span>
          <span v-if="tableRef?.filteredCount != null && tableRef.filteredCount !== candidates.length" class="text-gray-400">of {{ candidates.length }}</span>
          <span>candidates</span>
        </template>
      </div>
      <div v-if="!props.scope" class="flex items-center gap-2">
        <button
          @click="batchMatchAll"
          :disabled="batchRunning"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold border border-gray-200 rounded-lg text-gray-600 hover:border-gray-300 hover:text-gray-800 disabled:opacity-50 transition"
        >
          <svg class="w-3.5 h-3.5" :class="{ 'animate-spin': batchRunning }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {{ batchRunning ? 'Running…' : 'Batch Match' }}
        </button>
        <button
          @click="showUpload = true"
          class="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
        >
          <svg class="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" />
          </svg>
          Upload PDF
        </button>
      </div>
    </div>

    <!-- Main content -->
    <div class="flex-1 overflow-auto p-5">
      <!-- Backend connection error -->
      <div v-if="loadError" class="flex flex-col items-center justify-center py-20 text-center">
        <div class="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mb-4">
          <svg class="w-6 h-6 text-red-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M12 9v2m0 4h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" />
          </svg>
        </div>
        <h3 class="text-sm font-semibold text-gray-700 mb-1">Cannot reach backend</h3>
        <p class="text-xs text-gray-400 mb-1">Make sure the FastAPI server is running:</p>
        <code class="text-xs bg-gray-100 text-gray-600 rounded px-2 py-1 mb-5 font-mono">uv run python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000</code>
        <button
          @click="loadData"
          :disabled="loadingData"
          class="inline-flex items-center gap-1.5 px-4 py-2 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 transition"
        >
          <svg class="w-4 h-4" :class="{ 'animate-spin': loadingData }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
            <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          Retry
        </button>
      </div>

      <template v-else>
        <FilterPanel
          :education-levels="filterOptions.education_levels"
          :skill-tags="filterOptions.skill_tags"
          :experience-ranges="filterOptions.experience_ranges"
          :score-ranges="filterOptions.score_ranges"
          :import-batches="importBatches"
        />
        <CandidateTable ref="tableRef" :candidates="candidates" />
      </template>
    </div>

    <!-- Upload Modal -->
    <div
      v-if="showUpload"
      class="fixed inset-0 z-50 flex items-center justify-center"
    >
      <div class="absolute inset-0 bg-black/30 backdrop-blur-sm" @click="showUpload = false" />
      <div class="relative bg-white rounded-2xl shadow-2xl w-full max-w-md mx-4 p-6">
        <div class="flex items-center justify-between mb-5">
          <h2 class="text-base font-semibold text-gray-900">Upload Resume PDF</h2>
          <button @click="showUpload = false" class="text-gray-400 hover:text-gray-600 transition">
            <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        <!-- Drop zone -->
        <label
          class="block border-2 border-dashed border-gray-200 rounded-xl p-8 text-center cursor-pointer hover:border-blue-400 hover:bg-blue-50/50 transition-all group"
          :class="{ 'border-blue-400 bg-blue-50': uploadFile }"
        >
          <input type="file" accept=".pdf" class="hidden" @change="onFileChange" />
          <svg class="w-10 h-10 mx-auto text-gray-300 group-hover:text-blue-400 transition mb-3" :class="{ 'text-blue-500': uploadFile }" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="1.5">
            <path stroke-linecap="round" stroke-linejoin="round" d="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z" />
          </svg>
          <div v-if="uploadFile" class="text-sm font-medium text-blue-700">{{ uploadFile.name }}</div>
          <div v-else>
            <div class="text-sm font-medium text-gray-600">Choose PDF or drag & drop</div>
            <div class="text-xs text-gray-400 mt-1">PDF files only</div>
          </div>
        </label>

        <div v-if="uploadError" class="mt-3 text-xs text-red-600 text-center">{{ uploadError }}</div>

        <div class="flex justify-end gap-2 mt-5">
          <button @click="showUpload = false" class="px-4 py-2 text-sm font-medium text-gray-600 rounded-lg hover:bg-gray-100 transition">
            Cancel
          </button>
          <button
            :disabled="!uploadFile || uploading"
            @click="doUpload"
            class="px-4 py-2 text-sm font-semibold bg-blue-600 text-white rounded-lg hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed transition flex items-center gap-2"
          >
            <svg v-if="uploading" class="w-4 h-4 animate-spin" fill="none" viewBox="0 0 24 24" stroke="currentColor" stroke-width="2">
              <path stroke-linecap="round" stroke-linejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
            </svg>
            {{ uploading ? 'Uploading…' : 'Upload' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default { name: 'ListView' }
</script>

<script setup>
import { ref, onMounted, onActivated, nextTick } from 'vue'
import { onBeforeRouteLeave } from 'vue-router'
import { fetchCandidates, fetchFilters, fetchImportBatches, uploadPdf, batchMatch } from '../api'
import { useBookmarkStore } from '../stores/bookmarks'
import { useInvitationStore } from '../stores/invitations'
import { useFilterStore } from '../stores/filters'
import FilterPanel from '../components/FilterPanel.vue'
import CandidateTable from '../components/CandidateTable.vue'

const bookmarks = useBookmarkStore()
const invitations = useInvitationStore()
const filterStore = useFilterStore()

const props = defineProps({
  scope: { type: String, default: null },
  title: { type: String, default: 'Candidates' },
})

const tableRef = ref(null)
const candidates = ref([])
const importBatches = ref([])
const filterOptions = ref({ education_levels: [], skill_tags: [], experience_ranges: [], score_ranges: [] })
const showUpload = ref(false)
const uploadFile = ref(null)
const uploading = ref(false)
const uploadError = ref('')
const batchRunning = ref(false)
const loaded = ref(false)
const loadError = ref(false)
const loadingData = ref(false)

async function loadData() {
  loadError.value = false
  loadingData.value = true
  try {
    const [cands, filters, batches] = await Promise.all([
      fetchCandidates({ scope: props.scope }),
      fetchFilters({ scope: props.scope }),
      fetchImportBatches(),
    ])
    candidates.value = cands
    filterOptions.value = filters
    importBatches.value = batches
    // Guard: if "No Score" filter is saved but all candidates now have scores
    // (e.g. after running batch_score_all.py), auto-clear the stale filter so
    // the table isn't silently empty.
    const hasAnyScore = cands.some((c) => c.overall_score != null)
    if (hasAnyScore && filterStore.scoreRange === 'No Score') {
      filterStore.scoreRange = null
    }
  } catch (err) {
    loadError.value = true
    console.error('Failed to load data from backend:', err)
  } finally {
    loadingData.value = false
  }
}

function onFileChange(e) {
  uploadFile.value = e.target.files?.[0] || null
  uploadError.value = ''
}

async function doUpload() {
  if (!uploadFile.value) return
  uploading.value = true
  uploadError.value = ''
  try {
    await uploadPdf(uploadFile.value)
    showUpload.value = false
    uploadFile.value = null
    await loadData()
  } catch (err) {
    uploadError.value = 'Upload failed. Please try again.'
    console.error('Upload failed:', err)
  } finally {
    uploading.value = false
  }
}

async function batchMatchAll() {
  batchRunning.value = true
  try {
    await batchMatch()
    await loadData()
  } catch (err) {
    console.error('Batch match failed:', err)
  } finally {
    batchRunning.value = false
  }
}

// Save scroll position synchronously before navigating away (DOM is still live).
let savedScrollTop = 0
onBeforeRouteLeave(() => {
  savedScrollTop = tableRef.value?.getScrollTop() ?? 0
})

onMounted(() => {
  loadData()
  invitations.load()
  loaded.value = true
})

onActivated(async () => {
  if (!loaded.value) return
  await loadData()
  await nextTick()
  tableRef.value?.setScrollTop(savedScrollTop)
})
</script>
