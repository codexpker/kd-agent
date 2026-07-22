import { createRouter, createWebHistory } from 'vue-router'

import AssistantView from './views/AssistantView.vue'
import PaperReaderView from './views/PaperReaderView.vue'
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
    { path: '/papers/:paperId', name: 'paper-reader', component: PaperReaderView },
    { path: '/workspace', name: 'workspace', component: ResearchWorkspaceView },
    { path: '/opportunities', name: 'opportunities', component: ResearchWorkspaceView },
    { path: '/projects', name: 'projects', component: ResearchWorkspaceView },
    { path: '/papers', redirect: '/papers/anomaly-transformer-2022' },
    { path: '/experiments', redirect: { path: '/projects', hash: '#project-claim' } },
    { path: '/knowledge-graph', redirect: { name: 'paper-reader', params: { paperId: 'anomaly-transformer-2022' }, query: { tab: 'graph' } } },
  ],
})
