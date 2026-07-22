<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import DemoGuide from './components/DemoGuide.vue'

const route = useRoute()
const apiReady = ref(false)
const readinessMode = ref<'offline_demo' | 'local_infrastructure' | null>(null)
const readinessStatus = ref<'ready' | 'degraded' | 'blocked' | null>(null)
const formalChainStatus = ref<'blocked_external_configuration' | 'configured_unverified' | 'verified' | null>(null)
const paperMode = computed(() => route.path.startsWith('/papers/'))
const runtimeLabel = computed(() => {
  if (!apiReady.value) return 'API 未连接'
  if (readinessMode.value === null) return 'API 在线 · 链路状态未知'
  if (formalChainStatus.value === 'verified') return '讯飞正式链路 · 已核验'
  if (formalChainStatus.value === 'configured_unverified') return '讯飞链路已配置 · 待真实核验'
  if (readinessMode.value === 'local_infrastructure') {
    return readinessStatus.value === 'ready' ? '本地证据可用 · 讯飞链路未接入' : '本地基础设施待修复 · 讯飞链路未接入'
  }
  return '本地演示可用 · 讯飞链路未接入'
})

const sectionLabel = computed(() => {
  if (route.path === '/assistant') return '论文逆向工程'
  if (route.path === '/opportunities') return '领域进展地图'
  if (route.path === '/projects') return '我的研究教练'
  if (route.path.startsWith('/papers') && route.query.tab === 'graph') return '论文证据关系'
  if (route.path.startsWith('/papers')) return '论文逆向工程'
  if (route.path === '/workspace') return '开发与审核工作区'
  return 'KD Agent'
})

onMounted(async () => {
  try {
    const response = await fetch('/api/v1/healthz')
    apiReady.value = response.ok
    if (response.ok) {
      const readinessResponse = await fetch('/api/v1/demo/readiness')
      if (readinessResponse.ok) {
        const readiness = await readinessResponse.json() as {
          runtime_mode: 'offline_demo' | 'local_infrastructure'
          status: 'ready' | 'degraded' | 'blocked'
          formal_chain_status: 'blocked_external_configuration' | 'configured_unverified' | 'verified'
        }
        readinessMode.value = readiness.runtime_mode
        readinessStatus.value = readiness.status
        formalChainStatus.value = readiness.formal_chain_status
      }
    }
  } catch {
    apiReady.value = false
  }
})
</script>

<template>
  <div class="app-shell" :class="{ 'paper-mode': paperMode }">
    <aside class="app-sidebar">
      <RouterLink class="app-brand" to="/assistant">
        <span class="brand-mark">KD</span>
        <span><b>Agent</b><small>科研证据工作台</small></span>
      </RouterLink>

      <nav aria-label="产品导航">
        <p>三个核心工作台</p>
        <RouterLink to="/assistant"><span>01</span>论文逆向工程</RouterLink>
        <RouterLink to="/opportunities#opportunities"><span>02</span>领域进展地图</RouterLink>
        <RouterLink to="/projects#project-claim"><span>03</span>我的研究教练</RouterLink>
        <p>证据与开发审核</p>
        <RouterLink to="/papers"><span>04</span>原文证据核验</RouterLink>
        <RouterLink to="/workspace"><span>05</span>开发审计</RouterLink>
      </nav>

      <section class="integrity-card">
        <b>科研诚信边界</b>
        <p>Candidate ≠ confirmed innovation</p>
        <p>未核验证据不会冒充论文事实。</p>
      </section>
    </aside>

    <section class="app-stage">
      <header class="app-header">
        <div><span>当前空间</span><b>{{ sectionLabel }}</b></div>
        <div class="header-actions">
          <DemoGuide />
          <div class="runtime-status" :class="{ offline: !apiReady, warning: apiReady && (readinessStatus !== 'ready' || formalChainStatus !== 'verified') }">
            <i></i>{{ runtimeLabel }}
          </div>
        </div>
      </header>
      <div class="app-content"><RouterView /></div>
    </section>
  </div>
</template>

