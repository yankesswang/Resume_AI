import { createRouter, createWebHistory } from 'vue-router'
import ListView from '../views/ListView.vue'
import DetailView from '../views/DetailView.vue'
import BookmarksView from '../views/BookmarksView.vue'
import CalendarView from '../views/CalendarView.vue'

const routes = [
  { path: '/', name: 'list', component: ListView },
  {
    path: '/unique',
    name: 'unique',
    component: ListView,
    props: { scope: 'unique', title: 'Unique Candidates' },
  },
  { path: '/candidate/:id', name: 'detail', component: DetailView, props: true },
  { path: '/bookmarks', name: 'bookmarks', component: BookmarksView },
  { path: '/calendar', name: 'calendar', component: CalendarView },
]

export default createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})
