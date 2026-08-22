<template>
  <div class="h-full overflow-y-auto px-6 py-6">
    <div class="mx-auto max-w-5xl">
      <header class="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 class="text-title font-semibold tracking-tight text-ink">帳號與權限</h1>
          <p class="mt-1 text-small text-ink-muted">
            核准新帳號、指派角色與可見的個資範圍。只有 root 能執行這些操作。
          </p>
        </div>
        <div class="flex gap-1 rounded-control bg-surface-2 p-1">
          <button
            v-for="tab in tabs"
            :key="tab.value"
            class="rounded-[4px] px-3 py-1.5 text-small font-medium transition-colors"
            :class="filter === tab.value ? 'bg-surface text-ink shadow-sm' : 'text-ink-muted hover:text-ink'"
            @click="filter = tab.value"
          >
            {{ tab.label }}
            <span v-if="counts[tab.value]" class="ml-1 text-ink-faint">{{ counts[tab.value] }}</span>
          </button>
        </div>
      </header>

      <p v-if="error" class="mb-4 rounded-control border border-danger-line bg-danger-soft px-3 py-2.5 text-micro text-danger-ink">
        {{ error }}
      </p>

      <!-- The pending queue leads, because it is the only part of this page
           that represents someone waiting on a person. -->
      <section v-if="pending.length" class="mb-8">
        <h2 class="mb-3 text-small font-semibold text-ink">
          待審核
          <span class="chip ml-1.5 border-warn-line bg-warn-soft text-warn-ink">{{ pending.length }}</span>
        </h2>
        <div class="flex flex-col gap-3">
          <article v-for="u in pending" :key="u.id" class="card p-4">
            <div class="mb-4 flex flex-wrap items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-body font-medium text-ink">
                  {{ u.display_name || u.email }}
                </p>
                <p class="text-micro text-ink-muted">{{ u.email }}</p>
                <p v-if="u.company || u.department" class="mt-1 text-micro text-ink-faint">
                  {{ [u.company, u.department].filter(Boolean).join(' · ') }}
                </p>
              </div>
              <p class="text-micro text-ink-faint">{{ formatDate(u.created_at) }}</p>
            </div>

            <p v-if="u.requested_reason" class="mb-4 rounded-control bg-surface-2 px-3 py-2 text-micro text-ink-muted">
              「{{ u.requested_reason }}」
            </p>

            <div class="flex flex-wrap items-end gap-3">
              <label class="flex min-w-[9rem] flex-1 flex-col gap-1.5">
                <span class="text-micro font-medium text-ink-muted">角色</span>
                <select v-model="draft[u.id].role" class="field" @change="syncPii(u.id)">
                  <option v-for="r in assignableRoles" :key="r.value" :value="r.value">
                    {{ r.label }}
                  </option>
                </select>
              </label>
              <label class="flex min-w-[11rem] flex-1 flex-col gap-1.5">
                <span class="text-micro font-medium text-ink-muted">個資可見範圍</span>
                <select v-model="draft[u.id].piiLevel" class="field">
                  <option v-for="p in piiLevels" :key="p.value" :value="p.value">
                    {{ p.label }}
                  </option>
                </select>
              </label>
              <div class="flex gap-2">
                <button class="btn btn-primary" :disabled="busy === u.id" @click="approve(u)">
                  核准
                </button>
                <button class="btn btn-ghost" :disabled="busy === u.id" @click="reject(u)">
                  拒絕
                </button>
              </div>
            </div>

            <p class="mt-3 text-micro text-ink-faint">
              {{ permissionSummary(draft[u.id].role) }}
            </p>
          </article>
        </div>
      </section>

      <section>
        <h2 class="mb-3 text-small font-semibold text-ink">
          {{ filter === 'all' ? '所有帳號' : tabLabel }}
        </h2>

        <div v-if="loading" class="text-small text-ink-muted">載入中…</div>
        <div v-else-if="!visible.length" class="card p-8 text-center text-small text-ink-muted">
          沒有符合的帳號。
        </div>

        <div v-else class="card overflow-x-auto">
          <table class="w-full min-w-[46rem] border-collapse text-small">
            <thead>
              <tr class="border-b border-line text-left text-micro text-ink-muted">
                <th class="px-4 py-3 font-medium">使用者</th>
                <th class="px-4 py-3 font-medium">狀態</th>
                <th class="px-4 py-3 font-medium">角色</th>
                <th class="px-4 py-3 font-medium">個資範圍</th>
                <th class="px-4 py-3 font-medium">最後登入</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="u in visible" :key="u.id" class="border-b border-line last:border-0">
                <td class="px-4 py-3">
                  <p class="font-medium text-ink">{{ u.display_name || '—' }}</p>
                  <p class="text-micro text-ink-muted">{{ u.email }}</p>
                </td>
                <td class="px-4 py-3">
                  <span class="chip" :class="statusClass(u.status)">{{ statusLabel(u.status) }}</span>
                </td>
                <td class="px-4 py-3">
                  <select
                    :value="u.role"
                    class="field py-1.5 text-micro"
                    :disabled="u.status !== 'active' || busy === u.id"
                    @change="changeRole(u, $event.target.value)"
                  >
                    <option v-for="r in roles" :key="r.value" :value="r.value">{{ r.label }}</option>
                  </select>
                </td>
                <td class="px-4 py-3">
                  <select
                    :value="u.pii_level"
                    class="field py-1.5 text-micro"
                    :disabled="u.status !== 'active' || busy === u.id"
                    @change="changePii(u, $event.target.value)"
                  >
                    <option v-for="p in piiLevels" :key="p.value" :value="p.value">{{ p.label }}</option>
                  </select>
                </td>
                <td class="px-4 py-3 text-micro text-ink-faint">
                  {{ u.last_login_at ? formatDate(u.last_login_at) : '從未登入' }}
                </td>
              </tr>
            </tbody>
          </table>
        </div>

        <p class="mt-3 text-micro text-ink-faint">
          變更角色或狀態會立即失效該使用者目前的登入工作階段，需重新登入。
        </p>
      </section>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import {
  approveUser,
  authConfig,
  fetchUsers,
  rejectUser,
  updateUserGrade,
} from '../api'

