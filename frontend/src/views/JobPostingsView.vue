<template>
  <div class="flex h-full flex-col overflow-hidden">
    <div class="flex shrink-0 items-center justify-between border-b border-line bg-surface px-5 py-3">
      <div class="flex min-w-0 items-center gap-2 text-small text-ink-muted">
        <span class="whitespace-nowrap font-semibold text-ink">職缺管理</span>
        <span class="text-ink-faint">/</span>
        <span>{{ jobs.length }} 個職缺</span>
      </div>
      <button
        @click="showUpload = true"
        class="rounded-control bg-brand px-4 py-1.5 text-micro font-semibold text-white transition hover:bg-brand-hover"
      >
        上傳職缺文件
      </button>
    </div>

    <div class="flex-1 overflow-auto p-5">
      <div v-if="loading" class="py-20 text-center text-small text-ink-faint">載入中…</div>

      <div v-else-if="loadError" class="py-20 text-center">
        <h3 class="mb-3 text-small font-semibold text-ink">無法連線到後端</h3>
        <button @click="load" class="rounded-control bg-brand px-4 py-2 text-small font-semibold text-white">重試</button>
      </div>

      <div v-else class="mx-auto max-w-5xl space-y-4">
        <div class="rounded-card border border-line bg-surface-2 p-4">
          <p class="text-small font-semibold text-ink">上傳職位說明，自動建立篩選標準</p>
          <p class="mt-1 text-micro leading-relaxed text-ink-muted">
            系統會讀取職缺文件，為這個職位產生一套專屬的履歷評分標準：包含四個深度級距的判斷依據、
            該領域的關鍵字、能力面向與硬性條件。不限工程職，業務、行銷、財會、人資、營運、設計、
            製造等各領域皆適用。產生後為草稿，需人工檢視確認才會套用。
          </p>
        </div>

        <div v-if="!jobs.length" class="rounded-card border border-line bg-surface py-16 text-center">
          <p class="text-small text-ink-muted">尚未建立任何職缺</p>
          <button
            @click="showUpload = true"
            class="mt-3 rounded-control bg-brand px-4 py-2 text-small font-semibold text-white"
          >
            上傳第一份職缺文件
          </button>
        </div>

        <div v-else class="space-y-2">
          <article
            v-for="job in jobs"
            :key="job.id"
            class="rounded-card border border-line bg-surface p-4 transition hover:border-line-strong"
          >
            <div class="flex items-start justify-between gap-4">
              <div class="min-w-0 flex-1">
                <div class="flex flex-wrap items-center gap-2">
                  <router-link
                    :to="`/jobs/${job.id}`"
                    class="text-small font-semibold text-ink no-underline hover:text-brand-ink"
                  >
                    {{ job.job_title || job.title || '未命名職缺' }}
                  </router-link>
                  <span v-if="job.domain" class="chip border-line bg-surface-2 text-ink-muted">
                    {{ job.domain }}
                  </span>
                  <span class="chip" :class="statusClass(job.profile_status)">
                    {{ statusLabel(job.profile_status) }}
                  </span>
                  <span
                    v-if="job.id === activeJobId"
                    class="chip border-brand-line bg-brand-soft text-brand-ink"
                  >
                    使用中
                  </span>
                </div>
                <p v-if="job.job_summary" class="mt-1.5 line-clamp-2 text-micro leading-relaxed text-ink-muted">
                  {{ job.job_summary }}
                </p>
                <p v-if="job.source_document" class="mt-1 text-micro text-ink-faint">
                  來源：{{ job.source_document }}
                </p>
              </div>
              <div class="flex shrink-0 items-center gap-2">
                <router-link
                  :to="`/jobs/${job.id}`"
                  class="rounded-control border border-line px-3 py-1.5 text-micro font-semibold text-ink-muted no-underline transition hover:border-line-strong hover:text-ink"
                >
                  檢視標準
                </router-link>
                <button
                  v-if="job.id !== activeJobId"
                  @click="doDelete(job)"
                  class="rounded-control border border-line px-3 py-1.5 text-micro font-semibold text-ink-muted transition hover:border-bad-line hover:text-bad-ink"
                >
                  刪除
                </button>
              </div>
            </div>
          </article>
        </div>
      </div>
    </div>

    <!-- Upload dialog -->
    <div
      v-if="showUpload"
      class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
      @click.self="closeUpload"
    >
      <div class="w-full max-w-xl rounded-card border border-line bg-surface p-5 shadow-lg">
        <h2 class="text-small font-semibold text-ink">上傳職缺文件</h2>
        <p class="mt-1 text-micro text-ink-muted">支援 PDF、Word (.docx) 與純文字，也可以直接貼上內容。</p>

        <div class="mt-4 space-y-3">
          <div>
            <label class="mb-1 block text-micro font-medium text-ink-muted">職缺文件</label>
            <input
              type="file"
              accept=".pdf,.docx,.txt,.md"
              @change="onFile"
              class="w-full field px-3 py-2 text-micro"
            />
          </div>

          <div class="flex items-center gap-2 text-micro text-ink-faint">
            <span class="h-px flex-1 bg-line"></span>或<span class="h-px flex-1 bg-line"></span>
          </div>

          <div>
            <label class="mb-1 block text-micro font-medium text-ink-muted">直接貼上職缺內容</label>
            <textarea
              v-model="pastedText"
              rows="7"
              placeholder="職缺名稱、工作內容、應徵條件…"
              class="w-full field px-3 py-2 font-mono text-micro leading-relaxed"
            ></textarea>
          </div>

          <div>
            <label class="mb-1 block text-micro font-medium text-ink-muted">職缺名稱（選填，留空則由文件判斷）</label>
            <input
              v-model="jobTitle"
              type="text"
              class="w-full field px-3 py-2 text-micro"
            />
          </div>
        </div>

        <div v-if="uploadError" class="mt-3 rounded-card border border-bad-line bg-bad-soft p-3 text-micro text-bad-ink">
          {{ uploadError }}
        </div>

        <div v-if="uploading" class="mt-3 rounded-card border border-line bg-surface-2 p-3 text-micro text-ink-muted">
          正在解析職缺並建立評分標準，這需要 1-2 分鐘，請不要關閉頁面…
        </div>

        <div class="mt-5 flex justify-end gap-2">
          <button
            @click="closeUpload"
            :disabled="uploading"
            class="rounded-control border border-line px-3 py-1.5 text-micro font-semibold text-ink-muted disabled:opacity-50"
          >
            取消
          </button>
          <button
            @click="doUpload"
            :disabled="uploading || (!file && !pastedText.trim())"
            class="rounded-control bg-brand px-4 py-1.5 text-micro font-semibold text-white disabled:opacity-40"
          >
            {{ uploading ? '建立中…' : '建立評分標準' }}
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { deleteJobPosting, fetchJobPostings, uploadJobPosting } from '../api'

