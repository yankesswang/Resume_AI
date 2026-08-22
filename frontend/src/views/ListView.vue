<template>
  <div class="flex h-full flex-col overflow-hidden">
    <!-- Toolbar -->
    <div class="flex shrink-0 items-center justify-between gap-5 border-b border-line bg-surface px-6 py-3.5">
      <div class="flex min-w-0 items-baseline gap-2.5">
        <h1 class="text-title font-semibold tracking-tight text-ink">人才庫</h1>
        <!-- The filtered/total split is stated in words so a narrowed table is
             never mistaken for an empty database. -->
        <span v-if="candidates.length" class="truncate text-small text-ink-muted">
          <template v-if="visibleCount !== candidates.length">
            篩選出 <span class="font-semibold text-ink">{{ visibleCount }}</span> 位 ／ 共 {{ candidates.length }} 位
          </template>
          <template v-else>
            共 <span class="font-semibold text-ink">{{ candidates.length }}</span> 位人選
          </template>
        </span>
      </div>

      <div class="flex shrink-0 items-center gap-2">
        <button class="btn btn-ghost" :disabled="batchRunning" @click="batchMatchAll">
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': batchRunning }" :stroke-width="2" />
          {{ batchRunning ? '評分中…' : '全部重新評分' }}
        </button>
        <button class="btn btn-primary" @click="showUpload = true">
          <Upload class="h-3.5 w-3.5" :stroke-width="2" />
          上傳履歷
        </button>
      </div>
    </div>

    <div class="min-h-0 flex-1 overflow-auto p-5 lg:p-6">
      <!-- Backend unreachable -->
      <div v-if="loadError" class="mx-auto mt-16 max-w-md text-center">
        <div class="mx-auto mb-4 flex h-11 w-11 items-center justify-center rounded-full border border-bad-line bg-bad-soft">
          <AlertTriangle class="h-5 w-5 text-bad-ink" :stroke-width="2" />
        </div>
        <h2 class="text-title font-semibold text-ink">無法連線到後端服務</h2>
        <p class="mt-1.5 text-small text-ink-muted">請確認 FastAPI 伺服器已啟動：</p>
        <code class="mt-3 block overflow-x-auto rounded-control border border-line bg-surface-2 px-3 py-2 text-left font-mono text-micro text-ink-muted">uv run python -m uvicorn main:app --reload --host 0.0.0.0 --port 8000</code>
        <button class="btn btn-primary mx-auto mt-5" :disabled="loadingData" @click="loadData">
          <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': loadingData }" :stroke-width="2" />
          {{ loadingData ? '連線中…' : '重新連線' }}
        </button>
      </div>

      <!-- First load: a skeleton, not a blank page. -->
      <div v-else-if="loadingData && !candidates.length" class="space-y-2">
        <div class="h-11 animate-pulse rounded-card bg-surface" />
        <div class="card overflow-hidden">
          <div v-for="n in 8" :key="n" class="flex items-center gap-3 border-b border-line/60 px-4 py-3 last:border-0">
            <div class="h-7 w-7 shrink-0 animate-pulse rounded-full bg-surface-2" />
            <div class="h-3 animate-pulse rounded bg-surface-2" :style="{ width: `${18 + (n % 4) * 6}%` }" />
            <div class="ml-auto h-3 w-12 animate-pulse rounded bg-surface-2" />
          </div>
        </div>
      </div>

      <template v-else>
        <FilterPanel
          :education-levels="filterOptions.education_levels"
          :skill-tags="filterOptions.skill_tags"
          :experience-ranges="filterOptions.experience_ranges"
          :score-ranges="filterOptions.score_ranges"
          :ai-tiers="filterOptions.ai_tiers || []"
          :import-batches="importBatches"
        />
        <CandidateTable ref="tableRef" :candidates="candidates" />
      </template>
    </div>

    <!-- Upload -->
    <div v-if="showUpload" class="fixed inset-0 z-50 flex items-center justify-center p-4">
      <div class="absolute inset-0 bg-black/60 backdrop-blur-sm" @click="closeUpload" />
      <div class="card relative w-full max-w-md bg-surface-3 p-5 shadow-2xl">
        <div class="mb-4 flex items-start justify-between">
          <div>
            <h2 class="text-title font-semibold text-ink">上傳履歷 PDF</h2>
            <p class="mt-0.5 text-small text-ink-muted">上傳後系統會自動解析並評分</p>
          </div>
          <button class="rounded p-1 text-ink-faint transition-colors hover:text-ink" title="關閉" @click="closeUpload">
            <X class="h-4 w-4" :stroke-width="2" />
          </button>
        </div>

        <label
          class="block cursor-pointer rounded-card border border-dashed p-7 text-center transition-colors"
          :class="uploadFile || dragging
            ? 'border-brand-line bg-brand-soft'
            : 'border-line-strong bg-surface-2 hover:border-brand hover:bg-surface'"
          @dragover.prevent="dragging = true"
          @dragleave.prevent="dragging = false"
          @drop.prevent="onDrop"
        >
          <input type="file" accept=".pdf,application/pdf" class="hidden" @change="onFileChange" />
          <File class="mx-auto mb-2.5 h-8 w-8" :class="uploadFile || dragging ? 'text-brand-ink' : 'text-ink-faint'" :stroke-width="1.5" />
          <div v-if="uploadFile">
            <div class="truncate text-small font-medium text-brand-ink">{{ uploadFile.name }}</div>
            <div class="mt-0.5 text-micro text-ink-faint">{{ formatBytes(uploadFile.size) }} ・ 點擊可重新選擇</div>
          </div>
          <div v-else>
            <div class="text-small font-medium text-ink">點擊選擇檔案，或拖曳至此</div>
            <div class="mt-0.5 text-micro text-ink-faint">僅支援 PDF 格式</div>
          </div>
        </label>

        <p v-if="uploadError" class="mt-2.5 rounded-control border border-bad-line bg-bad-soft px-3 py-2 text-small text-bad-ink">
          {{ uploadError }}
        </p>

        <div class="mt-4 flex justify-end gap-2">
          <button class="btn btn-ghost" :disabled="uploading" @click="closeUpload">取消</button>
          <button class="btn btn-primary" :disabled="!uploadFile || uploading" @click="doUpload">
            <RefreshCw class="h-3.5 w-3.5 animate-spin" :stroke-width="2" v-if="uploading" />
            {{ uploading ? '解析中…' : '上傳並解析' }}
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
import { ref, computed, onMounted, onActivated, nextTick } from 'vue'
import { onBeforeRouteLeave, useRoute, useRouter } from 'vue-router'
import { fetchCandidates, fetchFilters, fetchImportBatches, uploadPdf, batchMatch } from '../api'
import { useBookmarkStore } from '../stores/bookmarks'
import { useInvitationStore } from '../stores/invitations'
import { useFilterStore } from '../stores/filters'
import FilterPanel from '../components/FilterPanel.vue'
import CandidateTable from '../components/CandidateTable.vue'
import { AlertTriangle, File, RefreshCw, Upload, X } from 'lucide-vue-next'