const users = ref([])
const counts = ref({})
const config = ref(null)
const loading = ref(true)
const busy = ref(null)
const error = ref('')
const filter = ref('pending')

const draft = reactive({})

const tabs = [
  { value: 'pending', label: '待審核' },
  { value: 'active', label: '已啟用' },
  { value: 'suspended', label: '已停用' },
  { value: 'all', label: '全部' },
]

const roles = computed(() => config.value?.roles || [])
// root is granted by promoting an existing active account, never at approval
// time — the backend refuses it, so offering it here would only produce an
// error the operator cannot act on.
const assignableRoles = computed(() => roles.value.filter((r) => r.value !== 'root'))
const piiLevels = computed(() => config.value?.pii_levels || [])

const pending = computed(() => users.value.filter((u) => u.status === 'pending'))
const visible = computed(() =>
  filter.value === 'all' ? users.value : users.value.filter((u) => u.status === filter.value),
)
const tabLabel = computed(() => tabs.find((t) => t.value === filter.value)?.label || '')

watch(pending, (list) => {
  for (const u of list) {
    if (!draft[u.id]) {
      const fallback = roles.value.find((r) => r.value === 'viewer')
      draft[u.id] = {
        role: 'viewer',
        piiLevel: fallback?.default_pii_level || 'masked',
      }
    }
  }
}, { immediate: true })

function syncPii(id) {
  // Follow the role's recommended level when the role changes, so the common
  // case needs one choice rather than two — while leaving the field editable,
  // because the two axes are genuinely independent.
  const role = roles.value.find((r) => r.value === draft[id].role)
  if (role) draft[id].piiLevel = role.default_pii_level
}

function permissionSummary(roleValue) {
  const role = roles.value.find((r) => r.value === roleValue)
  if (!role) return ''
  return `可執行：${role.permissions.join('、')}`
}

function statusLabel(status) {
  return {
    pending: '待審核',
    active: '已啟用',
    suspended: '已停用',
    rejected: '已拒絕',
  }[status] || status
}

function statusClass(status) {
  return {
    pending: 'border-warn-line bg-warn-soft text-warn-ink',
    active: 'border-good-line bg-good-soft text-good-ink',
    suspended: 'border-danger-line bg-danger-soft text-danger-ink',
    rejected: 'border-line bg-surface-2 text-ink-muted',
  }[status] || 'border-line bg-surface-2 text-ink-muted'
}

function formatDate(value) {
  if (!value) return '—'
  const d = new Date(value)
  return Number.isNaN(d.getTime()) ? value : d.toLocaleString('zh-TW', { hour12: false })
}

function messageFrom(err) {
  const detail = err?.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) return detail.map((d) => d.msg).join('；')
  return err?.message || '操作失敗。'
}

async function load() {
  loading.value = true
  error.value = ''
  try {
    const [data, cfg] = await Promise.all([fetchUsers(), config.value ? null : authConfig()])
    users.value = data.users
    counts.value = { ...data.counts, all: data.users.length }
    if (cfg) config.value = cfg
  } catch (err) {
    error.value = messageFrom(err)
  } finally {
    loading.value = false
  }
}

async function approve(u) {
  busy.value = u.id
  error.value = ''
  try {
    await approveUser(u.id, { role: draft[u.id].role, piiLevel: draft[u.id].piiLevel })
    await load()
  } catch (err) {
    error.value = messageFrom(err)
  } finally {
    busy.value = null
  }
}

async function reject(u) {
  if (!window.confirm(`確定拒絕 ${u.email} 的申請？`)) return
  busy.value = u.id
  error.value = ''
  try {
    await rejectUser(u.id)
    await load()
  } catch (err) {
    error.value = messageFrom(err)
  } finally {
    busy.value = null
  }
}

async function changeRole(u, role) {
  busy.value = u.id
  error.value = ''
  try {
    await updateUserGrade(u.id, { role })
    await load()
  } catch (err) {
    error.value = messageFrom(err)
    await load() // reset the select to the value the server actually holds
  } finally {
    busy.value = null
  }
}

async function changePii(u, piiLevel) {
  busy.value = u.id
  error.value = ''
  try {
    await updateUserGrade(u.id, { piiLevel })
    await load()
  } catch (err) {
    error.value = messageFrom(err)
    await load()
  } finally {
    busy.value = null
  }
}

onMounted(load)
</script>
