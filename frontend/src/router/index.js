import { createRouter, createWebHashHistory } from 'vue-router'
import ListView from '../views/ListView.vue'
import DetailView from '../views/DetailView.vue'

const routes = [
  { path: '/', name: 'list', component: ListView },
  { path: '/candidate/:id', name: 'detail', component: DetailView, props: true },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
  scrollBehavior(to, from, savedPosition) {
    if (savedPosition) return savedPosition
    return { top: 0 }
  },
})