const router = useRouter()

const jobs = ref([])
const activeJobId = ref(null)
const loading = ref(true)
const loadError = ref(false)

const showUpload = ref(false)
const file = ref(null)
const pastedText = ref('')
const jobTitle = ref('')
const uploading = ref(false)
const uploadError = ref('')

const STATUS = {
  ready: { label: '已啟用', cls: 'border-good-line bg-good-soft text-good-ink' },
  draft: { label: '草稿待確認', cls: 'border-warn-line bg-warn-soft text-warn-ink' },
  failed: { label: '生成失敗', cls: 'border-bad-line bg-bad-soft text-bad-ink' },
  none: { label: '無評分標準', cls: 'border-line bg-surface-2 text-ink-muted' },
}
function statusLabel(s) {
  return (STATUS[s] || STATUS.none).label
}
function statusClass(s) {
  return (STATUS[s] || STATUS.none).cls
}

async function load() {
  loading.value = true
  loadError.value = false
  try {
    const data = await fetchJobPostings()
    jobs.value = data.jobs || []
    activeJobId.value = data.active_job_id ?? null
  } catch {
    loadError.value = true
  } finally {
    loading.value = false
  }
}

function onFile(e) {
  file.value = e.target.files?.[0] || null
}

function closeUpload() {
  if (uploading.value) return
  showUpload.value = false
  uploadError.value = ''
}

async function doUpload() {
  uploading.value = true
  uploadError.value = ''
  try {
    const res = await uploadJobPosting({
      file: file.value,
      text: pastedText.value.trim(),
      title: jobTitle.value.trim(),
    })
    showUpload.value = false
    file.value = null
    pastedText.value = ''
    jobTitle.value = ''
    // Straight into review: a generated standard is a draft, and the whole
    // point is that a person reads it before it screens anybody.
    router.push(`/jobs/${res.job_id}`)
  } catch (e) {
    uploadError.value = e?.response?.data?.detail || e?.message || '上傳失敗'
  } finally {
    uploading.value = false
  }
}

async function doDelete(job) {
  if (!confirm(`確定要刪除「${job.job_title || job.title}」？此職缺的評分結果也會一併刪除。`)) return
  try {
    await deleteJobPosting(job.id)
    await load()
  } catch (e) {
    alert(e?.response?.data?.detail || '刪除失敗')
  }
}

onMounted(load)
</script>
