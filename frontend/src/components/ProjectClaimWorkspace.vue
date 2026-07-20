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
type PlanStatus = 'suggested' | 'confirmed' | 'modified' | 'rejected'
type DatasetPlan = {
  dataset_id: string
  role: 'primary' | 'robustness' | 'external_validation'
  split_protocol: string
  preprocessing_fit_scope: 'training_only' | 'full_dataset' | 'unspecified'
  temporal_order: 'preserved' | 'not_applicable' | 'violated' | 'unspecified'
}
type BaselinePlan = {
  baseline_id: string
  label: string
  strength_rationale: string
  implementation_source: string
  status: 'included' | 'excluded'
}
type MetricPlan = {
  name: string
  direction: 'higher_is_better' | 'lower_is_better' | 'descriptive'
  applies_to: 'all_methods' | 'proposed_method_only' | 'baselines_only'
}
type ExperimentPlan = {
  experiment_id: string
  claim_version_ids: string[]
  research_questions: string[]
  hypotheses: string[]
  datasets: DatasetPlan[]
  baselines: BaselinePlan[]
  variables: { independent: string[]; dependent: string[]; nuisance: string[] }
  controls: {
    data_split: string
    preprocessing: string
    tuning_budget: string
    compute_budget: string
    evaluation_protocol: string
    applies_equally: 'planned' | 'not_planned' | 'unspecified'
  }
  metrics: MetricPlan[]
  expected_artifact_ids: string[]
  boundary: {
    applicability_conditions: string[]
    can_support: string[]
    cannot_support: string[]
    stop_conditions: string[]
  }
  status: PlanStatus
  generated_by_requirement_ids: string[]
}
type ArtifactPlan = {
  artifact_id: string
  source_experiment_ids: string[]
  artifact_kind: 'figure' | 'table'
  form_reason: string
  x_axis: string | null
  y_axis: string | null
  rows: string[]
  columns: string[]
  data_fields: string[]
  supports_claim_version_ids: string[]
  common_misreadings: string[]
  status: PlanStatus
}
type QualityCheck = {
  check_type: string
  status: 'pass' | 'warning' | 'error'
  experiment_id: string
  message: string
  remediation: string
  rule_id: string
}
type ExperimentPlanBundle = {
  plan_id: string
  plan_revision_id: string
  revision: number
  origin: 'rule_generated' | 'user_edited'
  claim_references: Array<{ claim_version_id: string; version: number }>
  generation_basis: {
    planner_version: string
    diagnosis_versions: Array<{ claim_version_id: string; diagnosis_id: string; diagnosis_revision: number }>
    source_requirement_ids: string[]
    rule_ids: string[]
    result_policy: 'plan_only_no_results_or_expected_values'
  }
  experiments: ExperimentPlan[]
  artifacts: ArtifactPlan[]
  quality_report: { checker_version: string; checks: QualityCheck[]; has_errors: boolean }
  created_at: string
}

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
const selectedClaimVersions = ref<number[]>([])
const experimentPlan = ref<ExperimentPlanBundle | null>(null)
const experimentPlanHistory = ref<ExperimentPlanBundle[]>([])

const expectedLatestVersion = computed(
  () => history.value.at(-1)?.version ?? 0,
)
const expectedLatestPlanRevision = computed(
  () => experimentPlanHistory.value.at(-1)?.revision ?? 0,
)
const planIssues = computed(
  () => experimentPlan.value?.quality_report.checks.filter((item) => item.status !== 'pass') ?? [],
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
      if (!selectedClaimVersions.value.length) {
        selectedClaimVersions.value = [history.value.at(-1)!.version]
      }
      await loadVersion(history.value.at(-1)!.version)
      await loadExperimentPlanHistory()
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
  if (response.ok) {
    history.value = (await response.json()).versions
    if (!selectedClaimVersions.value.length && history.value.length) {
      selectedClaimVersions.value = [history.value.at(-1)!.version]
    }
  }
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

function eventLines(event: Event): string[] {
  return (event.target as HTMLTextAreaElement).value
    .split('\n')
    .map((item) => item.trim())
    .filter(Boolean)
}

async function loadExperimentPlanHistory() {
  const response = await fetch(
    `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/experiment-plans`,
  )
  if (!response.ok) throw new Error('实验计划历史加载失败。')
  experimentPlanHistory.value = (await response.json()).revisions
  if (experimentPlanHistory.value.length) {
    experimentPlan.value = experimentPlanHistory.value.at(-1)!
  }
}

async function loadExperimentPlanRevision(revision: number) {
  const response = await fetch(
    `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/experiment-plans/${revision}`,
  )
  if (!response.ok) throw new Error(`实验计划 r${revision} 加载失败。`)
  experimentPlan.value = await response.json()
}

async function generateExperimentPlan() {
  if (!selectedClaimVersions.value.length) {
    error.value = '请至少选择一个 Claim 版本。'
    return
  }
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const response = await fetch(
      `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/experiment-plans`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_latest_revision: expectedLatestPlanRevision.value,
          claim_versions: selectedClaimVersions.value,
        }),
      },
    )
    if (!response.ok) {
      throw new Error(response.status === 409 ? '计划已有更新，请重新加载历史。' : '计划生成失败。')
    }
    experimentPlan.value = await response.json()
    await loadExperimentPlanHistory()
    notice.value = `已生成实验与图表计划 r${experimentPlan.value!.revision}；未生成任何实验结果或预期数值。`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}

