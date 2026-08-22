<template>
  <div class="flex flex-col h-full overflow-hidden">
    <!-- Header -->
    <div class="flex items-center gap-3 px-5 py-3 bg-surface border-b border-line shrink-0">
      <button
        @click="$router.push({ name: 'imports' })"
        class="p-1.5 rounded-control text-ink-faint hover:text-ink hover:bg-surface-2 transition"
      >
        <ChevronLeft class="h-4 w-4" :stroke-width="2.5" />
      </button>
      <div class="min-w-0">
        <div class="text-small font-semibold text-ink truncate">
          {{ batch?.batch_name || '匯入批次' }}
        </div>
        <div v-if="batch" class="text-micro text-ink-faint">
          {{ formatDate(batch.created_at) }} ·
          {{ (batch.total_candidates || 0).toLocaleString() }} 位候選人 ·
          {{ batch.files?.length || 0 }} 個 PDF
        </div>
      </div>
      <router-link
        v-if="batch"
        :to="{ name: 'list' }"
        class="ml-auto text-micro font-semibold text-ink-muted hover:text-ink border border-line hover:border-line-strong rounded-control px-3 py-1.5 transition"
      >
        在候選人總表檢視
      </router-link>
    </div>

    <div class="flex-1 overflow-auto p-5">
      <div v-if="loadError" class="flex flex-col items-center justify-center py-20 text-center">
        <h3 class="text-small font-semibold text-ink mb-1">找不到這個匯入批次</h3>
        <router-link :to="{ name: 'imports' }" class="mt-3 text-micro text-brand-ink hover:underline">
          回到匯入紀錄
        </router-link>
      </div>

      <template v-else-if="batch">
        <!-- Source info -->
        <div class="bg-surface border border-line rounded-card p-4 mb-4">
          <div class="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 text-micro">
            <div>
              <div class="text-ink-faint mb-0.5">來源</div>
              <div class="font-medium text-ink break-all">
                {{ isUpload ? '前端手動上傳 PDF' : (zipName || '—') }}
              </div>
            </div>
            <div>
              <div class="text-ink-faint mb-0.5">類型</div>
              <div class="font-medium text-ink">
                {{ isUpload ? '手動上傳' : 'ZIP 匯入' }}
              </div>
            </div>
            <div>
              <div class="text-ink-faint mb-0.5">完成時間</div>
              <div class="font-medium text-ink">{{ formatDate(batch.finished_at) }}</div>
            </div>
            <div>
              <div class="text-ink-faint mb-0.5">去重結果</div>
              <div class="font-medium text-ink">
                <template v-if="hasDedupe">
                  新 {{ batch.unique_count || 0 }} ·
                  重複 {{ batch.duplicate_count || 0 }} ·
                  待確認 {{ batch.review_count || 0 }}
                </template>
                <span v-else class="text-ink-faint">尚未執行去重比對</span>
              </div>
            </div>
          </div>
          <div v-if="batch.notes" class="mt-3 pt-3 border-t border-line text-micro text-ink-muted">
            {{ batch.notes }}
          </div>
        </div>

        <!-- File list -->
        <div class="bg-surface border border-line rounded-card overflow-hidden">
          <div class="px-4 py-2.5 border-b border-line flex items-center gap-2">
            <span class="text-micro font-semibold text-ink">解析檔案</span>
            <span class="text-micro text-ink-faint">點檔案展開該次 parsing 出來的候選人</span>
          </div>

          <div v-for="file in batch.files" :key="file.id" class="border-b border-line last:border-b-0">
            <!-- File row -->
            <button
              @click="toggleFile(file.id)"
              class="w-full flex items-center gap-3 px-4 py-3 hover:bg-surface-2 transition text-left"
            >
              <ChevronRight class="h-3.5 w-3.5 text-ink-faint shrink-0 transition-transform" :class="{ 'rotate-90': expanded === file.id }" :stroke-width="2.5" />
              <File class="h-4 w-4 text-bad-ink shrink-0" :stroke-width="1.5" />
              <span class="text-small font-medium text-ink shrink-0">{{ file.pdf_name }}</span>
              <span
                v-if="file.parse_status !== 'parsed'"
                class="text-micro font-semibold rounded-full px-2 py-0.5 shrink-0 border"
                :class="file.parse_status === 'partial'
                  ? 'bg-warn-soft text-warn-ink border-warn-line'
                  : 'bg-bad-soft text-bad-ink border-bad-line'"
              >
                {{ statusLabel(file.parse_status) }}
              </span>
              <span class="ml-auto flex items-center gap-3 text-micro shrink-0">
                <span class="text-ink-muted">
                  <span class="font-semibold text-ink">{{ file.candidate_count }}</span> 位
                </span>
                <span v-if="hasDedupe" class="hidden sm:flex items-center gap-2 text-ink-faint">
                  <span class="flex items-center gap-1">
                    <span class="h-1.5 w-1.5 rounded-full bg-emerald-400" />{{ file.unique_count }}
                  </span>
                  <span class="flex items-center gap-1">
                    <span class="h-1.5 w-1.5 rounded-full bg-line-strong" />{{ file.duplicate_count }}
                  </span>
                  <span v-if="file.review_count" class="flex items-center gap-1">
                    <span class="h-1.5 w-1.5 rounded-full bg-amber-400" />{{ file.review_count }}
                  </span>
                </span>
              </span>
            </button>

            <!-- Expanded candidates -->
            <div v-if="expanded === file.id" class="bg-surface-2/70 px-4 py-3 border-t border-line">
              <!-- The parse error, shown in full: it names the actual cause
                   (a damaged PDF, a scanned page with no text layer), which is
                   what tells the operator whether to re-export or switch
                   parser backend. -->
              <div
                v-if="file.error_message"
                class="mb-3 rounded-control border p-3"
                :class="file.parse_status === 'partial'
                  ? 'bg-warn-soft border-warn-line'
                  : 'bg-bad-soft border-bad-line'"
              >
                <div class="flex items-center gap-1.5 mb-1">
                  <AlertTriangle
                    class="h-3.5 w-3.5 shrink-0"
                    :class="file.parse_status === 'partial' ? 'text-warn-ink' : 'text-bad-ink'"
                    :stroke-width="2"
                  />
                  <span
                    class="text-micro font-semibold"
                    :class="file.parse_status === 'partial' ? 'text-warn-ink' : 'text-bad-ink'"
                  >解析錯誤</span>
                </div>
                <pre class="text-micro whitespace-pre-wrap break-words font-mono text-ink-muted m-0">{{ file.error_message }}</pre>
              </div>

              <div v-if="loadingFile" class="flex items-center gap-2 text-micro text-ink-faint py-3">
                <RefreshCw class="h-3.5 w-3.5 animate-spin" :stroke-width="2" />
                載入候選人…
              </div>

              <div v-else-if="!fileCandidates.length" class="text-micro text-ink-faint py-3">
                這個檔案沒有候選人紀錄
              </div>

              <template v-else>
                <!-- Search within file -->
                <div class="flex items-center gap-2 mb-3">
                  <input
                    v-model="nameQuery"
                    placeholder="搜尋姓名…"
                    class="py-1.5 px-2.5 text-small border border-line rounded-control bg-surface focus:border-brand focus:ring-1 focus:ring-brand outline-none transition w-48"
                  />
                  <span class="text-micro text-ink-faint">
                    {{ visibleCandidates.length }} / {{ fileCandidates.length }}
                  </span>
                </div>

                <div class="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                  <router-link
                    v-for="c in visibleCandidates"
                    :key="c.id"
                    :to="{ name: 'detail', params: { id: c.id } }"
                    class="flex items-center gap-2 bg-surface border border-line rounded-control px-2.5 py-2 hover:border-brand-line hover:shadow-sm transition group min-w-0"
                  >
                    <img
                      v-if="c.photo_url"
                      :src="c.photo_url"
                      class="h-7 w-7 rounded-full object-cover bg-surface-2 shrink-0"
                      loading="lazy"
                      @error="(e) => { e.target.style.display = 'none' }"
                    />
                    <div
                      v-else
                      class="h-7 w-7 rounded-full bg-surface-2 flex items-center justify-center text-micro font-semibold text-ink-faint shrink-0"
                    >
                      {{ (c.name || '?').slice(0, 1) }}
                    </div>
                    <div class="min-w-0 flex-1">
                      <div class="text-small font-medium text-ink truncate group-hover:text-brand-ink transition">
                        {{ c.name || `#${c.id}（無姓名）` }}
                      </div>
                      <div class="text-micro text-ink-faint truncate">
                        {{ [c.education_level, c.school].filter(Boolean).join(' · ') || '—' }}
                      </div>
                    </div>
                    <div class="flex flex-col items-end gap-0.5 shrink-0">
                      <span
                        v-if="c.overall_score != null"
                        class="text-micro font-semibold"
                        :class="scoreClass(c.overall_score)"
                      >
                        {{ Math.round(c.overall_score) }}
                      </span>
                      <span
                        v-if="c.dedupe_status && c.dedupe_status !== 'unique'"
                        class="chip"
                        :class="c.dedupe_status === 'review'
                          ? 'bg-warn-soft text-warn-ink'
                          : 'bg-surface-2 text-ink-muted'"
                      >
                        {{ c.dedupe_status === 'review' ? '待確認' : '重複' }}
                      </span>
                    </div>
                  </router-link>
                </div>
              </template>
            </div>
          </div>
        </div>
      </template>
    </div>
  </div>
