<template>
  <!-- The login screen is its own full-page layout: rendering the nav around
       it would show a signed-out visitor the shape of a system they cannot
       use, and every link would bounce them straight back here. -->
  <router-view v-if="isBare" />

  <div v-else class="flex h-dvh flex-col overflow-hidden bg-canvas">
    <header class="flex h-16 shrink-0 items-center gap-7 border-b border-line bg-surface px-6">
      <router-link to="/" class="flex shrink-0 items-center gap-2.5 no-underline">
        <div class="flex h-8 w-8 items-center justify-center rounded-lg bg-brand shadow-sm">
          <FileText class="h-4.5 w-4.5 text-white" :stroke-width="2.5" />
        </div>
        <span class="text-title font-semibold tracking-tight text-ink">Resume AI</span>
      </router-link>

      <nav class="flex min-w-0 items-center gap-1 py-1">
        <router-link
          v-for="link in primaryLinks"
          :key="link.to"
          :to="link.to"
          class="relative flex min-h-10 shrink-0 items-center gap-1.5 rounded-control px-3 py-2 text-small font-medium no-underline transition-colors"
          :class="isActive(link)
            ? 'bg-surface-2 text-ink'
            : 'text-ink-muted hover:bg-surface-2 hover:text-ink'"
        >
          {{ link.label }}
          <span v-if="link.count" class="chip bg-warn-soft text-warn-ink border-warn-line">
            {{ link.count }}
          </span>
        </router-link>
      </nav>

      <div v-if="settingsLinks.length" ref="settingsRef" class="relative shrink-0">
        <button
          type="button"
          class="flex min-h-10 items-center gap-1.5 rounded-control px-3 py-2 text-small font-medium transition-colors"
          :class="settingsOpen || settingsActive
            ? 'bg-surface-2 text-ink'
            : 'text-ink-muted hover:bg-surface-2 hover:text-ink'"
          :aria-expanded="settingsOpen"
          aria-haspopup="menu"
          @click="settingsOpen = !settingsOpen"
        >
          <Settings class="h-4 w-4" :stroke-width="2" />
          設定
          <ChevronDown
            class="h-3.5 w-3.5 transition-transform"
            :class="settingsOpen ? 'rotate-180' : ''"
            :stroke-width="2"
          />
        </button>

        <div
          v-if="settingsOpen"
          role="menu"
          class="card absolute left-0 top-full z-50 mt-1.5 w-64 overflow-hidden bg-surface-3 p-1 shadow-lg"
        >
          <router-link
            v-for="link in settingsLinks"
            :key="link.to"
            :to="link.to"
            role="menuitem"
            class="flex items-start gap-2.5 rounded-control px-2.5 py-2 no-underline transition-colors"
            :class="isActive(link) ? 'bg-surface-2' : 'hover:bg-surface-2'"
          >
            <!-- The tick occupies its own fixed column so labels stay on a
                 single left edge whether or not a row is the active one. -->
            <Check
              class="mt-0.5 h-3.5 w-3.5 shrink-0 text-brand-ink"
              :class="isActive(link) ? '' : 'invisible'"
              :stroke-width="2.5"
            />
            <span class="min-w-0">
              <span class="block text-small font-medium text-ink">{{ link.label }}</span>
              <span class="block text-micro text-ink-faint">{{ link.hint }}</span>
            </span>
          </router-link>
        </div>
      </div>

      <div v-if="auth.authRequired && auth.user" class="ml-auto flex shrink-0 items-center gap-3">
        <!-- The current PII level is shown permanently, not tucked into a
             menu: a masked reviewer looking at "候選人 #42" needs to know the
             data is withheld from them, not missing from the resume. -->
        <span class="chip border-line bg-surface-2 text-ink-muted" :title="piiTitle">
          {{ auth.user.pii_label }}
        </span>
        <div class="text-right leading-tight">
          <p class="text-micro font-medium text-ink">{{ auth.user.display_name || auth.user.email }}</p>
          <p class="text-micro text-ink-faint">{{ auth.user.role_label }}</p>
        </div>
        <button class="btn btn-ghost px-2.5 py-1.5 text-micro" @click="logout">
          <LogOut class="h-3.5 w-3.5" :stroke-width="2" />
          登出
        </button>
      </div>
    </header>

    <main class="min-h-0 flex-1 overflow-hidden">
      <router-view v-slot="{ Component, route: r }">
        <keep-alive include="ListView">
          <component :is="Component" :key="r.path" />
        </keep-alive>
      </router-view>
    </main>
  </div>
