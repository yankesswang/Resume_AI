<template>
  <div class="flex min-h-dvh items-center justify-center bg-canvas px-6 py-12">
    <div class="w-full max-w-md">
      <div class="mb-8 flex flex-col items-center gap-3">
        <div class="flex h-12 w-12 items-center justify-center rounded-xl bg-brand shadow-sm">
          <FileText class="h-6 w-6 text-white" :stroke-width="2.5" />
        </div>
        <h1 class="text-title font-semibold tracking-tight text-ink">Resume AI</h1>
        <p class="text-small text-ink-muted">應徵者資料庫 · 需登入後使用</p>
      </div>

      <div class="card p-6">
        <div class="mb-5 flex gap-1 rounded-control bg-surface-2 p-1">
          <button
            class="flex-1 rounded-[4px] px-3 py-2 text-small font-medium transition-colors"
            :class="mode === 'login' ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink'"
            @click="switchMode('login')"
          >
            登入
          </button>
          <button
            v-if="registrationOpen"
            class="flex-1 rounded-[4px] px-3 py-2 text-small font-medium transition-colors"
            :class="mode === 'register' ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink'"
            @click="switchMode('register')"
          >
            申請帳號
          </button>
        </div>

        <!-- A fresh install with no root can accept registrations but can never
             approve them. Saying so here is the difference between "the system
             is being set up" and "my application was ignored". -->
        <div
          v-if="auth.config && auth.config.root_configured === false"
          class="mb-5 rounded-control border border-warn-line bg-warn-soft px-3 py-2.5 text-micro text-warn-ink"
        >
          系統尚未建立管理者帳號，目前無人能核准申請。請在伺服器上執行
          <code class="font-mono">python -m app.accounts_cli bootstrap-root</code>。
        </div>

        <form class="flex flex-col gap-4" @submit.prevent="submit">
          <label class="flex flex-col gap-1.5">
            <span class="text-micro font-medium text-ink-muted">公司電子郵件</span>
            <input
              v-model.trim="form.email"
              type="email"
              class="field"
              autocomplete="username"
              required
              placeholder="you@company.com"
            />
          </label>

          <label class="flex flex-col gap-1.5">
            <span class="text-micro font-medium text-ink-muted">密碼</span>
            <div class="field flex items-center gap-1 p-0 pl-3">
              <input
                v-model="form.password"
                :type="showPassword ? 'text' : 'password'"
                class="min-w-0 flex-1 border-0 bg-transparent py-2 text-small text-ink outline-none placeholder:text-ink-faint"
                :autocomplete="mode === 'login' ? 'current-password' : 'new-password'"
                required
                :placeholder="mode === 'register' ? passwordHint : ''"
              />
              <button
                type="button"
                class="mr-1 shrink-0 rounded-control p-1.5 text-ink-faint transition-colors hover:text-ink"
                :aria-label="showPassword ? '隱藏密碼' : '顯示密碼'"
                :aria-pressed="showPassword"
                :title="showPassword ? '隱藏密碼' : '顯示密碼'"
                @click="showPassword = !showPassword"
              >
                <EyeOff class="h-4.5 w-4.5" :stroke-width="1.75" v-if="showPassword" aria-hidden="true" />
                <Eye v-else class="h-4.5 w-4.5" :stroke-width="1.75" aria-hidden="true" />
              </button>
            </div>
          </label>

          <template v-if="mode === 'register'">
            <label class="flex flex-col gap-1.5">
              <span class="text-micro font-medium text-ink-muted">姓名</span>
              <input v-model.trim="form.display_name" type="text" class="field" required />
            </label>
            <div class="grid grid-cols-2 gap-3">
              <label class="flex flex-col gap-1.5">
                <span class="text-micro font-medium text-ink-muted">公司</span>
                <input v-model.trim="form.company" type="text" class="field" />
              </label>
              <label class="flex flex-col gap-1.5">
                <span class="text-micro font-medium text-ink-muted">部門</span>
                <input v-model.trim="form.department" type="text" class="field" />
              </label>
            </div>
            <label class="flex flex-col gap-1.5">
              <span class="text-micro font-medium text-ink-muted">申請用途</span>
              <textarea
                v-model.trim="form.requested_reason"
                class="field min-h-[4.5rem] resize-y"
                placeholder="例：負責 AI 工程師職缺的初步篩選"
              />
              <span class="text-micro text-ink-faint">
                管理者會依此決定你的權限與可見的個資範圍。
              </span>
            </label>
            <p v-if="domainHint" class="text-micro text-ink-faint">
              僅開放這些網域註冊：{{ domainHint }}
            </p>
          </template>

          <p
            v-if="error"
            class="rounded-control border border-danger-line bg-danger-soft px-3 py-2.5 text-micro text-danger-ink"
          >
            {{ error }}
          </p>

          <p
            v-if="notice"
            class="rounded-control border border-good-line bg-good-soft px-3 py-2.5 text-micro text-good-ink"
          >
            {{ notice }}
          </p>

          <button class="btn btn-primary w-full" type="submit" :disabled="busy">
            {{ busy ? '處理中…' : mode === 'login' ? '登入' : '送出申請' }}
          </button>
        </form>
      </div>

      <p v-if="mode === 'register'" class="mt-4 text-center text-micro text-ink-faint">
        送出後帳號為「待審核」，需由系統管理者核准才能存取應徵者資料。
      </p>
    </div>
  </div>
</template>

<script setup>
import { computed, reactive, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { Eye, EyeOff, FileText } from 'lucide-vue-next'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const mode = ref('login')
const busy = ref(false)
// Reset on mode switch / submit, so a revealed password is never left on
// screen for the next person at the keyboard.
const showPassword = ref(false)
const error = ref('')
const notice = ref('')

const form = reactive({
  email: '',
  password: '',
  display_name: '',
  company: '',
  department: '',
  requested_reason: '',
})

const registrationOpen = computed(() => auth.config?.registration_open !== false)
const domainHint = computed(() => (auth.config?.registration_domains || []).join('、'))
// Below 2 there is no rule worth stating, so the placeholder goes blank
// rather than telling people their password must be at least 1 character.
const passwordHint = computed(() => {
  const min = auth.config?.min_password_length ?? 0
  return min >= 2 ? `至少 ${min} 個字元` : ''
})

function switchMode(next) {
  mode.value = next
  error.value = ''
  notice.value = ''
  showPassword.value = false
}

// FastAPI puts validation errors in `detail`, which is a string for our own
// HTTPExceptions but a list of objects for request-schema failures. Rendering
// the raw value would show "[object Object]" to the user.
function messageFrom(err) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('；')
  if (err?.response?.status === 429) return '嘗試次數過多，請稍後再試。'
  return err?.message || '發生未知錯誤。'
}

async function submit() {
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    if (mode.value === 'login') {
      await auth.login(form.email, form.password)
      // Return to wherever the session expired, so an interrupted review
      // resumes where it left off instead of at the top of the list.
      router.replace(route.query.redirect || '/')
    } else {
      const result = await auth.register({
        email: form.email,
        password: form.password,
        display_name: form.display_name,
        company: form.company,
        department: form.department,
        requested_reason: form.requested_reason,
      })
      notice.value = result.message || '申請已送出，請等待核准。'
      mode.value = 'login'
      form.password = ''
      showPassword.value = false
    }
  } catch (err) {
    error.value = messageFrom(err)
  } finally {
    busy.value = false
  }
}
</script>
