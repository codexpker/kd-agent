<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

type ReadinessStatus = 'ready' | 'degraded' | 'blocked'
type CheckStatus = 'ready' | 'warning' | 'blocked' | 'not_configured'
type ReadinessCheck = {
  check_id: string
  label: string
  status: CheckStatus
  required_for_current_mode: boolean
  detail: string
  action: string | null
}
type TourStep = {
  step_id: string
  label: string
  route: string
  instruction: string
  success_signal: string
}
type DemoReadiness = {
  schema_version: 'demo-readiness-v1'
  status: ReadinessStatus
  runtime_mode: 'offline_demo' | 'local_infrastructure'
  formal_chain_status: 'blocked_external_configuration' | 'configured_unverified' | 'verified'
  formal_chain_detail: string
  formal_chain_blockers: string[]
  paper_id: string
  checks: ReadinessCheck[]
  tour_steps: TourStep[]
}

const route = useRoute()
const router = useRouter()
const guideOpen = ref(route.query.guide === '1')
const loading = ref(false)
const error = ref('')
const readiness = ref<DemoReadiness | null>(null)

const tourActive = computed(() => route.query.tour === '1' && Boolean(readiness.value?.tour_steps.length))
const tourIndex = computed(() => {
  const raw = Number(route.query.demo_step ?? 0)
  const last = Math.max((readiness.value?.tour_steps.length ?? 1) - 1, 0)
  return Number.isInteger(raw) ? Math.min(Math.max(raw, 0), last) : 0
})
const currentStep = computed(() => readiness.value?.tour_steps[tourIndex.value] ?? null)
const statusLabel = computed(() => {
  if (readiness.value?.status === 'ready') return '核心演示可用'
  if (readiness.value?.status === 'degraded') return '核心演示部分可用'
  if (readiness.value?.status === 'blocked') return '核心演示存在阻断'
  return '正在检查演示环境'
})
const modeLabel = computed(() => readiness.value?.runtime_mode === 'local_infrastructure' ? '本地证据基础设施' : '离线演示数据')
const formalStatusLabel = computed(() => {
  if (readiness.value?.formal_chain_status === 'verified') return '讯飞正式链路已核验'
  if (readiness.value?.formal_chain_status === 'configured_unverified') return '讯飞链路已配置，待真实核验'
  return '讯飞正式链路尚未接入'
})

const checkLabel: Record<CheckStatus, string> = {
  ready: '就绪',
  warning: '待验证',
  blocked: '阻断',
  not_configured: '未启用',
}

async function loadReadiness() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/demo/readiness')
    if (!response.ok) throw new Error(`就绪检查失败：HTTP ${response.status}`)
    readiness.value = await response.json() as DemoReadiness
  } catch (reason) {
    readiness.value = null
    error.value = reason instanceof Error ? reason.message : '无法读取演示状态'
  } finally {
    loading.value = false
  }
}

async function openGuide() {
  guideOpen.value = true
  if (!readiness.value) await loadReadiness()
}

function closeGuide() {
  guideOpen.value = false
  if (route.query.guide === '1') {
    const query = { ...route.query }
    delete query.guide
    void router.replace({ query })
  }
}

function stepLocation(step: TourStep, index: number) {
  const target = new URL(step.route, window.location.origin)
  const query = Object.fromEntries(target.searchParams.entries())
  return {
    path: target.pathname,
    query: { ...query, tour: '1', demo_step: String(index) },
  }
}

function goToStep(index: number) {
  const step = readiness.value?.tour_steps[index]
  if (!step) return
  guideOpen.value = false
  void router.push(stepLocation(step, index))
}

function finishTour() {
  const query = { ...route.query }
  delete query.tour
  delete query.demo_step
  void router.replace({ query })
}

watch(
  () => route.query.guide,
  (value) => {
    if (value === '1') void openGuide()
  },
)

onMounted(loadReadiness)
</script>

