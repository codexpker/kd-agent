<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'

type Evidence = { id: string; kind: string; label: string; excerpt: string; page: number | null; verified: boolean }
type NarrativeMove = { id: string; order: number; move: string; purpose: string; evidence_ids: string[] }
type Claim = { id: string; claim_type: string; statement: string; evidence_ids: string[] }
type Experiment = { id: string; title: string; question: string; design_reason: string; variables: string[]; supports_claim_ids: string[]; evidence_ids: string[] }
type Artifact = { id: string; artifact_type: string; label: string; role: string; why_here: string; supports_claim_ids: string[]; evidence_ids: string[] }
type Paper = { title: string; venue: string; year: number; status: string; narrative_moves: NarrativeMove[]; claims: Claim[]; experiment_intents: Experiment[]; artifacts: Artifact[]; evidence: Evidence[]; limitations: string[] }
type SearchHit = { paper_id: string; title: string; year: number; venue: string; snippet: string; has_gold: boolean }
type Structure = { source: string; sections: { id: string; title: string; page_start: number | null }[]; artifacts: { id: string; label: string; artifact_type: string; page: number | null; caption: string | null }[]; warnings: string[] }

const query = ref('Transformer 在多变量时间序列异常检测中的研究进展')
const hits = ref<SearchHit[]>([])
const paper = ref<Paper | null>(null)
const structure = ref<Structure | null>(null)
const selectedEvidence = ref<Evidence | null>(null)
const activeTab = ref<'narrative' | 'experiments' | 'artifacts'>('narrative')
const loading = ref(false)
const error = ref('')

const evidenceMap = computed(() => new Map((paper.value?.evidence ?? []).map(item => [item.id, item])))