<style scoped>
.app-shell { min-height: 100vh; display: grid; grid-template-columns: 244px minmax(0, 1fr); background: #f4f6f3; }
.app-sidebar { position: sticky; top: 0; height: 100vh; display: flex; flex-direction: column; padding: 24px 18px; border-right: 1px solid #dfe4df; background: #fbfcfa; z-index: 20; }
.app-brand { display: flex; gap: 11px; align-items: center; padding: 4px 7px 26px; color: #14251d; text-decoration: none; }
.brand-mark { display: grid; place-items: center; width: 43px; height: 43px; border-radius: 13px; background: #205c45; color: #dfff43; font-weight: 900; }
.app-brand > span:last-child { display: grid; }.app-brand b { font-size: 20px; }.app-brand small { color: #7a887f; font-size: 10px; }
.app-sidebar nav { display: grid; gap: 5px; }.app-sidebar nav p { margin: 20px 10px 8px; color: #9aa59f; font-size: 10px; font-weight: 800; letter-spacing: 1.5px; }
.app-sidebar nav a { display: flex; gap: 11px; align-items: center; padding: 11px 12px; border-radius: 10px; color: #55645c; text-decoration: none; font-size: 13px; font-weight: 700; }
.app-sidebar nav a span { color: #9da8a2; font-size: 10px; }.app-sidebar nav a:hover { background: #eef2ee; }.app-sidebar nav a.router-link-active { background: #dfeee6; color: #174c38; }.app-sidebar nav a.router-link-active span { color: #ef683e; }
.integrity-card { margin-top: auto; padding: 15px; border: 1px solid #dfe4df; border-radius: 13px; background: #f1f4ef; }.integrity-card b { font-size: 11px; }.integrity-card p { margin: 7px 0 0; color: #6f7d75; font-size: 10px; line-height: 1.45; }
.app-stage { min-width: 0; }.app-header { height: 66px; display: flex; justify-content: space-between; align-items: center; padding: 0 28px; border-bottom: 1px solid #dfe4df; background: rgba(251, 252, 250, .94); position: sticky; top: 0; z-index: 15; backdrop-filter: blur(12px); }.app-header > div:first-child { display: grid; }.app-header span { color: #8a968f; font-size: 9px; letter-spacing: 1.3px; }.app-header b { margin-top: 2px; font-size: 14px; }.runtime-status { padding: 7px 10px; border: 1px solid #c8d5cd; border-radius: 99px; color: #52645a; font-size: 10px; }.runtime-status i { display: inline-block; width: 7px; height: 7px; margin-right: 6px; border-radius: 50%; background: #47a76b; }.runtime-status.warning i { background: #d69227; }.runtime-status.offline i { background: #e06c47; }
.header-actions { display: flex; gap: 8px; align-items: center; }
.app-content { min-width: 0; }
.app-shell.paper-mode { grid-template-columns: 76px minmax(0, 1fr); }
.paper-mode .app-sidebar { padding: 18px 9px; }
.paper-mode .app-brand { justify-content: center; padding-inline: 0; }
.paper-mode .app-brand > span:last-child { display: none; }
.paper-mode .app-sidebar nav p, .paper-mode .app-sidebar nav a { font-size: 0; }
.paper-mode .app-sidebar nav a { justify-content: center; }
.paper-mode .app-sidebar nav a span { font-size: 10px; }
.paper-mode .integrity-card { display: none; }
@media (max-width: 900px) { .app-shell { grid-template-columns: 76px minmax(0, 1fr); }.app-sidebar { padding: 18px 9px; }.app-brand > span:last-child, .app-sidebar nav p, .app-sidebar nav a:not(.router-link-active) { font-size: 0; }.app-sidebar nav a { justify-content: center; }.app-sidebar nav a span { font-size: 10px; }.integrity-card { display: none; } }
@media (max-width: 640px) { .app-shell { display: block; }.app-sidebar { position: static; width: 100%; height: auto; flex-direction: row; padding: 8px; overflow-x: auto; }.app-brand, .integrity-card, .app-sidebar nav p { display: none; }.app-sidebar nav { display: flex; }.app-sidebar nav a { white-space: nowrap; font-size: 11px !important; }.app-header { top: 0; padding: 0 15px; } }
</style>
