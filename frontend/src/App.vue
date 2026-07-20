<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'

type Evidence = {
  id: string
  kind: string
  label: string
  excerpt: string
  page: number | null
  verified: boolean
}
type Paper = {
  paper_id: string
  title: string
  venue: string
  year: number
  status: string
  narrative_moves: { id: string; order: number; move: string; purpose: string; evidence_ids: string[] }[]
  claims: { id: string; claim_type: string; statement: string; evidence_ids: string[] }[]
  experiment_intents: {
    id: string
    title: string
    question: string
    design_reason: string
    variables: string[]
    evidence_ids: string[]
  }[]
  artifacts: {
    id: string
    artifact_type: string
    label: string
    role: string
    why_here: string
    evidence_ids: string[]
  }[]
  limitations: string[]
  evidence: Evidence[]
}
type DocumentStructure = {
  source: string
  sections: { id: string; title: string; level: number; page_start: number | null }[]
  artifacts: {
    id: string
    label: string
    artifact_type: string
    page: number | null
    caption: string | null
  }[]
  warnings: string[]
}
type SearchHit = {
  paper_id: string
  title: string
  year: number
  venue: string
  snippet: string
  has_gold: boolean
}
type OpportunityEvidence = {
  paper_id: string
  paper_title: string
  year: number
  source_statement: string
  relation: 'supporting' | 'conflicting'
  evidence_anchor: Evidence
  matched_rule_terms: string[]
}
type Candidate = {
  candidate_id: string
  candidate_type: string
  topic_key: string
  problem_description: string
  evidence_paper_count: number
  supporting_evidence: OpportunityEvidence[]
  conflicting_evidence: OpportunityEvidence[]
  conflict_evidence_note: string
  corpus_coverage: {
    corpus_id: string
    retrieved_paper_count: number
    included_evidence_paper_count: number
    year_from: number | null
    year_to: number | null
    venues: string[]
  }
  confidence: { score: number; level: string; calculation: string; basis: string[] }
  human_confirmation_required: string[]
  applicable_conditions: string[]
  prohibited_conclusions: string[]
}
type OpportunityResponse = {
  status: 'ok' | 'insufficient_evidence'
  result_label: string
  disclaimer: string
  message: string
  query_plan: {
    query: string
    steps: string[]
    inclusion_rules: string[]
    exclusion_rules: string[]
    possible_omissions: string[]
    selections: {
      paper_id: string
      title: string
      year: number
      status: string
      decision: string
      reason: string
    }[]
    coverage: {
      corpus_id: string
      retrieved_paper_count: number
      included_evidence_paper_count: number
      year_from: number | null
      year_to: number | null
    }
  }
  progress_map: {
    milestone_id: string
    year: number
    title: string
    paper_id: string
    venue: string
    summary: string
    evidence_anchors: Evidence[]
  }[]
  candidates: Candidate[]
}
type PlannedExperiment = {
  experiment_id: string
  experiment_type: string
  title: string
  validation_goal: string
  design: string
  independent_variables: string[]
  dependent_variables: string[]
  controlled_variables: string[]
  required_inputs: string[]
  output_fields: string[]
  falsification_criteria: string[]
  interpretation_boundary: string[]
  rationale: {
    inference_type: 'system_planning_inference'
    evidence_references: {
      paper_id: string
      evidence_anchor_id: string
      relation: string
    }[]
    explanation: string
  }
}
type PlannedArtifact = {
  artifact_id: string
  artifact_type: string
  title: string
  validation_goal: string
  source_experiment_ids: string[]
  variables: string[]
  output_fields: string[]
  recommended_encoding: string
  evidence_boundary: string[]
}
type CoachResponse = {
  status: 'ready_for_review' | 'insufficient_evidence'
  message: string
  plan: null | {
    plan_id: string
    source_candidate_id: string
    experiments: PlannedExperiment[]
    artifacts: PlannedArtifact[]
    open_decisions: string[]
    global_boundaries: string[]
  }
}

