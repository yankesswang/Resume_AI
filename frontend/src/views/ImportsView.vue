<template>
  <div class="flex flex-col h-full overflow-hidden">
    <!-- Toolbar -->
    <div class="flex items-center justify-between px-5 py-3 bg-surface border-b border-line shrink-0">
      <div class="flex items-center gap-2 text-small text-ink-muted min-w-0">
        <span class="font-semibold text-ink whitespace-nowrap">匯入紀錄</span>
        <span class="text-ink-faint">/</span>
        <span class="font-semibold text-ink">{{ batches.length }}</span>
        <span>批次</span>
        <template v-if="totalCandidates">
          <span class="text-ink-faint">·</span>
          <span class="font-semibold text-ink">{{ totalCandidates.toLocaleString() }}</span>
          <span>位候選人</span>
        </template>
      </div>
      <button
        @click="load"
        :disabled="loading"
        class="inline-flex items-center gap-1.5 px-3 py-1.5 text-micro font-semibold border border-line rounded-control text-ink-muted hover:border-line-strong hover:text-ink disabled:opacity-50 transition"
      >
        <RefreshCw class="h-3.5 w-3.5" :class="{ 'animate-spin': loading }" :stroke-width="2" />
        重新載入
      </button>
    </div>

    <div class="flex-1 overflow-auto p-5">
      <!-- Error -->
      <div v-if="loadError" class="flex flex-col items-center justify-center py-20 text-center">
        <div class="h-12 w-12 rounded-full bg-bad-soft flex items-center justify-center mb-4">
          <AlertTriangle class="h-6 w-6 text-bad-ink" :stroke-width="2" />
        </div>
        <h3 class="text-small font-semibold text-ink mb-1">無法連線到後端</h3>
        <button
          @click="load"
          class="mt-3 px-4 py-2 text-small font-semibold bg-brand text-white rounded-control hover:bg-brand-hover transition"
        >
          重試
        </button>
      </div>

      <!-- Empty -->
      <div v-else-if="!loading && !batches.length" class="flex flex-col items-center justify-center py-20 text-center">
        <div class="h-12 w-12 rounded-full bg-surface-2 flex items-center justify-center mb-4">
          <Inbox class="h-6 w-6 text-ink-faint" :stroke-width="1.5" />
        </div>
        <h3 class="text-small font-semibold text-ink mb-1">還沒有匯入紀錄</h3>
        <p class="text-micro text-ink-faint">用 scripts/import_104_zip.py 匯入 104 履歷 ZIP 後會出現在這裡</p>
      </div>

      <!-- Batch cards -->
      <div v-else class="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <router-link
          v-for="batch in batches"
          :key="batch.id"
          :to="{ name: 'import-detail', params: { id: batch.id } }"
          class="relative block bg-surface border border-line rounded-card p-4 hover:border-brand-line hover:shadow-sm transition group"
          :class="batch.failed_count ? 'border-bad-line' : ''"
        >
          <!-- The whole card is a router-link, so the delete button must stop
               the click from navigating as well as deleting. -->
          <button
            @click.prevent.stop="askDelete(batch)"
            class="absolute top-3 right-3 z-10 p-1.5 rounded-control text-ink-faint opacity-0 group-hover:opacity-100 focus:opacity-100 hover:bg-bad-soft hover:text-bad-ink transition"
            title="刪除此匯入紀錄"
          >
            <Trash2 class="h-3.5 w-3.5" :stroke-width="2" />
          </button>
          <div class="flex items-start justify-between gap-2 mb-3">
            <div class="min-w-0">
              <div class="text-small font-semibold text-ink truncate group-hover:text-brand-ink transition" :title="batch.batch_name">
                {{ batch.batch_name }}
              </div>
              <div class="text-micro text-ink-faint mt-0.5">
                {{ formatDate(batch.created_at) }}
              </div>
            </div>
            <span
              class="text-micro font-semibold rounded-full px-2 py-0.5 shrink-0 border mr-7"
              :class="batch.status === 'uploaded'
                ? 'bg-brand-soft text-brand-ink border-brand-line'
                : 'bg-good-soft text-good-ink border-good-line'"
            >
              {{ batch.status === 'uploaded' ? '手動上傳' : 'ZIP 匯入' }}
            </span>
          </div>

          <div class="flex items-baseline gap-1.5 mb-3">
            <span class="text-display font-bold text-ink">{{ (batch.total_candidates || 0).toLocaleString() }}</span>
            <span class="text-micro text-ink-faint">位候選人 · {{ batch.total_files || 0 }} 個 PDF</span>
          </div>

          <!-- Parse failures: the reason a batch has fewer candidates than
               expected. Shown before the dedupe bar because a failed parse
               makes those counts incomplete rather than merely uninteresting. -->
          <div
            v-if="batch.failed_count"
            class="flex items-center gap-1.5 mb-2 px-2 py-1 rounded-control bg-bad-soft border border-bad-line text-micro text-bad-ink"
          >
            <AlertTriangle class="h-3.5 w-3.5 shrink-0" :stroke-width="2" />
            <span class="font-semibold">{{ batch.failed_count }} 個 PDF 解析失敗</span>
            <span class="text-ink-faint">· 點開查看原因</span>
          </div>

          <!-- Dedupe distribution bar (uploads have no dedupe verdicts yet) -->
          <div v-if="dedupeTotal(batch)" class="flex h-1.5 rounded-full overflow-hidden bg-surface-2 mb-2">
            <div
              class="bg-emerald-400"
              :style="{ width: pct(batch.unique_count, dedupeTotal(batch)) }"
              :title="`新履歷 ${batch.unique_count}`"
            />
            <div
              class="bg-line-strong"
              :style="{ width: pct(batch.duplicate_count, dedupeTotal(batch)) }"
              :title="`重複 ${batch.duplicate_count}`"
            />
            <div
              class="bg-amber-400"
              :style="{ width: pct(batch.review_count, dedupeTotal(batch)) }"
              :title="`待確認 ${batch.review_count}`"
            />
          </div>

          <div class="flex items-center gap-3 text-micro">
            <template v-if="dedupeTotal(batch)">
              <span class="flex items-center gap-1 text-ink-muted">
                <span class="h-2 w-2 rounded-full bg-emerald-400" />新 {{ batch.unique_count || 0 }}
              </span>
              <span class="flex items-center gap-1 text-ink-muted">
                <span class="h-2 w-2 rounded-full bg-line-strong" />重複 {{ batch.duplicate_count || 0 }}
              </span>
              <span v-if="batch.review_count" class="flex items-center gap-1 text-ink-muted">
                <span class="h-2 w-2 rounded-full bg-amber-400" />待確認 {{ batch.review_count }}
              </span>
            </template>
            <span v-else class="text-ink-faint">尚未執行去重比對</span>
          </div>
        </router-link>
      </div>
    </div>

    <!-- Delete confirmation -->
    <div
      v-if="pendingDelete"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="pendingDelete = null"
    >
      <div class="w-full max-w-md bg-surface border border-line rounded-card shadow-lg p-5">
        <div class="flex items-start gap-3 mb-4">
          <div class="h-9 w-9 rounded-full bg-bad-soft flex items-center justify-center shrink-0">
            <AlertTriangle class="h-4.5 w-4.5 text-bad-ink" :stroke-width="2" />
          </div>
          <div class="min-w-0">
            <h3 class="text-small font-semibold text-ink">刪除匯入紀錄</h3>
            <p class="text-micro text-ink-muted mt-0.5 break-words">
              {{ pendingDelete.batch_name }}
            </p>
          </div>
        </div>

        <div class="rounded-control bg-surface-2 border border-line p-3 mb-4">
          <label class="flex items-start gap-2 cursor-pointer">
            <input type="checkbox" v-model="alsoDeleteCandidates" class="mt-0.5 shrink-0" />
            <span class="text-micro text-ink-muted">
              <span class="font-semibold text-ink">同時刪除這批的 {{ pendingDelete.total_candidates || 0 }} 位候選人</span>
              <span class="block mt-1">
                不勾選時只移除匯入紀錄，候選人會保留但失去批次歸屬（日後可用
                repair_import_batches.py 還原）。
              </span>
            </span>
          </label>
        </div>

        <p v-if="alsoDeleteCandidates" class="text-micro text-bad-ink mb-3">
          此操作無法復原，將永久刪除 {{ pendingDelete.total_candidates || 0 }} 位候選人及其評分。
        </p>
        <p v-if="deleteError" class="text-micro text-bad-ink mb-3">{{ deleteError }}</p>

        <div class="flex justify-end gap-2">
          <button
            @click="pendingDelete = null"
            :disabled="deleting"
            class="px-3 py-1.5 text-micro font-semibold border border-line rounded-control text-ink-muted hover:text-ink disabled:opacity-50 transition"
          >
            取消
          </button>
          <button
            @click="confirmDelete"
            :disabled="deleting"
            class="px-3 py-1.5 text-micro font-semibold rounded-control bg-bad-ink text-white hover:opacity-90 disabled:opacity-50 transition"
          >
            {{ deleting ? '刪除中…' : '確認刪除' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script>
export default { name: 'ImportsView' }
</script>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchImportBatches, deleteImportBatch } from '../api'
import { AlertTriangle, Inbox, RefreshCw, Trash2 } from 'lucide-vue-next'

const batches = ref([])
const loading = ref(false)
const loadError = ref(false)

const totalCandidates = computed(() =>
  batches.value.reduce((sum, b) => sum + (b.total_candidates || 0), 0)
)

function pct(part, total) {
  if (!total) return '0%'
  return `${((part || 0) / total) * 100}%`
}

function dedupeTotal(batch) {
  return (batch.unique_count || 0) + (batch.duplicate_count || 0) + (batch.review_count || 0)
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

const pendingDelete = ref(null)
const alsoDeleteCandidates = ref(false)
const deleting = ref(false)
const deleteError = ref('')

function askDelete(batch) {
  pendingDelete.value = batch
  // Reset per-dialog, so a previous "delete the people too" cannot carry over
  // into the next batch the operator opens.
  alsoDeleteCandidates.value = false
  deleteError.value = ''
}

async function confirmDelete() {
  if (!pendingDelete.value) return
  deleting.value = true
  deleteError.value = ''
  try {
    await deleteImportBatch(pendingDelete.value.id, alsoDeleteCandidates.value)
    pendingDelete.value = null
    await load()
  } catch (err) {
    deleteError.value =
      err?.response?.data?.detail || err?.message || '刪除失敗，請稍後再試'
    console.error('Delete import batch failed:', err)
  } finally {
    deleting.value = false
  }
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    batches.value = await fetchImportBatches()
  } catch (err) {
    loadError.value = true
    console.error('Failed to load import batches:', err)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>
