import { createRouter, createWebHistory } from 'vue-router'

export const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'player', component: () => import('./views/Player.vue') },
    { path: '/manage', name: 'manage', component: () => import('./views/Manage.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})