const searchQuery = ref('time series anomaly detection')
const opportunityQuery = ref('time series anomaly detection')
const yearFrom = ref<number | null>(null)
const yearTo = ref<number | null>(null)
const hits = ref<SearchHit[]>([])
const paper = ref<Paper | null>(null)
const structure = ref<DocumentStructure | null>(null)
const selectedEvidence = ref<Evidence | null>(null)
const opportunity = ref<OpportunityResponse | null>(null)
const lastOpportunityRequest = ref<Record<string, string | number>>({
  query: opportunityQuery.value,
  minimum_evidence_papers: 2,
})
const selectedCandidate = ref<Candidate | null>(null)
const researchQuestion = ref('')
const hypothesis = ref('')
const proposedMethod = ref('')
const coachResponse = ref<CoachResponse | null>(null)
const loadingSearch = ref(false)
const loadingOpportunity = ref(false)
const loadingPlan = ref(false)
const error = ref('')

const evidenceMap = computed(
  () => new Map((paper.value?.evidence ?? []).map((item) => [item.id, item])),
)

async function search() {
  loadingSearch.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/tools/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query: searchQuery.value, limit: 5 }),
    })
    if (!response.ok) throw new Error('检索接口暂时不可用。')
    hits.value = (await response.json()).hits
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loadingSearch.value = false
  }
}

async function selectPaper(hit: SearchHit) {
  if (!hit.has_gold) return
  error.value = ''
  const [paperResponse, structureResponse] = await Promise.all([
    fetch(`/api/v1/tools/paper-deconstruct/${hit.paper_id}`, { method: 'POST' }),
    fetch(`/api/v1/papers/${hit.paper_id}/document-structure`),
  ])
  if (!paperResponse.ok) {
    error.value = '这篇论文尚无可公开加载的深度记录。'
    return
  }
  paper.value = await paperResponse.json()
  structure.value = structureResponse.ok ? await structureResponse.json() : null
  selectedEvidence.value = paper.value?.evidence[0] ?? null
}

function inspectEvidence(evidenceIds: string[]) {
  selectedEvidence.value = evidenceMap.value.get(evidenceIds[0]) ?? null
  document.querySelector('#paper-evidence')?.scrollIntoView({ behavior: 'smooth' })
}

async function analyzeOpportunities() {
  loadingOpportunity.value = true
  error.value = ''
  try {
    const payload: Record<string, string | number> = {
      query: opportunityQuery.value,
      minimum_evidence_papers: 2,
    }
    if (typeof yearFrom.value === 'number' && Number.isFinite(yearFrom.value)) {
      payload.year_from = yearFrom.value
    }
    if (typeof yearTo.value === 'number' && Number.isFinite(yearTo.value)) {
      payload.year_to = yearTo.value
    }
    lastOpportunityRequest.value = payload
    const response = await fetch('/api/v1/research/opportunities', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) throw new Error('研究机会分析请求无效或暂时不可用。')
    opportunity.value = await response.json()
    selectedCandidate.value = null
    coachResponse.value = null
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loadingOpportunity.value = false
  }
}

function selectCandidateForPlan(candidate: Candidate) {
  selectedCandidate.value = candidate
  coachResponse.value = null
  window.setTimeout(() => {
    document.querySelector('#research-coach')?.scrollIntoView({ behavior: 'smooth' })
  }, 0)
}

async function createExperimentPlan() {
  if (!selectedCandidate.value) return
  loadingPlan.value = true
  error.value = ''
  try {
    const response = await fetch('/api/v1/research/experiment-plans', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        opportunity: lastOpportunityRequest.value,
        candidate_id: selectedCandidate.value.candidate_id,
        project_claim: {
          research_question: researchQuestion.value,
          hypothesis: hypothesis.value,
          proposed_method: proposedMethod.value,
        },
      }),
    })
    if (!response.ok) {
      throw new Error(
        response.status === 404
          ? '该候选已不在当前查询范围，请重新运行研究机会分析。'
          : '研究教练请求无效或暂时不可用。',
      )
    }
    coachResponse.value = await response.json()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loadingPlan.value = false
  }
}