<template>
  <button class="guide-trigger" data-testid="demo-guide-toggle" @click="openGuide">
    <span>▶</span> 演示引导
  </button>

  <Teleport to="body">
    <aside v-if="guideOpen" class="guide-panel" data-testid="demo-guide-panel" aria-label="核心演示引导">
      <header>
        <div><small>DEMO READINESS</small><h2>先确认链路，再开始演示</h2></div>
        <button aria-label="关闭演示引导" @click="closeGuide">×</button>
      </header>

      <section v-if="readiness" class="readiness-summary" :class="readiness.status">
        <i></i><div><b>{{ statusLabel }}</b><span>{{ modeLabel }}</span></div>
      </section>
      <section v-if="readiness" class="formal-chain" :class="readiness.formal_chain_status">
        <header><b>{{ formalStatusLabel }}</b><span>比赛主链路</span></header>
        <p>{{ readiness.formal_chain_detail }}</p>
        <ul v-if="readiness.formal_chain_blockers.length">
          <li v-for="blocker in readiness.formal_chain_blockers" :key="blocker">{{ blocker }}</li>
        </ul>
      </section>
      <p v-else-if="loading" class="guide-loading">正在检查API与核心依赖…</p>
      <p v-else class="guide-error">{{ error || '暂时无法读取演示状态。' }}</p>

      <section v-if="readiness" class="check-list" data-testid="demo-readiness-checks">
        <article v-for="check in readiness.checks" :key="check.check_id" :class="check.status">
          <header><b>{{ check.label }}</b><span>{{ checkLabel[check.status] }}</span></header>
          <p>{{ check.detail }}</p>
          <small v-if="check.action">{{ check.action }}</small>
        </article>
      </section>

      <section v-if="readiness" class="guide-story">
        <header><b>五步看懂核心价值</b><span>约3分钟</span></header>
        <ol>
          <li v-for="(step, index) in readiness.tour_steps" :key="step.step_id">
            <i>{{ index + 1 }}</i><div><b>{{ step.label }}</b><span>{{ step.instruction }}</span></div>
          </li>
        </ol>
      </section>

      <footer>
        <button :disabled="loading" @click="loadReadiness">重新检查</button>
        <button data-testid="start-guided-demo" :disabled="!readiness" @click="goToStep(0)">开始核心演示</button>
      </footer>
    </aside>

    <section v-if="tourActive && currentStep" class="tour-dock" data-testid="guided-demo-step">
      <header><span>核心演示 {{ tourIndex + 1 }}/{{ readiness?.tour_steps.length }}</span><button aria-label="退出演示" @click="finishTour">×</button></header>
      <h3>{{ currentStep.label }}</h3>
      <p>{{ currentStep.instruction }}</p>
      <div><b>看到什么算成功</b><span>{{ currentStep.success_signal }}</span></div>
      <footer>
        <button :disabled="tourIndex === 0" @click="goToStep(tourIndex - 1)">上一步</button>
        <button v-if="tourIndex < (readiness?.tour_steps.length ?? 0) - 1" data-testid="guided-demo-next" @click="goToStep(tourIndex + 1)">下一步</button>
        <button v-else data-testid="guided-demo-finish" @click="finishTour">完成演示</button>
      </footer>
    </section>
  </Teleport>
</template>

