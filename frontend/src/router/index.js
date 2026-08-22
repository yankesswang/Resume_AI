import { createRouter, createWebHistory } from 'vue-router'
import ListView from '../views/ListView.vue'
import DetailView from '../views/DetailView.vue'
import BookmarksView from '../views/BookmarksView.vue'
import CalendarView from '../views/CalendarView.vue'
import ImportsView from '../views/ImportsView.vue'
import ImportDetailView from '../views/ImportDetailView.vue'
import ScoringSettingsView from '../views/ScoringSettingsView.vue'
import LLMSettingsView from '../views/LLMSettingsView.vue'
import EmailTemplatesView from '../views/EmailTemplatesView.vue'
import JobPostingsView from '../views/JobPostingsView.vue'
import JobProfileView from '../views/JobProfileView.vue'
import LoginView from '../views/LoginView.vue'
import UsersView from '../views/UsersView.vue'
import { useAuthStore } from '../stores/auth'

const routes = [
  { path: '/', name: 'list', component: ListView },
  // 去重名單 was this same ListView with `scope: 'unique'` pinned — one value of
  // the 去重 filter promoted to its own nav entry, and a weaker one (it could
  // not switch to duplicate/review, and hid the upload/rescore buttons). The
  // filter does the whole job, so the page is gone; the path redirects rather
  // than 404s, since it was linkable and bookmarkable.
  { path: '/unique', redirect: { name: 'list', query: { dedupe: 'unique' } } },
  { path: '/imports', name: 'imports', component: ImportsView },
  { path: '/imports/:id', name: 'import-detail', component: ImportDetailView, props: true },
  { path: '/candidate/:id', name: 'detail', component: DetailView, props: true },
  { path: '/bookmarks', name: 'bookmarks', component: BookmarksView },
  { path: '/calendar', name: 'calendar', component: CalendarView },
  { path: '/jobs', name: 'jobs', component: JobPostingsView },
  { path: '/jobs/:id', name: 'job-profile', component: JobProfileView, props: true },
  { path: '/scoring', name: 'scoring', component: ScoringSettingsView },
  {
    path: '/llm-settings',
    name: 'llm-settings',
    component: LLMSettingsView,
    meta: { permission: 'write:scoring' },
  },
  { path: '/email-templates', name: 'email-templates', component: EmailTemplatesView },
  // `public: true` is the exception, not the rule: a new route added without
  // any meta is protected by default rather than silently shipping open.
  { path: '/login', name: 'login', component: LoginView, meta: { public: true } },
  { path: '/users', name: 'users', component: UsersView, meta: { permission: 'admin:users' } },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})

router.beforeEach(async (to) => {
  const auth = useAuthStore()
  // First navigation of the session: resolve whether auth is even on, and
  // whether the stored token is still good, before deciding anything.
  if (!auth.ready) await auth.init()

  if (!auth.authRequired) return true
  if (to.meta.public) {
    return auth.isAuthenticated ? { name: 'list' } : true
  }
  if (!auth.isAuthenticated) {
    // Carry the destination so login returns the user to the page they were
    // trying to reach, not to the top of the list.
    return { name: 'login', query: to.fullPath === '/' ? {} : { redirect: to.fullPath } }
  }
  // This guard is a UI courtesy, not the enforcement: the server rejects the
  // same request regardless of what the client chooses to render.
  if (to.meta.permission && !auth.can(to.meta.permission)) {
    return { name: 'list' }
  }
  return true
})

export default router