onMounted(async () => {
  await Promise.all([search(), analyzeOpportunities()])
  const first = hits.value.find((item) => item.has_gold)
  if (first) await selectPaper(first)
})
</script>

<template>
  <div class="shell">
    <header class="topbar">
      <a class="brand" href="#top">KD<span>·</span>Agent</a>
      <nav>
        <a href="#papers">论文拆解</a>
        <a href="#opportunities">研究进展与机会</a>
        <span class="status"><i></i> 离线证据模式</span>
      </nav>
    </header>

    <main id="top">
      <section class="hero">
        <p class="eyebrow">EVIDENCE-GROUNDED RESEARCH COPILOT</p>
        <h1>从论文证据出发，<br /><em>寻找值得验证的问题。</em></h1>
        <p class="hero-copy">
          系统只输出 Research Opportunity Candidate，不会把候选声明为已确认创新。证据不足时会明确停止。
        </p>
        <form class="searchbox" @submit.prevent="search">
          <span>⌕</span>
          <input v-model="searchQuery" aria-label="论文检索主题" />
          <button :disabled="loadingSearch">{{ loadingSearch ? '检索中' : '检索论文' }}</button>
        </form>
        <p v-if="error" class="error">{{ error }}</p>
      </section>

      <section id="papers" class="paper-results" aria-label="论文检索结果">
        <article
          v-for="hit in hits"
          :key="hit.paper_id"
          class="paper-hit"
          :class="{ disabled: !hit.has_gold }"
          @click="selectPaper(hit)"
        >
          <div class="paper-meta"><span>{{ hit.year }}</span><span>{{ hit.venue }}</span></div>
          <h3>{{ hit.title }}</h3>
          <p>{{ hit.snippet }}</p>
          <b>{{ hit.has_gold ? '查看证据拆解 →' : '等待审核，不参与机会分析' }}</b>
        </article>
      </section>

      <section v-if="paper" class="paper-workspace">
        <div class="section-heading">
          <div>
            <p class="eyebrow">PAPER DECONSTRUCTION</p>
            <h2>{{ paper.title }}</h2>
            <p>{{ paper.venue }} · {{ paper.year }} · {{ paper.status }}</p>
          </div>
          <span class="boundary-pill">开发种子，不是冻结 Gold</span>
        </div>
        <div class="narrative-list">
          <article v-for="move in paper.narrative_moves" :key="move.id">
            <span>{{ String(move.order).padStart(2, '0') }}</span>
            <div><h3>{{ move.move }}</h3><p>{{ move.purpose }}</p></div>
            <button @click="inspectEvidence(move.evidence_ids)">证据 {{ move.evidence_ids.join(', ') }}</button>
          </article>
        </div>
        <div class="paper-fact-grid">
          <section>
            <h3>实验意图</h3>
            <article v-for="item in paper.experiment_intents" :key="item.id">
              <b>{{ item.title }}</b>
              <p>{{ item.question }}</p>
              <button @click="inspectEvidence(item.evidence_ids)">检查支撑证据</button>
            </article>
          </section>
          <section>
            <h3>Figure / Table 角色</h3>
            <article v-for="item in paper.artifacts" :key="item.id">
              <b>{{ item.label }} · {{ item.role }}</b>
              <p>{{ item.why_here }}</p>
              <button @click="inspectEvidence(item.evidence_ids)">检查支撑证据</button>
            </article>
          </section>
        </div>
        <section v-if="structure" class="structure-summary">
          <header>
            <div><h3>文档结构</h3><p>查询来源：{{ structure.source }}</p></div>
            <span>{{ structure.artifacts.length }} 个版面图表事实</span>
          </header>
          <ol>
            <li v-for="section in structure.sections" :key="section.id">
              <span>H{{ section.level }}</span>
              <b>{{ section.title }}</b>
              <small>{{ section.page_start ? `p.${section.page_start}` : '未提供真实页码' }}</small>
            </li>
          </ol>
          <p v-for="warning in structure.warnings" :key="warning" class="structure-warning">
            {{ warning }}
          </p>
        </section>
        <aside v-if="selectedEvidence" id="paper-evidence" class="paper-evidence">
          <div><b>{{ selectedEvidence.kind }}</b><span>{{ selectedEvidence.verified ? '已核验' : '待核验' }}</span></div>
          <h3>{{ selectedEvidence.label }}</h3>
          <blockquote>{{ selectedEvidence.excerpt }}</blockquote>
          <p>页码：{{ selectedEvidence.page ?? '尚未由授权 PDF 核验' }}</p>
        </aside>
      </section>

      <section id="opportunities" class="opportunity-section">
        <div class="opportunity-intro">
          <p class="eyebrow">RESEARCH PROGRESS & OPPORTUNITY CANDIDATES</p>
          <h2>把检索范围、证据冲突和未知项一起摆出来。</h2>
          <p>
            候选由确定性规则和已核验 EvidenceAnchor 生成。当前语料覆盖不足时，不会用排队论文或合成数据补齐。
          </p>
        </div>

        <form class="opportunity-form" @submit.prevent="analyzeOpportunities">
          <label>研究问题<input v-model="opportunityQuery" /></label>
          <label>起始年份<input v-model.number="yearFrom" type="number" min="1900" max="2100" placeholder="不限" /></label>
          <label>结束年份<input v-model.number="yearTo" type="number" min="1900" max="2100" placeholder="不限" /></label>
          <button :disabled="loadingOpportunity">{{ loadingOpportunity ? '分析中' : '运行证据分析' }}</button>
        </form>

        <template v-if="opportunity">
          <div class="result-state" :class="opportunity.status">
            <span>{{ opportunity.status }}</span>
            <strong>{{ opportunity.message }}</strong>
            <p>{{ opportunity.disclaimer }}</p>
          </div>

          <section class="query-plan">
            <div class="plan-header">
              <div><p class="eyebrow">QUERY PLAN</p><h3>查询计划与语料边界</h3></div>
              <div class="coverage-stats">
                <span><b>{{ opportunity.query_plan.coverage.retrieved_paper_count }}</b> 注册论文</span>
                <span><b>{{ opportunity.query_plan.coverage.included_evidence_paper_count }}</b> 纳入证据论文</span>
                <span><b>{{ opportunity.query_plan.coverage.year_from ?? '—' }}–{{ opportunity.query_plan.coverage.year_to ?? '—' }}</b> 年份覆盖</span>
              </div>
            </div>
            <div class="plan-columns">
              <div><h4>执行步骤</h4><ol><li v-for="item in opportunity.query_plan.steps" :key="item">{{ item }}</li></ol></div>
              <div><h4>纳入规则</h4><ul><li v-for="item in opportunity.query_plan.inclusion_rules" :key="item">{{ item }}</li></ul></div>
              <div><h4>排除规则</h4><ul><li v-for="item in opportunity.query_plan.exclusion_rules" :key="item">{{ item }}</li></ul></div>
            </div>
            <div class="selection-list">
              <article v-for="item in opportunity.query_plan.selections" :key="item.paper_id">
                <span :class="item.decision">{{ item.decision }}</span>
                <div><b>{{ item.title }}</b><p>{{ item.year }} · {{ item.status }} · {{ item.reason }}</p></div>
              </article>
            </div>
            <details><summary>可能遗漏</summary><ul><li v-for="item in opportunity.query_plan.possible_omissions" :key="item">{{ item }}</li></ul></details>
          </section>

          <section class="progress-section">
            <p class="eyebrow">READABLE PROGRESS MAP</p>
            <h3>研究进展地图</h3>
            <div v-if="opportunity.progress_map.length" class="progress-map">
              <article v-for="item in opportunity.progress_map" :key="item.milestone_id">
                <span class="progress-year">{{ item.year }}</span>
                <div><small>{{ item.venue }} · {{ item.paper_id }}</small><h4>{{ item.title }}</h4><p>{{ item.summary }}</p><b>EvidenceAnchor: {{ item.evidence_anchors.map((anchor) => anchor.id).join(', ') }}</b></div>
              </article>
            </div>
            <p v-else class="empty-map">没有达到纳入规则的论文，因此不绘制虚假的研究进展节点。</p>
          </section>

          <section class="candidate-section">
            <p class="eyebrow">CANDIDATE LIST</p>
            <h3>Research Opportunity Candidates</h3>
            <div v-if="opportunity.candidates.length" class="candidate-list">
              <article v-for="candidate in opportunity.candidates" :key="candidate.candidate_id" class="candidate-card">
                <header><span>Research Opportunity Candidate</span><b>{{ candidate.candidate_type }}</b></header>
                <h4>{{ candidate.problem_description }}</h4>
                <div class="candidate-stats"><span>{{ candidate.evidence_paper_count }} 篇证据论文</span><span>置信度 {{ candidate.confidence.score.toFixed(3) }} / {{ candidate.confidence.level }}</span><span>{{ candidate.corpus_coverage.year_from }}–{{ candidate.corpus_coverage.year_to }}</span></div>
                <div class="evidence-columns">
                  <section><h5>支持证据</h5><article v-for="item in candidate.supporting_evidence" :key="`${item.paper_id}-${item.evidence_anchor.id}`"><b>{{ item.paper_title }} · {{ item.year }}</b><p>{{ item.source_statement }}</p><small>{{ item.evidence_anchor.id }} · {{ item.evidence_anchor.label }}</small></article></section>
                  <section><h5>反对或冲突证据</h5><article v-for="item in candidate.conflicting_evidence" :key="`${item.paper_id}-${item.evidence_anchor.id}`"><b>{{ item.paper_title }} · {{ item.year }}</b><p>{{ item.source_statement }}</p><small>{{ item.evidence_anchor.id }} · {{ item.evidence_anchor.label }}</small></article><p v-if="!candidate.conflicting_evidence.length">{{ candidate.conflict_evidence_note }}</p></section>
                </div>
                <div class="candidate-boundaries">
                  <section><h5>置信度依据</h5><p>{{ candidate.confidence.calculation }}</p><ul><li v-for="item in candidate.confidence.basis" :key="item">{{ item }}</li></ul></section>
                  <section><h5>仍需人工确认</h5><ul><li v-for="item in candidate.human_confirmation_required" :key="item">{{ item }}</li></ul></section>
                  <section><h5>适用条件</h5><ul><li v-for="item in candidate.applicable_conditions" :key="item">{{ item }}</li></ul></section>
                  <section><h5>不能得出的结论</h5><ul><li v-for="item in candidate.prohibited_conclusions" :key="item">{{ item }}</li></ul></section>
                </div>
                <button class="coach-start" @click="selectCandidateForPlan(candidate)">
                  用这个候选制定可证伪实验与图表计划 →
                </button>
              </article>
            </div>
            <p v-else class="empty-candidates">当前没有满足至少两篇已审核、已核验证据论文覆盖的候选。</p>
          </section>

          <section v-if="selectedCandidate" id="research-coach" class="coach-section">
            <p class="eyebrow">RESEARCH COACH</p>
            <h3>从用户假设反推实验与图表</h3>
            <p class="coach-boundary">
              研究问题、假设和拟议方法由你提供，系统不会补成论文事实；输出只是一份待执行、待复核的计划。
            </p>
            <div class="selected-candidate">
              <span>{{ selectedCandidate.candidate_type }}</span>
              <b>{{ selectedCandidate.problem_description }}</b>
            </div>
            <form class="coach-form" @submit.prevent="createExperimentPlan">
              <label>
                研究问题
                <textarea v-model="researchQuestion" required minlength="10" rows="3" placeholder="你希望回答的可检验问题"></textarea>
              </label>
              <label>
                可证伪假设
                <textarea v-model="hypothesis" required minlength="10" rows="4" placeholder="写明什么观察会支持或反驳该假设"></textarea>
              </label>
              <label>
                拟议方法
                <textarea v-model="proposedMethod" required minlength="2" rows="3" placeholder="只描述你的方法，不填入未经实验的效果"></textarea>
              </label>
              <button :disabled="loadingPlan">
                {{ loadingPlan ? '生成计划中' : '生成证据约束计划' }}
              </button>
            </form>

            <div v-if="coachResponse" class="coach-result" :class="coachResponse.status">
              <header><span>{{ coachResponse.status }}</span><p>{{ coachResponse.message }}</p></header>
              <template v-if="coachResponse.plan">
                <div class="plan-identity">
                  <b>{{ coachResponse.plan.plan_id }}</b>
                  <span>来源候选 {{ coachResponse.plan.source_candidate_id }}</span>
                </div>
                <section class="experiment-plan-list">
                  <article v-for="experiment in coachResponse.plan.experiments" :key="experiment.experiment_id">
                    <header><span>{{ experiment.experiment_type }}</span><b>{{ experiment.experiment_id }}</b></header>
                    <h4>{{ experiment.title }}</h4>
                    <p><strong>验证目标：</strong>{{ experiment.validation_goal }}</p>
                    <p><strong>设计：</strong>{{ experiment.design }}</p>
                    <div class="experiment-fields">
                      <section><h5>自变量</h5><ul><li v-for="item in experiment.independent_variables" :key="item">{{ item }}</li></ul></section>
                      <section><h5>因变量</h5><ul><li v-for="item in experiment.dependent_variables" :key="item">{{ item }}</li></ul></section>
                      <section><h5>控制变量</h5><ul><li v-for="item in experiment.controlled_variables" :key="item">{{ item }}</li></ul></section>
                      <section><h5>输出字段</h5><ul><li v-for="item in experiment.output_fields" :key="item">{{ item }}</li></ul></section>
                    </div>
                    <div class="experiment-boundaries">
                      <section><h5>可反驳条件</h5><ul><li v-for="item in experiment.falsification_criteria" :key="item">{{ item }}</li></ul></section>
                      <section><h5>解释边界</h5><ul><li v-for="item in experiment.interpretation_boundary" :key="item">{{ item }}</li></ul></section>
                    </div>
                    <details>
                      <summary>规划推断与证据引用</summary>
                      <p>{{ experiment.rationale.explanation }}</p>
                      <ul><li v-for="item in experiment.rationale.evidence_references" :key="`${item.paper_id}-${item.evidence_anchor_id}-${item.relation}`">{{ item.paper_id }} · {{ item.evidence_anchor_id }} · {{ item.relation }}</li></ul>
                    </details>
                  </article>
                </section>

                <section class="artifact-plan-grid">
                  <article v-for="artifact in coachResponse.plan.artifacts" :key="artifact.artifact_id">
                    <span>{{ artifact.artifact_type }}</span>
                    <h4>{{ artifact.title }}</h4>
                    <p><strong>验证目标：</strong>{{ artifact.validation_goal }}</p>
                    <b>来源实验：{{ artifact.source_experiment_ids.join(', ') }}</b>
                    <h5>变量</h5>
                    <p>{{ artifact.variables.join(' · ') }}</p>
                    <h5>输出字段</h5>
                    <p>{{ artifact.output_fields.join(' · ') }}</p>
                    <h5>表达建议</h5>
                    <p>{{ artifact.recommended_encoding }}</p>
                    <h5>证据边界</h5>
                    <ul><li v-for="item in artifact.evidence_boundary" :key="item">{{ item }}</li></ul>
                  </article>
                </section>

                <div class="plan-checklist">
                  <section><h4>执行前待决定</h4><ul><li v-for="item in coachResponse.plan.open_decisions" :key="item">{{ item }}</li></ul></section>
                  <section><h4>全局证据边界</h4><ul><li v-for="item in coachResponse.plan.global_boundaries" :key="item">{{ item }}</li></ul></section>
                </div>
              </template>
            </div>
          </section>
        </template>
      </section>
    </main>

    <footer><span>KD·Agent / reconstructed evidence baseline</span><span>Candidate ≠ confirmed innovation</span></footer>
  </div>
</template>