<style scoped>
.guide-trigger { display: inline-flex; gap: 6px; align-items: center; padding: 7px 11px; border: 1px solid #c7d5cc; border-radius: 99px; background: #fff; color: #285d48; font-size: 10px; font-weight: 800; cursor: pointer; }.guide-trigger span { color: #ef683e; font-size: 8px; }
.guide-panel { position: fixed; z-index: 100; top: 14px; right: 14px; bottom: 14px; width: min(430px, calc(100vw - 28px)); overflow-y: auto; padding: 20px; border: 1px solid #cad6ce; border-radius: 18px; background: #fbfcfa; box-shadow: 0 24px 70px rgba(17,45,33,.25); color: #20362c; }.guide-panel > header { display: flex; justify-content: space-between; gap: 18px; align-items: start; }.guide-panel > header small { color: #6e8177; font-size: 9px; font-weight: 900; letter-spacing: 1.6px; }.guide-panel h2 { margin: 5px 0 0; font-size: 21px; }.guide-panel > header button, .tour-dock > header button { border: 0; background: transparent; color: #738078; font-size: 24px; cursor: pointer; }
.readiness-summary { display: flex; gap: 11px; align-items: center; margin-top: 18px; padding: 13px; border-radius: 11px; background: #e7f3eb; }.readiness-summary i { width: 11px; height: 11px; border-radius: 50%; background: #3fa367; }.readiness-summary > div { display: grid; gap: 3px; }.readiness-summary b { font-size: 13px; }.readiness-summary span { color: #627268; font-size: 10px; }.readiness-summary.degraded { background: #fff4dc; }.readiness-summary.degraded i { background: #d69227; }.readiness-summary.blocked { background: #ffe9df; }.readiness-summary.blocked i { background: #dd603c; }
.formal-chain { margin-top: 9px; padding: 12px 13px; border: 1px solid #efc2b3; border-radius: 11px; background: #fff7f3; }.formal-chain header { display: flex; justify-content: space-between; gap: 12px; }.formal-chain header b { color: #9a432c; font-size: 11px; }.formal-chain header span { color: #a46e5e; font-size: 8px; font-weight: 900; letter-spacing: 1px; }.formal-chain p { margin: 7px 0 0; color: #6f5148; font-size: 9px; line-height: 1.5; }.formal-chain ul { margin: 7px 0 0; padding-left: 17px; color: #865447; font-size: 9px; line-height: 1.55; }.formal-chain.configured_unverified { border-color: #ead7ae; background: #fffaf0; }.formal-chain.configured_unverified header b { color: #95691e; }.formal-chain.verified { border-color: #b7d9c4; background: #eff8f2; }.formal-chain.verified header b { color: #28734a; }
.guide-loading, .guide-error { margin-top: 18px; padding: 14px; border-radius: 10px; background: #f0f2ef; font-size: 11px; }.guide-error { background: #ffe9df; color: #91442f; }
.check-list { display: grid; gap: 8px; margin-top: 13px; }.check-list article { padding: 11px 12px; border: 1px solid #dce3de; border-radius: 10px; background: white; }.check-list article > header { display: flex; justify-content: space-between; }.check-list article header b { font-size: 11px; }.check-list article header span { color: #37875a; font-size: 9px; font-weight: 900; }.check-list article p { margin: 7px 0 0; color: #56675e; font-size: 10px; line-height: 1.55; }.check-list article small { display: block; margin-top: 6px; color: #886325; font-size: 9px; line-height: 1.45; }.check-list article.blocked { border-color: #efb9a7; background: #fff8f5; }.check-list article.blocked header span { color: #c7502f; }.check-list article.warning, .check-list article.not_configured { border-color: #ead7ae; }.check-list article.warning header span, .check-list article.not_configured header span { color: #a67523; }
.guide-story { margin-top: 18px; padding-top: 15px; border-top: 1px solid #dfe5e1; }.guide-story > header { display: flex; justify-content: space-between; }.guide-story > header b { font-size: 12px; }.guide-story > header span { color: #7b8981; font-size: 9px; }.guide-story ol { display: grid; gap: 10px; margin: 13px 0 0; padding: 0; list-style: none; }.guide-story li { display: grid; grid-template-columns: 25px 1fr; gap: 9px; align-items: start; }.guide-story li > i { display: grid; place-items: center; width: 24px; height: 24px; border-radius: 50%; background: #dfeee6; color: #1e6548; font-size: 10px; font-style: normal; font-weight: 900; }.guide-story li div { display: grid; gap: 3px; }.guide-story li b { font-size: 11px; }.guide-story li span { color: #68776f; font-size: 9px; line-height: 1.5; }
.guide-panel > footer { position: sticky; bottom: -20px; display: flex; justify-content: flex-end; gap: 8px; margin: 20px -20px -20px; padding: 14px 20px; border-top: 1px solid #dce3de; background: rgba(251,252,250,.96); }.guide-panel > footer button, .tour-dock footer button { padding: 9px 13px; border: 1px solid #bfcfc5; border-radius: 8px; background: white; color: #355c49; font-size: 10px; font-weight: 800; cursor: pointer; }.guide-panel > footer button:last-child, .tour-dock footer button:last-child { border-color: #205c45; background: #205c45; color: white; }.guide-panel button:disabled, .tour-dock button:disabled { opacity: .45; cursor: not-allowed; }
.tour-dock { position: fixed; z-index: 95; right: 22px; bottom: 20px; width: min(440px, calc(100vw - 44px)); padding: 17px; border: 1px solid #a9c3b4; border-radius: 15px; background: #fff; box-shadow: 0 20px 55px rgba(19,50,37,.23); color: #20382d; }.tour-dock > header { display: flex; justify-content: space-between; align-items: center; }.tour-dock > header span { color: #ef683e; font-size: 9px; font-weight: 900; letter-spacing: 1px; }.tour-dock h3 { margin: 7px 0; font-size: 17px; }.tour-dock > p { margin: 0; color: #52675c; font-size: 11px; line-height: 1.55; }.tour-dock > div { display: grid; gap: 3px; margin-top: 11px; padding: 10px; border-radius: 8px; background: #eef4f0; }.tour-dock > div b { font-size: 9px; }.tour-dock > div span { color: #5f7168; font-size: 9px; line-height: 1.45; }.tour-dock > footer { display: flex; justify-content: flex-end; gap: 8px; margin-top: 12px; }
.tour-dock > footer { padding: 0; background: transparent; font-size: inherit; font-weight: normal; }
@media (max-width: 640px) { .guide-trigger { padding-inline: 8px; }.guide-panel { top: 8px; right: 8px; bottom: 8px; width: calc(100vw - 16px); }.tour-dock { right: 8px; bottom: 8px; width: calc(100vw - 16px); } }
</style>
