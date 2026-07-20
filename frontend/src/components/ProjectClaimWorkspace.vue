<script setup lang="ts">
import { computed, ref } from 'vue'

type ExistingResult = {
  label: string
  description: string
  result_type: 'observation' | 'quantitative' | 'partial' | 'negative' | 'other'
  source?: 'user_reported'
  verified?: false
}
type ClaimInput = {
  research_question: string
  hypothesis: string
  proposed_method: string
  target_scenario: string
  existing_results: ExistingResult[]
}
type ClaimVersion = ClaimInput & {
  project_id: string
  claim_id: string
  claim_version_id: string
  version: number
  supersedes_claim_version_id: string | null
  origin: 'user_supplied'
  content_sha256: string
  created_at: string
}
type Artifact = {
  artifact_type: 'table' | 'line_chart' | 'bar_chart' | 'heatmap' | 'scatter_plot' | 'case_panel'
  title: string
  rationale: string
}
type Requirement = {
  requirement_id: string
  requirement_type: string
  validates_claim_version_id: string
  validates_claim: string
  why_needed: string
  independent_variables: string[]
  controlled_variables: string[]
  output_fields: string[]
  recommended_artifact: Artifact
  can_support: string[]
  cannot_support: string[]
  status: 'planned' | 'in_progress' | 'user_reports_evidence_available' | 'not_applicable'
  user_notes: string
  generated_by_rule: string
}
type Diagnosis = {
  diagnosis_id: string
  claim_version_id: string
  revision: number
  origin: 'rule_generated' | 'user_edited'
  planner_version: string
  language_organizer: 'deterministic_templates'
  requirements: Requirement[]
  feasibility_assessment: 'not_assessed'
  innovation_assessment: 'not_assessed'
  created_at: string
}
type Envelope = { claim: ClaimVersion; diagnosis: Diagnosis }

const projectId = ref('tad-noise-study')
const researchQuestion = ref('')
const hypothesis = ref('')
const proposedMethod = ref('')
const targetScenario = ref('')
const existingResults = ref<ExistingResult[]>([])
const history = ref<ClaimVersion[]>([])
const envelope = ref<Envelope | null>(null)
const loading = ref(false)
const error = ref('')
const notice = ref('')

const expectedLatestVersion = computed(
  () => history.value.at(-1)?.version ?? 0,
)

const requirementLabels: Record<string, string> = {
  main_experiment: '主实验',
  strong_baseline: '强基线',
  fair_comparison: '公平比较条件',
  ablation: '消融实验',
  parameter_sensitivity: '参数敏感性',
  robustness: '鲁棒性',
  efficiency: '效率',
  failure_cases: '失败案例',
}

function claimPayload(): ClaimInput {
  return {
    research_question: researchQuestion.value,
    hypothesis: hypothesis.value,
    proposed_method: proposedMethod.value,
    target_scenario: targetScenario.value,
    existing_results: existingResults.value.map((item) => ({
      ...item,
      source: 'user_reported',
      verified: false,
    })),
  }
}

function loadClaimIntoEditor(claim: ClaimInput) {
  researchQuestion.value = claim.research_question
  hypothesis.value = claim.hypothesis
  proposedMethod.value = claim.proposed_method
  targetScenario.value = claim.target_scenario
  existingResults.value = claim.existing_results.map((item) => ({ ...item }))
}

function setEnvelope(payload: Envelope) {
  envelope.value = payload
  loadClaimIntoEditor(payload.claim)
}

async function loadTadExample() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const response = await fetch('/api/v1/research/project-claims/examples/tad')
    if (!response.ok) throw new Error('TAD 示例暂时不可用。')
    const payload = await response.json()
    loadClaimIntoEditor(payload.claim)
    notice.value = payload.disclaimer
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function loadHistory() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const response = await fetch(
      `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/claims`,
    )
    if (!response.ok) throw new Error('Project Claim 历史加载失败。')
    history.value = (await response.json()).versions
    if (history.value.length) {
      await loadVersion(history.value.at(-1)!.version)
    } else {
      envelope.value = null
      notice.value = '当前项目还没有 Claim 版本。'
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function loadVersion(version: number) {
  const response = await fetch(
    `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/claims/${version}`,
  )
  if (!response.ok) throw new Error(`Claim v${version} 加载失败。`)
  setEnvelope(await response.json())
}

async function saveClaim() {
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const response = await fetch(
      `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/claims`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_latest_version: expectedLatestVersion.value,
          claim: claimPayload(),
        }),
      },
    )
    if (!response.ok) {
      throw new Error(
        response.status === 409
          ? '版本已被更新，请重新加载历史后再保存。'
          : 'Project Claim 输入无效或后端不可用。',
      )
    }
    const payload: Envelope = await response.json()
    setEnvelope(payload)
    await refreshHistoryOnly()
    notice.value = `已保存 Claim v${payload.claim.version}，并生成规则化证据诊断。`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function refreshHistoryOnly() {
  const response = await fetch(
    `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/claims`,
  )
  if (response.ok) history.value = (await response.json()).versions
}