async function search() {
  loading.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/tools/search', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ query: query.value, limit: 5 }) })
    if (!response.ok) throw new Error('检索接口暂时不可用')
    hits.value = (await response.json()).hits
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function selectPaper(hit: SearchHit) {
  if (!hit.has_gold) return
  loading.value = true
  error.value = ''
  try {
    const [paperResponse, structureResponse] = await Promise.all([
      fetch(`/api/v1/tools/paper-deconstruct/${hit.paper_id}`, { method: 'POST' }),
      fetch(`/api/v1/papers/${hit.paper_id}/document-structure`),
    ])
    if (!paperResponse.ok) throw new Error('这篇论文尚无已审核的深度记录')
    paper.value = await paperResponse.json()
    structure.value = structureResponse.ok ? await structureResponse.json() : null
    selectedEvidence.value = paper.value?.evidence[0] ?? null
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function inspectEvidence(ids: string[]) {
  selectedEvidence.value = evidenceMap.value.get(ids[0]) ?? null
  await nextTick()
  document.querySelector('#evidence-lens')?.scrollIntoView({ behavior: 'smooth', block: 'center' })
}

onMounted(async () => {
  await search()
  const first = hits.value.find(item => item.has_gold)
  if (first) await selectPaper(first)
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <a class="brand" href="#">KD<span>·</span>Agent</a>
      <nav><a href="#workspace">论文拆解</a><a href="#evidence-lens">证据透镜</a><span class="status"><i></i> 离线 Gold</span></nav>
    </header>

    <main>
      <section class="hero">
        <div class="eyebrow">EVIDENCE-GROUNDED RESEARCH COPILOT</div>
        <h1>别只读结论，<br><em>看懂论文如何证明。</em></h1>
        <p>从 Problem 到 Evidence，拆开论文的叙事、实验与图表。系统显示证据边界，不把候选方向伪装成确定创新。</p>
        <form class="searchbox" @submit.prevent="search">
          <span>⌕</span><input v-model="query" aria-label="研究主题" /><button :disabled="loading">{{ loading ? '分析中' : '开始研究' }}</button>
        </form>
        <p v-if="error" class="error">{{ error }}</p>
      </section>

      <section class="results" aria-label="检索结果">
        <article v-for="hit in hits" :key="hit.paper_id" class="paper-hit" :class="{ disabled: !hit.has_gold }" @click="selectPaper(hit)">
          <div><span class="year">{{ hit.year }}</span><span>{{ hit.venue }}</span></div>
          <h3>{{ hit.title }}</h3><p>{{ hit.snippet }}</p>
          <b>{{ hit.has_gold ? '打开深度拆解 →' : '标注队列中' }}</b>
        </article>
      </section>

      <section v-if="paper" id="workspace" class="workspace">
        <div class="section-head"><div><span class="kicker">PAPER DECONSTRUCTION</span><h2>{{ paper.title }}</h2><p>{{ paper.venue }} · {{ paper.year }} · 开发种子（尚未冻结）</p></div><div class="chain">Problem <span>→</span> Gap <span>→</span> Claim <span>→</span> Experiment <span>→</span> Evidence</div></div>

        <div class="tabs"><button :class="{ active: activeTab === 'narrative' }" @click="activeTab = 'narrative'">叙事链</button><button :class="{ active: activeTab === 'experiments' }" @click="activeTab = 'experiments'">实验意图</button><button :class="{ active: activeTab === 'artifacts' }" @click="activeTab = 'artifacts'">图表角色</button></div>

        <div v-if="activeTab === 'narrative'" class="timeline">
          <article v-for="move in paper.narrative_moves" :key="move.id"><span class="step">{{ String(move.order).padStart(2, '0') }}</span><div><h3>{{ move.move }}</h3><p>{{ move.purpose }}</p><button @click="inspectEvidence(move.evidence_ids)">查看证据 {{ move.evidence_ids.join(', ') }}</button></div></article>
        </div>

        <div v-else-if="activeTab === 'experiments'" class="card-grid">
          <article v-for="item in paper.experiment_intents" :key="item.id" class="intent-card"><span class="tag">RESEARCH QUESTION</span><h3>{{ item.title }}</h3><strong>{{ item.question }}</strong><p>{{ item.design_reason }}</p><div class="chips"><span v-for="v in item.variables" :key="v">{{ v }}</span></div><button @click="inspectEvidence(item.evidence_ids)">检查支撑证据 →</button></article>
        </div>

        <div v-else class="card-grid artifacts">
          <article v-for="item in paper.artifacts" :key="item.id" class="intent-card"><span class="tag">{{ item.label }}</span><h3>{{ item.role }}</h3><p>{{ item.why_here }}</p><button @click="inspectEvidence(item.evidence_ids)">为什么放在这里？ →</button></article>
        </div>
      </section>

      <section v-if="paper" id="evidence-lens" class="evidence-lens">
        <div class="lens-nav"><span class="kicker">LAYOUT EVIDENCE LENS</span><h2>证据不是装饰，<br>它决定结论的边界。</h2><div class="section-list"><button v-for="section in structure?.sections" :key="section.id">{{ section.title }} <span>{{ section.page_start ? `p.${section.page_start}` : '页码待解析' }}</span></button></div></div>
        <article v-if="selectedEvidence" class="evidence-card"><div class="evidence-meta"><span>{{ selectedEvidence.kind }}</span><span>{{ selectedEvidence.page ? `PAGE ${selectedEvidence.page}` : 'PAGE NOT VERIFIED' }}</span></div><h3>{{ selectedEvidence.label }}</h3><blockquote>{{ selectedEvidence.excerpt }}</blockquote><div class="warning">△ 当前为 Gold 语义快照。只有合法全文完成解析和人工复核后，才会显示真实页码、bbox、图注与正文引用。</div></article>
      </section>

      <section v-if="paper" class="claims"><span class="kicker">CLAIM AUDIT</span><h2>主张与边界</h2><div class="claim-list"><article v-for="claim in paper.claims" :key="claim.id"><span>{{ claim.claim_type }}</span><p>{{ claim.statement }}</p><button @click="inspectEvidence(claim.evidence_ids)">证据 {{ claim.evidence_ids.join(' · ') }}</button></article></div><div class="limits"><h3>仍需人工确认</h3><ul><li v-for="item in paper.limitations" :key="item">{{ item }}</li></ul></div></section>
    </main>

    <footer><span>KD·Agent / Reconstructed handoff</span><span>Trace claims. Inspect evidence. Respect boundaries.</span></footer>
  </div>
</template>