</template>

<script>
export default { name: 'ImportDetailView' }
</script>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { fetchImportBatch, fetchImportFileCandidates } from '../api'
import { AlertTriangle, ChevronLeft, ChevronRight, File, RefreshCw } from 'lucide-vue-next'

// Parse statuses come from the importer as bare keys; the raw value ("failed")
// was being rendered straight into the badge.
const STATUS_LABELS = {
  parsed: '已解析',
  failed: '解析失敗',
  partial: '部分失敗',
  pending: '等待中',
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status
}

const props = defineProps({
  id: { type: [String, Number], required: true },
})

const batch = ref(null)
const loadError = ref(false)
const expanded = ref(null)
const fileCandidates = ref([])
const loadingFile = ref(false)
const nameQuery = ref('')

const isUpload = computed(() => batch.value?.status === 'uploaded')

// Uploads are not run through scripts/organize_resume_db.py, so they carry no
// dedupe verdicts; showing "unique 0 / duplicate 0" would read as a real result.
const hasDedupe = computed(() => {
  const b = batch.value
  if (!b) return false
  return (b.unique_count || 0) + (b.duplicate_count || 0) + (b.review_count || 0) > 0
})

const zipName = computed(() => {
  const p = batch.value?.source_zip_path || ''
  return p.split('/').pop()
})

