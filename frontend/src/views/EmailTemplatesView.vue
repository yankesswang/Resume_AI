<template>
  <div class="h-full overflow-y-auto">
    <div class="mx-auto max-w-5xl px-6 py-8">
      <div class="mb-6 flex items-start gap-3">
        <div>
          <h1 class="text-display font-bold text-ink">信件範本</h1>
          <p class="mt-1 text-small text-ink-muted">
            設定寄給候選人的信件格式。系統不會替你寄信 —— 它把變數填好，你複製到公司信箱送出。
          </p>
        </div>
        <div class="ml-auto flex shrink-0 items-center gap-2">
          <button
            class="rounded-control border border-line px-3 py-1.5 text-small font-medium text-ink-muted transition hover:border-line-strong hover:text-ink"
            @click="doReset"
            :disabled="saving"
          >回復預設</button>
          <button
            class="rounded-control bg-brand px-4 py-1.5 text-small font-semibold text-white transition hover:bg-brand-hover disabled:opacity-50"
            @click="doSave"
            :disabled="saving"
          >{{ saving ? '儲存中…' : '儲存' }}</button>
        </div>
      </div>

      <div v-if="message" :class="[
        'mb-4 rounded-control border px-3 py-2 text-small',
        messageOk ? 'border-good-line bg-good-soft text-good-ink' : 'border-bad-line bg-bad-soft text-bad-ink',
      ]">{{ message }}</div>

      <div v-if="loading" class="py-10 text-small text-ink-faint">載入中…</div>

      <template v-else>
        <!-- Sender block: shared by every template -->
        <SectionCard title="寄件人資訊">
          <p class="mb-3 text-micro text-ink-muted">
            填一次，所有範本共用。對應 <code class="rounded bg-surface-2 px-1 font-mono">{{ ph('company') }}</code>、<code class="rounded bg-surface-2 px-1 font-mono">{{ ph('sender_name') }}</code> 等變數。
          </p>
          <div class="grid gap-3 sm:grid-cols-2">
            <div v-for="f in senderFields" :key="f.key">
              <label class="mb-1 block text-micro font-medium text-ink-muted">{{ f.label }}</label>
              <input
                v-model="sender[f.key]"
                :placeholder="f.placeholder"
                class="w-full rounded-control border border-line bg-surface px-3 py-2 text-small text-ink focus:border-brand-line focus:outline-none"
              />
            </div>
          </div>
        </SectionCard>

        <!-- Variable reference -->
        <SectionCard title="可用變數">
          <p class="mb-3 text-micro text-ink-muted">
            點一下複製，貼進主旨或內文。找不到資料的變數會留白；打錯的變數會在信件裡顯示成
            <code class="rounded bg-surface-2 px-1 font-mono">⟨未知變數: xxx⟩</code>，不會默默消失。
          </p>
          <div class="flex flex-wrap gap-1.5">
            <button
              v-for="v in variables"
              :key="v.key"
              @click="copyVar(v.key)"
              class="rounded-full border border-line bg-surface-2 px-2.5 py-1 text-micro text-ink-muted transition hover:border-brand-line hover:text-brand-ink"
              :title="`複製 ${ph(v.key)}`"
            >
              <span class="font-mono">{{ ph(v.key) }}</span>
              <span class="ml-1 text-ink-faint">{{ v.label }}</span>
              <span v-if="copiedVar === v.key" class="ml-1 text-good-ink">已複製</span>
            </button>
          </div>
        </SectionCard>

        <!-- Templates -->
        <SectionCard title="範本">
          <div v-if="!templates.length" class="py-3 text-small text-ink-faint">
            還沒有任何範本。
          </div>

          <div
            v-for="(t, idx) in templates"
            :key="t.id"
            class="mb-4 rounded-control border border-line bg-surface-2 p-4 last:mb-0"
          >
            <div class="mb-3 flex items-center gap-2">
              <input
                v-model="t.name"
                placeholder="範本名稱"
                class="flex-1 rounded-control border border-line bg-surface px-3 py-1.5 text-small font-semibold text-ink focus:border-brand-line focus:outline-none"
              />
              <button
                class="shrink-0 rounded-control border border-line px-2.5 py-1.5 text-micro text-ink-faint transition hover:border-bad-line hover:text-bad-ink"
                @click="removeTemplate(idx)"
              >刪除</button>
            </div>

            <label class="mb-1 block text-micro font-medium text-ink-muted">主旨</label>
            <input
              v-model="t.subject"
              class="mb-3 w-full rounded-control border border-line bg-surface px-3 py-2 text-small text-ink focus:border-brand-line focus:outline-none"
            />

            <label class="mb-1 block text-micro font-medium text-ink-muted">內文</label>
            <textarea
              v-model="t.body"
              rows="12"
              class="w-full resize-y rounded-control border border-line bg-surface px-3 py-2 font-sans text-small leading-relaxed text-ink focus:border-brand-line focus:outline-none"
            ></textarea>

            <div v-if="unknownIn(t).length" class="mt-2 text-micro text-bad-ink">
              無法辨識的變數：{{ unknownIn(t).join('、') }}
            </div>
          </div>

          <button
            class="mt-2 rounded-control border border-line px-3 py-1.5 text-small font-medium text-ink-muted transition hover:border-line-strong hover:text-ink"
            @click="addTemplate"
          >+ 新增範本</button>
        </SectionCard>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { fetchEmailTemplates, saveEmailTemplates, resetEmailTemplates } from '../api'
