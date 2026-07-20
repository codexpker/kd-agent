import { createRouter, createWebHistory } from 'vue-router'

import AssistantView from './views/AssistantView.vue'
import ResearchWorkspaceView from './views/ResearchWorkspaceView.vue'

export const router = createRouter({
  history: createWebHistory(),
  scrollBehavior(to) {
    if (to.hash) return { el: to.hash, behavior: 'smooth', top: 76 }
    return { top: 0 }
  },
  routes: [
    { path: '/', redirect: '/assistant' },
    { path: '/assistant', name: 'assistant', component: AssistantView },
    { path: '/workspace', name: 'workspace', component: ResearchWorkspaceView },
    { path: '/papers', redirect: { path: '/workspace', hash: '#papers' } },
    { path: '/opportunities', redirect: { path: '/workspace', hash: '#opportunities' } },
    { path: '/projects', redirect: { path: '/workspace', hash: '#project-claim' } },
    { path: '/experiments', redirect: { path: '/workspace', hash: '#project-claim' } },
    { path: '/knowledge-graph', redirect: { path: '/assistant', query: { panel: 'graph' } } },
  ],
})