function addExistingResult() {
  existingResults.value.push({
    label: '',
    description: '',
    result_type: 'partial',
  })
}

function removeExistingResult(index: number) {
  existingResults.value.splice(index, 1)
}

type ListField =
  | 'independent_variables'
  | 'controlled_variables'
  | 'output_fields'
  | 'can_support'
  | 'cannot_support'

function updateLines(requirement: Requirement, field: ListField, event: Event) {
  const value = (event.target as HTMLTextAreaElement).value
  requirement[field] = value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

async function saveDiagnosis() {
  if (!envelope.value) return
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const diagnosis = envelope.value.diagnosis
    const response = await fetch(
      `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/claims/${envelope.value.claim.version}/diagnosis`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_revision: diagnosis.revision,
          requirements: diagnosis.requirements.map((item) => ({
            requirement_type: item.requirement_type,
            why_needed: item.why_needed,
            independent_variables: item.independent_variables,
            controlled_variables: item.controlled_variables,
            output_fields: item.output_fields,
            recommended_artifact: item.recommended_artifact,
            can_support: item.can_support,
            cannot_support: item.cannot_support,
            status: item.status,
            user_notes: item.user_notes,
          })),
        }),
      },
    )
    if (!response.ok) {
      throw new Error(
        response.status === 409
          ? '诊断已被更新，请重新加载该 Claim 版本。'
          : '诊断编辑内容无效或后端不可用。',
      )
    }
    setEnvelope(await response.json())
    notice.value = `诊断已保存为修订 r${envelope.value!.diagnosis.revision}。`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <section id="project-claim" class="claim-workspace">
    <header class="claim-heading">
      <div>
        <p class="claim-eyebrow">R4 · ADVANCE MY RESEARCH</p>
        <h2>先写清你的 Claim，<br /><em>再检查证据缺口。</em></h2>
        <p>
          这里保存的是用户输入，不是论文事实。规则规划器只诊断最小证据需求，不评估可行性或创新性。
        </p>
      </div>
      <button type="button" :disabled="loading" @click="loadTadExample">载入合成 TAD 示例</button>
    </header>

    <div class="project-toolbar">
      <label>项目 ID<input v-model="projectId" pattern="[a-z0-9][a-z0-9-]{2,63}" /></label>
      <button type="button" :disabled="loading" @click="loadHistory">加载版本历史</button>
      <span>下一版本：v{{ expectedLatestVersion + 1 }}</span>
    </div>

    <div v-if="history.length" class="version-strip">
      <button v-for="item in history" :key="item.claim_version_id" type="button" @click="loadVersion(item.version)">
        v{{ item.version }} · {{ new Date(item.created_at).toLocaleString() }}
      </button>
    </div>

    <form class="claim-form" @submit.prevent="saveClaim">
      <label>研究问题<textarea v-model="researchQuestion" required minlength="10" rows="3"></textarea></label>
      <label>假设<textarea v-model="hypothesis" required minlength="10" rows="4"></textarea></label>
      <label>拟议方法<textarea v-model="proposedMethod" required minlength="2" rows="3"></textarea></label>
      <label>目标场景<textarea v-model="targetScenario" required minlength="2" rows="3"></textarea></label>

      <section class="existing-results">
        <header><div><h3>已有结果</h3><p>全部标记为 user_reported / 未核验。</p></div><button type="button" @click="addExistingResult">＋ 添加</button></header>
        <article v-for="(item, index) in existingResults" :key="index">
          <input v-model="item.label" required placeholder="结果标签" />
          <select v-model="item.result_type">
            <option value="observation">观察</option><option value="quantitative">定量</option>
            <option value="partial">部分结果</option><option value="negative">负结果</option><option value="other">其他</option>
          </select>
          <textarea v-model="item.description" required rows="2" placeholder="只记录你实际已有的内容"></textarea>
          <button type="button" @click="removeExistingResult(index)">删除</button>
        </article>
      </section>
      <button class="save-claim" :disabled="loading">{{ loading ? '处理中' : `保存为 Claim v${expectedLatestVersion + 1} 并诊断` }}</button>
    </form>

    <p v-if="error" class="claim-error">{{ error }}</p>
    <p v-if="notice" class="claim-notice">{{ notice }}</p>

    <section v-if="envelope" class="diagnosis">
      <header class="diagnosis-header">
        <div><p class="claim-eyebrow">MINIMUM EVIDENCE DIAGNOSIS</p><h3>Claim v{{ envelope.claim.version }} · 诊断 r{{ envelope.diagnosis.revision }}</h3></div>
        <div><span>{{ envelope.claim.origin }}</span><span>{{ envelope.diagnosis.origin }}</span><span>{{ envelope.diagnosis.planner_version }}</span></div>
      </header>
      <div class="assessment-boundary">
        <span>可行性：{{ envelope.diagnosis.feasibility_assessment }}</span>
        <span>创新性：{{ envelope.diagnosis.innovation_assessment }}</span>
        <span>语言组织：{{ envelope.diagnosis.language_organizer }}</span>
      </div>

      <div class="requirement-list">
        <article v-for="(item, index) in envelope.diagnosis.requirements" :key="item.requirement_id">
          <header><span>{{ String(index + 1).padStart(2, '0') }}</span><div><b>{{ requirementLabels[item.requirement_type] }}</b><small>{{ item.generated_by_rule }}</small></div><select v-model="item.status"><option value="planned">planned</option><option value="in_progress">in_progress</option><option value="user_reports_evidence_available">user_reports_evidence_available</option><option value="not_applicable">not_applicable</option></select></header>
          <label>验证哪个 Claim<textarea :value="item.validates_claim" readonly rows="3"></textarea></label>
          <label>为什么需要<textarea v-model="item.why_needed" rows="3"></textarea></label>
          <div class="variable-grid">
            <label>自变量<textarea :value="item.independent_variables.join('\n')" rows="4" @input="updateLines(item, 'independent_variables', $event)"></textarea></label>
            <label>控制变量<textarea :value="item.controlled_variables.join('\n')" rows="4" @input="updateLines(item, 'controlled_variables', $event)"></textarea></label>
            <label>输出字段<textarea :value="item.output_fields.join('\n')" rows="4" @input="updateLines(item, 'output_fields', $event)"></textarea></label>
          </div>
          <div class="artifact-editor">
            <label>推荐图表类型<select v-model="item.recommended_artifact.artifact_type"><option value="table">table</option><option value="line_chart">line_chart</option><option value="bar_chart">bar_chart</option><option value="heatmap">heatmap</option><option value="scatter_plot">scatter_plot</option><option value="case_panel">case_panel</option></select></label>
            <label>推荐标题<input v-model="item.recommended_artifact.title" /></label>
            <label>推荐理由<textarea v-model="item.recommended_artifact.rationale" rows="2"></textarea></label>
          </div>
          <div class="proof-grid">
            <label>能支持什么<textarea :value="item.can_support.join('\n')" rows="3" @input="updateLines(item, 'can_support', $event)"></textarea></label>
            <label>不能支持什么<textarea :value="item.cannot_support.join('\n')" rows="3" @input="updateLines(item, 'cannot_support', $event)"></textarea></label>
          </div>
          <label>用户备注<textarea v-model="item.user_notes" rows="2" placeholder="可编辑，但不会变成已验证事实"></textarea></label>
        </article>
      </div>
      <button class="save-diagnosis" :disabled="loading" @click="saveDiagnosis">保存诊断编辑为新修订</button>
    </section>
  </section>