const bookmarks = useBookmarkStore()
const invitations = useInvitationStore()
const filterStore = useFilterStore()

const tableRef = ref(null)
const candidates = ref([])
const importBatches = ref([])
const filterOptions = ref({ education_levels: [], skill_tags: [], experience_ranges: [], score_ranges: [], ai_tiers: [] })
const showUpload = ref(false)
const uploadFile = ref(null)
const uploading = ref(false)
const uploadError = ref('')
const batchRunning = ref(false)
const dragging = ref(false)
const loaded = ref(false)
const loadError = ref(false)
const loadingData = ref(false)

async function loadData() {
  loadError.value = false
  loadingData.value = true
  try {
    const [cands, filters, batches] = await Promise.all([
      fetchCandidates(),
      fetchFilters(),
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

const visibleCount = computed(() => tableRef.value?.filteredCount ?? candidates.value.length)

function setFile(file) {
  if (!file) return
  if (!file.name.toLowerCase().endsWith('.pdf')) {
    uploadError.value = '只能上傳 PDF 檔案'
    return
  }
  uploadFile.value = file
  uploadError.value = ''
}

function onFileChange(e) {
  setFile(e.target.files?.[0])
}

function onDrop(e) {
  dragging.value = false
  setFile(e.dataTransfer?.files?.[0])
}

function closeUpload() {
  if (uploading.value) return
  showUpload.value = false
  uploadFile.value = null
  uploadError.value = ''
}

function formatBytes(bytes) {
  if (!bytes) return ''
  const mb = bytes / 1024 / 1024
  return mb >= 1 ? `${mb.toFixed(1)} MB` : `${Math.round(bytes / 1024)} KB`
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
    // Surface the server's own reason (413 size, 415 not-a-PDF, 429 rate
    // limit) instead of a fixed "check the format" line: the format is usually
    // fine, and the generic text sent the operator looking in the wrong place.
    uploadError.value =
      err?.response?.data?.detail || err?.message || '上傳失敗，請稍後再試一次'
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

// `?dedupe=` is the landing spot for the retired /unique page's bookmarks: it
// sets the filter the page used to hardcode, then strips itself from the URL so
// the choice stays a normal filter the user can change or clear — a query param
// left in place would silently re-apply on every reload.
const route = useRoute()
const router = useRouter()

function applyDedupeQuery() {
  const wanted = route.query.dedupe
  if (typeof wanted !== 'string') return
  if (['unique', 'duplicate', 'review'].includes(wanted)) {
    filterStore.dedupeStatus = wanted
    filterStore.panelOpen = true
  }
  router.replace({ name: 'list', query: {} })
}

onMounted(() => {
  applyDedupeQuery()
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