</template>

<script setup>
import { computed, onMounted, onBeforeUnmount, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { FileText, Settings, Check, ChevronDown, LogOut } from 'lucide-vue-next'
import { useBookmarkStore } from './stores/bookmarks'
import { useAuthStore } from './stores/auth'
import { setUnauthorizedHandler } from './api'

const bookmarks = useBookmarkStore()
const auth = useAuthStore()
const route = useRoute()
const router = useRouter()

const isBare = computed(() => route.meta.public === true)

const piiTitle = computed(() => {
  const level = auth.piiLevel
  if (level === 'full') return '你可以看到完整的應徵者個人資料。'
  if (level === 'partial') return '姓名、聯絡方式與照片已部分遮罩。'
  return '應徵者的身分資訊已完全遮罩，僅顯示評分與經歷。'
})

// A 401 from anywhere in the app means the session died mid-use — expired, or
// revoked by root. Route to login from here rather than from the API module,
// which has no router access.
onMounted(() => {
  setUnauthorizedHandler(() => {
    auth.logout()
    if (route.meta.public !== true) {
      router.replace({ name: 'login', query: { redirect: route.fullPath } })
    }
  })
})

// Interface language is Chinese; only established technical terms stay English.
//
// The nav is split by *how often a link is used*, not by permission — though
// the two happen to coincide here. The six working surfaces are visited many
// times a day and stay on the bar; the four configuration screens are visited
// when something needs changing and live behind 設定.
//
// Previously all ten sat in one `overflow-x-auto` row. At common laptop widths
// the last few scrolled off the right edge with no scrollbar drawn, so 帳號管理
// was reachable only by dragging a nav bar most people never guess is
// draggable. A menu that is closed is still discoverable; a link pushed out of
// the viewport is not.
const primaryLinks = computed(() => {
  const all = [
    { to: '/', label: '人才庫', exact: true },
    { to: '/imports', label: '匯入紀錄' },
    { to: '/jobs', label: '職缺管理' },
    { to: '/bookmarks', label: '感興趣', exact: true, count: bookmarks.count },
    { to: '/calendar', label: '面試行事曆', exact: true },
  ]
  // Hiding a link the user cannot use is presentation only — the route guard
  // and the server both refuse the same navigation regardless.
  return all.filter((link) => !link.permission || auth.can(link.permission))
})

const settingsLinks = computed(() => {
  const all = [
    { to: '/scoring', label: '評分設定', hint: '權重、分級與學校分組', exact: true, permission: 'write:scoring' },
    { to: '/email-templates', label: '信件範本', hint: '邀約、婉謝與補件信', exact: true, permission: 'write:scoring' },
    { to: '/llm-settings', label: 'AI 模型', hint: '對話與嵌入模型供應商', exact: true, permission: 'write:scoring' },
    { to: '/users', label: '帳號管理', hint: '審核申請與權限分級', exact: true, permission: 'admin:users' },
  ]
  return all.filter((link) => !link.permission || auth.can(link.permission))
})

function isActive(link) {
  return link.exact ? route.path === link.to : route.path.startsWith(link.to)
}

// Highlights the 設定 trigger while any screen behind it is open, so the menu
// still reports where you are once it has closed.
const settingsActive = computed(() => settingsLinks.value.some(isActive))

const settingsOpen = ref(false)
const settingsRef = ref(null)

function closeSettings() {
  settingsOpen.value = false
}

// A menu that only closes on its own trigger strands itself open the moment
// attention moves elsewhere. Escape and outside-click are the two exits people
// try without being told.
function onDocumentPointerDown(e) {
  if (settingsRef.value && !settingsRef.value.contains(e.target)) closeSettings()
}

function onDocumentKeydown(e) {
  if (e.key === 'Escape') closeSettings()
}

onMounted(() => {
  document.addEventListener('pointerdown', onDocumentPointerDown)
  document.addEventListener('keydown', onDocumentKeydown)
})

onBeforeUnmount(() => {
  document.removeEventListener('pointerdown', onDocumentPointerDown)
  document.removeEventListener('keydown', onDocumentKeydown)
})

// Navigating from inside the menu must dismiss it; the route changes under it
// otherwise and it hangs over the new page.
watch(() => route.path, closeSettings)

function logout() {
  auth.logout()
  router.replace({ name: 'login' })
}
</script>