async function saveExperimentPlan() {
  if (!experimentPlan.value) return
  loading.value = true
  error.value = ''
  notice.value = ''
  try {
    const current = experimentPlan.value
    const response = await fetch(
      `/api/v1/research/projects/${encodeURIComponent(projectId.value)}/experiment-plans/${current.revision}`,
      {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          expected_revision: current.revision,
          experiments: current.experiments,
          artifacts: current.artifacts,
        }),
      },
    )
    if (!response.ok) {
      throw new Error(response.status === 409 ? '计划已有更新，请重新加载历史。' : '计划编辑无效。')
    }
    experimentPlan.value = await response.json()
    await loadExperimentPlanHistory()
    notice.value = `计划编辑已保存为 r${experimentPlan.value!.revision}，质量检查已重新计算。`
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
  } finally {
    loading.value = false
  }
}

function addBaseline(experiment: ExperimentPlan) {
  experiment.baselines.push({
    baseline_id: `baseline-${experiment.baselines.length + 1}`,
    label: '',
    strength_rationale: '',
    implementation_source: '',
    status: 'included',
  })
  experiment.status = 'modified'
}

function addMetric(experiment: ExperimentPlan) {
  experiment.metrics.push({ name: '', direction: 'descriptive', applies_to: 'all_methods' })
  experiment.status = 'modified'
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

    <section v-if="history.length" class="experiment-planning">
      <header class="plan-heading">
        <div>
          <p class="claim-eyebrow">EXECUTABLE EXPERIMENT & ARTIFACT PLAN</p>
          <h3>把证据缺口变成可审查的执行计划</h3>
          <p>选择一个或多个 Claim 版本。RQ 与 Hypothesis 保持用户原文；计划只定义配置、产物和解释边界。</p>
        </div>
        <div class="claim-selector">
          <label v-for="item in history" :key="item.claim_version_id">
            <input v-model="selectedClaimVersions" type="checkbox" :value="item.version" /> Claim v{{ item.version }}
          </label>
          <button type="button" :disabled="loading" @click="generateExperimentPlan">
            生成计划 r{{ expectedLatestPlanRevision + 1 }}
          </button>
        </div>
      </header>

      <div v-if="experimentPlanHistory.length" class="version-strip plan-revisions">
        <button
          v-for="item in experimentPlanHistory"
          :key="item.plan_revision_id"
          type="button"
          @click="loadExperimentPlanRevision(item.revision)"
        >
          r{{ item.revision }} · {{ item.origin }}
        </button>
      </div>

      <template v-if="experimentPlan">
        <div class="plan-meta">
          <span>计划 r{{ experimentPlan.revision }}</span>
          <span>{{ experimentPlan.origin }}</span>
          <span>{{ experimentPlan.generation_basis.planner_version }}</span>
          <span>{{ experimentPlan.generation_basis.result_policy }}</span>
        </div>

        <section class="quality-report">
          <header>
            <div><h4>计划质量检查</h4><p>{{ experimentPlan.quality_report.checker_version }}</p></div>
            <strong :class="{ danger: experimentPlan.quality_report.has_errors }">
              {{ planIssues.length }} 项需处理
            </strong>
          </header>
          <p v-if="!planIssues.length" class="quality-pass">五类检查均通过；这不代表实验可行或 Claim 成立。</p>
          <article v-for="item in planIssues" :key="`${item.experiment_id}:${item.check_type}`" :class="item.status">
            <b>{{ item.status }} · {{ item.check_type }}</b>
            <span>{{ item.message }}</span>
            <small>{{ item.remediation }}</small>
          </article>
        </section>

        <div class="experiment-list">
          <article v-for="(item, experimentIndex) in experimentPlan.experiments" :key="item.experiment_id">
            <header>
              <div><span>{{ String(experimentIndex + 1).padStart(2, '0') }}</span><h4>{{ item.experiment_id.split(':').at(-1) }}</h4></div>
              <select v-model="item.status">
                <option value="suggested">suggested</option><option value="confirmed">confirmed</option>
                <option value="modified">modified</option><option value="rejected">rejected</option>
              </select>
            </header>
            <div class="source-text">
              <label>RQ（用户原文）<textarea :value="item.research_questions.join('\n')" readonly rows="3"></textarea></label>
              <label>Hypothesis（用户原文）<textarea :value="item.hypotheses.join('\n')" readonly rows="3"></textarea></label>
            </div>

            <section class="plan-subsection">
              <h5>Dataset</h5>
              <div v-for="dataset in item.datasets" :key="dataset.dataset_id" class="dataset-grid">
                <label>Dataset ID<input v-model="dataset.dataset_id" /></label>
                <label>角色<select v-model="dataset.role"><option value="primary">primary</option><option value="robustness">robustness</option><option value="external_validation">external_validation</option></select></label>
                <label>预处理拟合范围<select v-model="dataset.preprocessing_fit_scope"><option value="training_only">training_only</option><option value="full_dataset">full_dataset</option><option value="unspecified">unspecified</option></select></label>
                <label>时间顺序<select v-model="dataset.temporal_order"><option value="preserved">preserved</option><option value="not_applicable">not_applicable</option><option value="violated">violated</option><option value="unspecified">unspecified</option></select></label>
                <label class="wide">切分协议<textarea v-model="dataset.split_protocol" rows="2"></textarea></label>
              </div>
            </section>

            <section class="plan-subsection">
              <header><h5>Baseline</h5><button type="button" @click="addBaseline(item)">＋ 添加基线</button></header>
              <div v-for="(baseline, baselineIndex) in item.baselines" :key="`${baseline.baseline_id}:${baselineIndex}`" class="baseline-grid">
                <label>ID<input v-model="baseline.baseline_id" /></label>
                <label>名称<input v-model="baseline.label" /></label>
                <label>状态<select v-model="baseline.status"><option value="included">included</option><option value="excluded">excluded</option></select></label>
                <label>强基线依据<textarea v-model="baseline.strength_rationale" rows="2"></textarea></label>
                <label>实现来源<textarea v-model="baseline.implementation_source" rows="2"></textarea></label>
                <button type="button" @click="item.baselines.splice(baselineIndex, 1); item.status = 'modified'">删除</button>
              </div>
            </section>

            <div class="variable-grid plan-variables">
              <label>Variables · 自变量<textarea :value="item.variables.independent.join('\n')" rows="4" @input="item.variables.independent = eventLines($event)"></textarea></label>
              <label>Variables · 因变量<textarea :value="item.variables.dependent.join('\n')" rows="4" @input="item.variables.dependent = eventLines($event)"></textarea></label>
              <label>Variables · 干扰变量<textarea :value="item.variables.nuisance.join('\n')" rows="4" @input="item.variables.nuisance = eventLines($event)"></textarea></label>
            </div>

            <section class="plan-subsection">
              <h5>Controls</h5>
              <div class="controls-grid">
                <label>数据切分<textarea v-model="item.controls.data_split" rows="2"></textarea></label>
                <label>预处理<textarea v-model="item.controls.preprocessing" rows="2"></textarea></label>
                <label>调参预算<textarea v-model="item.controls.tuning_budget" rows="2"></textarea></label>
                <label>计算预算<textarea v-model="item.controls.compute_budget" rows="2"></textarea></label>
                <label>评价协议<textarea v-model="item.controls.evaluation_protocol" rows="2"></textarea></label>
                <label>是否同等适用<select v-model="item.controls.applies_equally"><option value="planned">planned</option><option value="not_planned">not_planned</option><option value="unspecified">unspecified</option></select></label>
              </div>
            </section>

            <section class="plan-subsection">
              <header><h5>Metrics</h5><button type="button" @click="addMetric(item)">＋ 添加指标</button></header>
              <div v-for="(metric, metricIndex) in item.metrics" :key="metricIndex" class="metric-grid">
                <input v-model="metric.name" placeholder="指标名称" />
                <select v-model="metric.direction"><option value="higher_is_better">higher_is_better</option><option value="lower_is_better">lower_is_better</option><option value="descriptive">descriptive</option></select>
                <select v-model="metric.applies_to"><option value="all_methods">all_methods</option><option value="proposed_method_only">proposed_method_only</option><option value="baselines_only">baselines_only</option></select>
                <button type="button" @click="item.metrics.splice(metricIndex, 1); item.status = 'modified'">删除</button>
              </div>
            </section>

            <section class="plan-subsection boundary-editor">
              <h5>Boundary</h5>
              <div class="proof-grid">
                <label>适用条件<textarea :value="item.boundary.applicability_conditions.join('\n')" rows="3" @input="item.boundary.applicability_conditions = eventLines($event)"></textarea></label>
                <label>能支持<textarea :value="item.boundary.can_support.join('\n')" rows="3" @input="item.boundary.can_support = eventLines($event)"></textarea></label>
                <label>不能支持<textarea :value="item.boundary.cannot_support.join('\n')" rows="3" @input="item.boundary.cannot_support = eventLines($event)"></textarea></label>
                <label>停止解读条件<textarea :value="item.boundary.stop_conditions.join('\n')" rows="3" @input="item.boundary.stop_conditions = eventLines($event)"></textarea></label>
              </div>
            </section>
            <p class="link-note">ExpectedArtifact：{{ item.expected_artifact_ids.join('、') }} · Claim：{{ item.claim_version_ids.join('、') }}</p>
          </article>
        </div>

        <section class="artifact-plans">
          <header><p class="claim-eyebrow">ARTIFACT PLANS</p><h3>Figure / Table 设计</h3></header>
          <article v-for="(artifact, artifactIndex) in experimentPlan.artifacts" :key="artifact.artifact_id">
            <header><b>{{ String(artifactIndex + 1).padStart(2, '0') }} · {{ artifact.artifact_id.split(':').at(-1) }}</b><select v-model="artifact.status"><option value="suggested">suggested</option><option value="confirmed">confirmed</option><option value="modified">modified</option><option value="rejected">rejected</option></select></header>
            <div class="artifact-plan-grid">
              <label>形式<select v-model="artifact.artifact_kind"><option value="figure">Figure</option><option value="table">Table</option></select></label>
              <label class="wide">为什么采用此形式<textarea v-model="artifact.form_reason" rows="2"></textarea></label>
              <template v-if="artifact.artifact_kind === 'figure'">
                <label>横轴<input v-model="artifact.x_axis" /></label><label>纵轴<input v-model="artifact.y_axis" /></label>
              </template>
              <template v-else>
                <label>行设计<textarea :value="artifact.rows.join('\n')" rows="3" @input="artifact.rows = eventLines($event)"></textarea></label>
                <label>列设计<textarea :value="artifact.columns.join('\n')" rows="3" @input="artifact.columns = eventLines($event)"></textarea></label>
              </template>
              <label>数据字段要求<textarea :value="artifact.data_fields.join('\n')" rows="3" @input="artifact.data_fields = eventLines($event)"></textarea></label>
              <label>常见误读<textarea :value="artifact.common_misreadings.join('\n')" rows="3" @input="artifact.common_misreadings = eventLines($event)"></textarea></label>
            </div>
            <p class="link-note">支持 Claim：{{ artifact.supports_claim_version_ids.join('、') }} · 来源 Experiment：{{ artifact.source_experiment_ids.join('、') }}</p>
          </article>
        </section>

        <button class="save-diagnosis save-plan" :disabled="loading" @click="saveExperimentPlan">
          保存确认 / 修改 / 拒绝为新修订并重新检查
        </button>
      </template>
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
.experiment-planning { margin-top: 95px; padding-top: 55px; border-top: 1px solid #526059; }.plan-heading { display: grid; grid-template-columns: 1fr minmax(280px, 420px); gap: 30px; align-items: end; }.plan-heading h3, .artifact-plans > header h3 { margin: 8px 0; font-size: 34px; }.plan-heading p { color: #abb6af; line-height: 1.6; }.claim-selector { display: grid; grid-template-columns: repeat(2, 1fr); gap: 8px; padding: 16px; border: 1px solid #526059; }.claim-selector label { display: flex; gap: 7px; align-items: center; font-size: 12px; }.claim-selector button { grid-column: 1 / -1; padding: 11px; border: 1px solid #dfff43; background: #dfff43; font-weight: 800; }.plan-meta { display: flex; flex-wrap: wrap; gap: 6px; margin: 22px 0; }.plan-meta span { padding: 7px 9px; border: 1px solid #68766e; color: #c5cec9; font-size: 10px; }.quality-report { padding: 20px; border: 1px solid #68766e; background: #111a16; }.quality-report > header { display: flex; justify-content: space-between; align-items: center; }.quality-report h4, .quality-report p { margin: 3px 0; }.quality-report header p { color: #859188; font-size: 11px; }.quality-report strong { color: #dfff43; }.quality-report strong.danger { color: #ff9b76; }.quality-report article { display: grid; grid-template-columns: 210px 1fr; gap: 6px 15px; margin-top: 10px; padding: 11px; border-left: 4px solid #eccb53; background: #22271d; }.quality-report article.error { border-color: #f56a3b; }.quality-report article small { grid-column: 2; color: #abb6af; }.quality-pass { color: #bfe888; }.experiment-list { display: grid; gap: 24px; margin-top: 25px; }.experiment-list > article { padding: 26px; border: 1px solid #526059; background: #1b2721; }.experiment-list > article > header, .plan-subsection > header, .artifact-plans article > header { display: flex; justify-content: space-between; align-items: center; gap: 12px; }.experiment-list > article > header div { display: flex; align-items: center; gap: 13px; }.experiment-list > article > header span { color: #dfff43; font-size: 26px; }.experiment-list h4 { margin: 0; text-transform: uppercase; }.experiment-list select, .experiment-list input, .experiment-list textarea, .artifact-plans select, .artifact-plans input, .artifact-plans textarea { min-width: 0; padding: 10px; border: 1px solid #68766e; background: #f7f4ec; color: #17211d; font: inherit; }.source-text { display: grid; grid-template-columns: 1fr 1fr; gap: 10px; margin-top: 16px; }.source-text label, .plan-subsection label, .plan-variables label, .artifact-plan-grid label { display: grid; gap: 6px; color: #c5cec9; font-size: 11px; font-weight: 800; }.source-text textarea { background: #dfe1d7; }.plan-subsection { margin-top: 18px; padding-top: 15px; border-top: 1px dotted #68766e; }.plan-subsection h5 { margin: 0 0 10px; color: #dfff43; letter-spacing: 1px; }.plan-subsection header button { border: 1px solid #dfff43; background: transparent; color: #dfff43; padding: 7px 9px; }.dataset-grid, .controls-grid, .artifact-plan-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 9px; }.wide { grid-column: 1 / -1; }.baseline-grid { display: grid; grid-template-columns: 1fr 1fr 140px; gap: 9px; margin-top: 9px; }.baseline-grid button, .metric-grid button { border: 1px solid #f56a3b; background: transparent; color: #f6a181; }.metric-grid { display: grid; grid-template-columns: 1fr 190px 200px auto; gap: 8px; margin-top: 8px; }.plan-variables { margin-top: 18px; }.boundary-editor .proof-grid { margin-top: 0; }.link-note { margin: 14px 0 0; color: #859188; font-size: 10px; overflow-wrap: anywhere; }.artifact-plans { margin-top: 55px; }.artifact-plans > article { margin-top: 14px; padding: 22px; border: 1px solid #526059; }.artifact-plan-grid { margin-top: 14px; }.save-plan { background: #f56a3b; border-color: #f56a3b; color: #fff; }
@media (max-width: 900px) { .claim-heading, .diagnosis-header { display: block; }.claim-heading button { margin-top: 12px; }.claim-form, .variable-grid, .artifact-editor { grid-template-columns: 1fr; }.existing-results article { grid-template-columns: 1fr; }.diagnosis-header > div:last-child { margin-top: 12px; } }
@media (max-width: 900px) { .plan-heading, .source-text, .dataset-grid, .controls-grid, .artifact-plan-grid { grid-template-columns: 1fr; }.baseline-grid, .metric-grid { grid-template-columns: 1fr; }.wide { grid-column: auto; }.quality-report article { grid-template-columns: 1fr; }.quality-report article small { grid-column: 1; } }
@media (max-width: 640px) { .claim-workspace { padding: 55px 20px; }.project-toolbar, .proof-grid { grid-template-columns: 1fr; }.requirement-list > article, .experiment-list > article { padding: 17px; }.requirement-list > article > header { grid-template-columns: 45px 1fr; }.requirement-list > article > header select { grid-column: 2; }.assessment-boundary { display: grid; }.claim-selector { grid-template-columns: 1fr; }.quality-report > header { display: block; } }
</style>
