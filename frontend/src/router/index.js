import { createRouter, createWebHistory } from 'vue-router'
import TaskCreate from '../views/TaskCreate.vue'
import TaskProgress from '../views/TaskProgress.vue'

const routes = [
  { path: '/', name: 'create', component: TaskCreate },
  { path: '/task/:id', name: 'progress', component: TaskProgress, props: true },
]

const router = createRouter({
  history: createWebHistory(),
  routes,
})

export default router
