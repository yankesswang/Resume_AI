<template>
  <div
    class="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4"
    @click.self="$emit('close')"
  >
    <div class="flex max-h-[88vh] w-full max-w-2xl flex-col rounded-card border border-line bg-surface shadow-lg">
      <!-- Header -->
      <div class="flex items-center gap-3 border-b border-line px-5 py-4">
        <h2 class="text-small font-semibold text-ink">寄信給 {{ candidateName }}</h2>
        <button
          class="ml-auto rounded-control p-1 text-ink-faint transition hover:bg-surface-2 hover:text-ink"
          @click="$emit('close')"
        >
          <X class="h-4 w-4" :stroke-width="2" />
        </button>
      </div>

      <div class="flex-1 overflow-y-auto px-5 py-4">
        <!-- Loading -->
        <div v-if="loading" class="flex items-center gap-3 py-10 text-ink-faint">
          <RefreshCw class="h-5 w-5 animate-spin" :stroke-width="1.5" />
          <span class="text-small">載入範本…</span>
        </div>

        <div v-else-if="error" class="py-6">
          <div class="text-small font-medium text-bad-ink">{{ error }}</div>
          <router-link
            v-if="noTemplates"
            to="/email-templates"
            class="mt-2 inline-block text-micro text-brand-ink hover:underline"
          >前往設定信件範本</router-link>
        </div>

        <template v-else>
          <!-- Template picker -->
          <div>
            <label class="mb-1.5 block text-micro font-medium text-ink-muted">信件範本</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="t in templates"
                :key="t.id"
                @click="selectTemplate(t.id)"
                :class="[
                  'rounded-full border px-3 py-1 text-micro font-medium transition',
                  t.id === selectedId
                    ? 'border-brand-line bg-brand-soft text-brand-ink'
                    : 'border-line text-ink-muted hover:border-line-strong hover:text-ink',
                ]"
              >{{ t.name }}</button>
            </div>
          </div>

          <!-- Warnings -->
          <div v-if="rendered?.missing_variables?.length" class="mt-4 rounded-control border border-warn-line bg-warn-soft px-3 py-2">
            <div class="text-micro font-semibold text-warn-ink">以下欄位沒有資料，信件中會是空白：</div>
            <div class="mt-1 text-micro text-warn-ink">
              {{ rendered.missing_variables.map(labelFor).join('、') }}
            </div>
          </div>
          <div v-if="rendered?.unknown_variables?.length" class="mt-2 rounded-control border border-bad-line bg-bad-soft px-3 py-2">
            <div class="text-micro font-semibold text-bad-ink">
              範本中有無法辨識的變數：{{ rendered.unknown_variables.join('、') }}
            </div>
          </div>

          <!-- Recipient -->
          <div class="mt-4">
            <label class="mb-1 block text-micro font-medium text-ink-muted">收件人</label>
            <div class="flex items-center gap-2">
              <span
                v-if="rendered?.to"
                class="flex-1 truncate rounded-control border border-line bg-surface-2 px-3 py-2 font-mono text-small text-ink"
              >{{ rendered.to }}</span>
              <span
                v-else
                class="flex-1 rounded-control border border-warn-line bg-warn-soft px-3 py-2 text-small text-warn-ink"
              >此候選人沒有 Email</span>
              <button
                v-if="rendered?.to"
                class="shrink-0 rounded-control border border-line px-3 py-2 text-micro font-medium text-ink-muted transition hover:border-line-strong hover:text-ink"
                @click="copy(rendered.to, 'to')"
              >{{ copied === 'to' ? '已複製' : '複製' }}</button>
            </div>
          </div>

          <!-- Subject -->
          <div class="mt-3">
            <label class="mb-1 block text-micro font-medium text-ink-muted">主旨</label>
            <div class="flex items-center gap-2">
              <input
                v-model="subject"
                class="flex-1 rounded-control border border-line bg-surface px-3 py-2 text-small text-ink focus:border-brand-line focus:outline-none"
              />
              <button
                class="shrink-0 rounded-control border border-line px-3 py-2 text-micro font-medium text-ink-muted transition hover:border-line-strong hover:text-ink"
                @click="copy(subject, 'subject')"
              >{{ copied === 'subject' ? '已複製' : '複製' }}</button>
            </div>
          </div>

          <!-- Body -->
          <div class="mt-3">
            <div class="mb-1 flex items-center gap-2">
              <label class="text-micro font-medium text-ink-muted">內文</label>
              <button
                class="ml-auto text-micro text-brand-ink hover:underline"
                @click="copy(body, 'body')"
              >{{ copied === 'body' ? '已複製內文' : '複製內文' }}</button>
            </div>
            <textarea
              v-model="body"
              rows="14"
              class="w-full resize-y rounded-control border border-line bg-surface px-3 py-2 text-small leading-relaxed text-ink focus:border-brand-line focus:outline-none"
            ></textarea>
            <p class="mt-1 text-micro text-ink-faint">
              可以直接在這裡修改，複製出去的是你修改後的版本。修改不會影響範本本身。
            </p>
          </div>
        </template>
      </div>

      <!-- Footer -->
      <div class="flex items-center gap-2 border-t border-line px-5 py-3">
        <router-link to="/email-templates" class="text-micro text-ink-faint hover:text-ink-muted hover:underline">
          編輯範本
        </router-link>
        <button
          class="ml-auto rounded-control border border-line px-3 py-1.5 text-small font-medium text-ink-muted transition hover:border-line-strong hover:text-ink"
          @click="$emit('close')"
        >關閉</button>
        <button
          :disabled="!rendered"
          class="rounded-control bg-brand px-4 py-1.5 text-small font-semibold text-white transition hover:bg-brand-hover disabled:opacity-50"
          @click="copyAll"
        >{{ copied === 'all' ? '已複製整封信' : '複製整封信' }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { fetchEmailTemplates, composeEmail } from '../api'
import { RefreshCw, X } from 'lucide-vue-next'

const props = defineProps({
  candidateId: { type: [String, Number], required: true },
  candidateName: { type: String, default: '' },
})
defineEmits(['close'])

const loading = ref(true)
const error = ref('')
const noTemplates = ref(false)
const templates = ref([])
const variables = ref([])
const selectedId = ref('')
const rendered = ref(null)

// Subject/body are local copies so the operator can tweak one letter without
// editing the template every other candidate will get.
const subject = ref('')
const body = ref('')
const copied = ref('')

const labelMap = computed(() =>
  Object.fromEntries(variables.value.map((v) => [v.key, v.label]))
)
function labelFor(key) {
  return labelMap.value[key] || key
}

async function selectTemplate(id) {
  selectedId.value = id
  try {
    const result = await composeEmail(props.candidateId, id)
    rendered.value = result
    subject.value = result.subject
    body.value = result.body
    error.value = ''
  } catch (e) {
    error.value = e.response?.data?.detail || e.response?.data?.error || '產生信件失敗'
  }
}

async function copy(text, key) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    // Clipboard API needs a secure context; the Electron build and plain http
    // dev server do not always have one.
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copied.value = key
  setTimeout(() => {
    if (copied.value === key) copied.value = ''
  }, 1600)
}

function copyAll() {
  copy(`${subject.value}\n\n${body.value}`, 'all')
}

onMounted(async () => {
  try {
    const data = await fetchEmailTemplates()
    templates.value = data.templates || []
    variables.value = data.variables || []
    if (!templates.value.length) {
      noTemplates.value = true
      error.value = '尚未設定任何信件範本。'
      return
    }
    await selectTemplate(templates.value[0].id)
  } catch (e) {
    error.value = e.response?.data?.detail || e.response?.data?.error || '載入範本失敗'
  } finally {
    loading.value = false
  }
})
</script>