</template>

<style scoped>
.claim-workspace { padding: 85px 6vw; background: #15211c; color: #f6f3e9; }
.claim-heading { display: flex; justify-content: space-between; gap: 35px; align-items: end; }
.claim-heading > div { max-width: 920px; }.claim-heading h2 { margin: 12px 0; font-size: clamp(42px, 5vw, 72px); line-height: 1; letter-spacing: -3px; }.claim-heading h2 em { color: #dfff43; font-style: normal; }.claim-heading p { color: #abb6af; line-height: 1.7; }.claim-heading button, .project-toolbar button, .save-claim, .save-diagnosis { border: 2px solid #f6f3e9; background: #dfff43; color: #17211d; padding: 12px 16px; font-weight: 800; }
.claim-eyebrow { color: #dfff43 !important; font-size: 10px; font-weight: 800; letter-spacing: 2px; }.project-toolbar { display: grid; grid-template-columns: minmax(220px, 1fr) auto auto; gap: 12px; align-items: end; margin-top: 35px; padding: 18px; border: 1px solid #526059; }.project-toolbar label, .claim-form > label, .requirement-list label, .artifact-editor label { display: grid; gap: 7px; color: #c5cec9; font-size: 11px; font-weight: 800; }.project-toolbar input, .claim-form textarea, .claim-form input, .claim-form select, .requirement-list textarea, .requirement-list input, .requirement-list select { min-width: 0; padding: 11px; border: 1px solid #68766e; background: #f7f4ec; color: #17211d; font: inherit; }.project-toolbar span { padding: 12px; color: #abb6af; font-size: 12px; }.version-strip { display: flex; flex-wrap: wrap; gap: 7px; margin: 14px 0; }.version-strip button { border: 1px solid #68766e; background: transparent; color: #dfff43; padding: 8px 10px; }
.claim-form { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 25px; }.claim-form textarea { resize: vertical; line-height: 1.5; }.existing-results { grid-column: 1 / -1; padding: 20px; border: 1px solid #526059; }.existing-results > header { display: flex; justify-content: space-between; align-items: center; }.existing-results h3, .existing-results p { margin: 3px 0; }.existing-results p { color: #abb6af; font-size: 12px; }.existing-results header button { border: 1px solid #dfff43; background: transparent; color: #dfff43; padding: 8px 10px; }.existing-results article { display: grid; grid-template-columns: 1fr 160px 2fr auto; gap: 8px; margin-top: 12px; }.existing-results article button { border: 1px solid #f56a3b; background: transparent; color: #f6a181; }.save-claim { grid-column: 1 / -1; min-height: 52px; }.claim-error, .claim-notice { margin-top: 18px; padding: 14px; }.claim-error { background: #7b2c22; }.claim-notice { background: #294c39; }
.diagnosis { margin-top: 65px; }.diagnosis-header { display: flex; justify-content: space-between; gap: 20px; align-items: end; border-bottom: 2px solid #dfff43; padding-bottom: 18px; }.diagnosis-header h3 { margin: 8px 0 0; font-size: 32px; }.diagnosis-header > div:last-child { display: flex; flex-wrap: wrap; gap: 6px; }.diagnosis-header span, .assessment-boundary span { padding: 6px 8px; border: 1px solid #68766e; color: #c5cec9; font-size: 10px; }.assessment-boundary { display: flex; gap: 8px; margin: 15px 0 25px; }.requirement-list { display: grid; gap: 20px; }.requirement-list > article { padding: 24px; border: 1px solid #526059; background: #1e2a24; }.requirement-list > article > header { display: grid; grid-template-columns: 55px 1fr 170px; gap: 12px; align-items: center; margin-bottom: 20px; }.requirement-list > article > header > span { color: #dfff43; font-size: 28px; }.requirement-list > article > header div { display: grid; gap: 4px; }.requirement-list > article > header b { font-size: 22px; }.requirement-list > article > header small { color: #859188; }.requirement-list > article > label { margin-top: 12px; }.requirement-list textarea[readonly] { background: #dfe1d7; }.variable-grid, .proof-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-top: 12px; }.proof-grid { grid-template-columns: 1fr 1fr; }.artifact-editor { display: grid; grid-template-columns: 180px 1fr 2fr; gap: 10px; margin-top: 12px; }.save-diagnosis { width: 100%; margin-top: 22px; min-height: 50px; }
@media (max-width: 900px) { .claim-heading, .diagnosis-header { display: block; }.claim-heading button { margin-top: 12px; }.claim-form, .variable-grid, .artifact-editor { grid-template-columns: 1fr; }.existing-results article { grid-template-columns: 1fr; }.diagnosis-header > div:last-child { margin-top: 12px; } }
@media (max-width: 640px) { .claim-workspace { padding: 55px 20px; }.project-toolbar, .proof-grid { grid-template-columns: 1fr; }.requirement-list > article { padding: 17px; }.requirement-list > article > header { grid-template-columns: 45px 1fr; }.requirement-list > article > header select { grid-column: 2; }.assessment-boundary { display: grid; } }
</style>