const visibleCandidates = computed(() => {
  const q = nameQuery.value.trim().toLowerCase()
  if (!q) return fileCandidates.value
  return fileCandidates.value.filter((c) => {
    const name = (c.name || '').toLowerCase()
    const en = (c.english_name || '').toLowerCase()
    return name.includes(q) || en.includes(q)
  })
})

function scoreClass(score) {
  if (score >= 80) return 'text-good-ink'
  if (score >= 60) return 'text-brand-ink'
  if (score >= 40) return 'text-warn-ink'
  return 'text-ink-faint'
}

function formatDate(raw) {
  if (!raw) return '—'
  const d = new Date(raw.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return raw
  return d.toLocaleString('zh-TW', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  })
}

async function toggleFile(fileId) {
  if (expanded.value === fileId) {
    expanded.value = null
    return
  }
  expanded.value = fileId
  nameQuery.value = ''
  fileCandidates.value = []
  loadingFile.value = true
  try {
    fileCandidates.value = await fetchImportFileCandidates(fileId)
  } catch (err) {
    console.error('Failed to load candidates for import file:', err)
    fileCandidates.value = []
  } finally {
    loadingFile.value = false
  }
}

async function load() {
  loadError.value = false
  expanded.value = null
  try {
    batch.value = await fetchImportBatch(props.id)
    if (batch.value?.error) {
      loadError.value = true
      batch.value = null
    }
  } catch (err) {
    loadError.value = true
    console.error('Failed to load import batch:', err)
  }
}

watch(() => props.id, load)
onMounted(load)
</script>