import SectionCard from '../components/SectionCard.vue'

const loading = ref(true)
const saving = ref(false)
const message = ref('')
const messageOk = ref(true)
const copiedVar = ref('')

const templates = ref([])
const variables = ref([])
const sender = ref({
  company: '',
  sender_name: '',
  sender_title: '',
  sender_email: '',
  sender_phone: '',
})

const senderFields = [
  { key: 'company', label: '公司名稱', placeholder: '例：宏碁股份有限公司' },
  { key: 'sender_name', label: '寄件人姓名', placeholder: '例：陳小華' },
  { key: 'sender_title', label: '寄件人職稱', placeholder: '例：人資專員' },
  { key: 'sender_email', label: '寄件人 Email', placeholder: 'hr@example.com' },
  { key: 'sender_phone', label: '寄件人電話', placeholder: '02-1234-5678' },
]

// Built rather than written literally: a `{{...}}` inside the template markup
// would be parsed as an interpolation and break the build.
const OPEN = '{' + '{'
const CLOSE = '}' + '}'
function ph(key) {
  return OPEN + key + CLOSE
}

// Mirrors the server's placeholder regex so the warning shows while typing,
// without a round trip. The server re-checks on save.
const PLACEHOLDER = /\{\{\s*([a-z0-9_]+)\s*\}\}/gi

function unknownIn(t) {
  const known = new Set(variables.value.map((v) => v.key))
  const found = new Set()
  for (const m of `${t.subject}\n${t.body}`.matchAll(PLACEHOLDER)) {
    const key = m[1].toLowerCase()
    if (!known.has(key)) found.add(key)
  }
  return [...found].sort()
}

function addTemplate() {
  templates.value.push({
    id: `t${Date.now().toString(36)}`,
    name: '新範本',
    subject: '',
    body: '',
  })
}

function removeTemplate(idx) {
  templates.value.splice(idx, 1)
}

async function copyVar(key) {
  const text = ph(key)
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    const ta = document.createElement('textarea')
    ta.value = text
    document.body.appendChild(ta)
    ta.select()
    document.execCommand('copy')
    document.body.removeChild(ta)
  }
  copiedVar.value = key
  setTimeout(() => {
    if (copiedVar.value === key) copiedVar.value = ''
  }, 1200)
}

function show(text, ok) {
  message.value = text
  messageOk.value = ok
  setTimeout(() => { message.value = '' }, 4000)
}

function apply(data) {
  templates.value = data.templates || []
  sender.value = { ...sender.value, ...(data.sender || {}) }
  if (data.variables) variables.value = data.variables
}

async function doSave() {
  saving.value = true
  try {
    const data = await saveEmailTemplates(templates.value, sender.value)
    if (data.saved === false || data.error) {
      show(data.error || '儲存失敗', false)
    } else {
      apply(data)
      show('已儲存', true)
    }
  } catch (e) {
    show(e.response?.data?.error || e.response?.data?.detail || '儲存失敗', false)
  } finally {
    saving.value = false
  }
}

async function doReset() {
  if (!confirm('確定要回復預設範本嗎？目前的範本會被覆蓋。')) return
  saving.value = true
  try {
    apply(await resetEmailTemplates())
    show('已回復預設範本', true)
  } catch (e) {
    show(e.response?.data?.error || '回復失敗', false)
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  try {
    apply(await fetchEmailTemplates())
  } catch (e) {
    show('載入失敗', false)
  } finally {
    loading.value = false
  }
})
</script>
