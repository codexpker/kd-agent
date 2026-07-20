<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'

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
  status: string
  claims: { id: string; claim_type: string; statement: string; evidence_ids: string[] }[]
  experiment_intents: { id: string; title: string; supports_claim_ids: string[]; evidence_ids: string[] }[]
  artifacts: { id: string; label: string; role: string; supports_claim_ids: string[]; evidence_ids: string[] }[]
  evidence: Evidence[]
}
type GraphNode = {
  node_id: string
  node_type: 'paper' | 'claim' | 'experiment' | 'artifact' | 'evidence' | 'narrative_move'
  label: string
  summary: string | null
  local_id: string | null
  verified: boolean | null
}
type GraphEdge = { source_id: string; target_id: string; relationship: string }
type EvidenceGraph = {
  paper_id: string
  source: 'neo4j' | 'gold_snapshot'
  status: 'ready'
  nodes: GraphNode[]
  edges: GraphEdge[]
  warnings: string[]
}
type ChatMessage = {
  id: number
  role: 'assistant' | 'user'
  text: string
  meta?: string
  evidenceIds?: string[]
  origin?: string
}
type TaskStep = { label: string; status: 'pending' | 'running' | 'done' | 'blocked'; detail: string }
type TaskKind = 'paper' | 'opportunity' | 'claim' | 'plot'
type AssistantToolRun = {
  run_id: string
  tool_name: 'paper_deconstruct' | 'document_structure' | 'evidence_graph'
  status: 'succeeded' | 'failed'
  source: string
  result_summary: string
  evidence_ids: string[]
}
type AssistantSession = {
  session_id: string
  trace_id: string
  paper_id: string
  backend: 'offline' | 'astron'
  provider_status: 'ready' | 'unavailable'
  provider_name: string
  model_label: string
  prompt_version: string
  storage: 'process_memory'
  messages: unknown[]
  warnings: string[]
}
type AssistantTurn = {
  status: 'succeeded' | 'error'
  session: AssistantSession
  assistant_message: {
    content: string
    origin: string
    evidence_ids: string[]
  }
  tool_runs: AssistantToolRun[]
  warning: string | null
}

const router = useRouter()
const route = useRoute()
const paperId = 'anomaly-transformer-2022'
const loading = ref(false)
const error = ref('')
const prompt = ref('')
const paper = ref<Paper | null>(null)
const graph = ref<EvidenceGraph | null>(null)
const assistantSession = ref<AssistantSession | null>(null)
const latestToolRuns = ref<AssistantToolRun[]>([])
const selectedNode = ref<GraphNode | null>(null)
const focusedClaimId = ref<string | null>(null)
const sidePanel = ref<'evidence' | 'graph'>(route.query.panel === 'graph' ? 'graph' : 'evidence')
const activeTask = ref('等待任务')
const taskSteps = ref<TaskStep[]>([])
let messageSequence = 2
const messages = ref<ChatMessage[]>([
  {
    id: 1,
    role: 'assistant',
    meta: '科研助理 · 会话尚未创建',
    text: '你好。我会先确认任务和证据边界，再调用结构化科研工具。运行模式由服务端决定；离线回答和模型生成会明确区分。',
  },
])

const quickTasks: { kind: TaskKind; code: string; title: string; description: string }[] = [
  { kind: 'paper', code: '01', title: '拆解一篇论文', description: '查看 Claim、实验意图、图表角色和 EvidenceAnchor。' },
  { kind: 'opportunity', code: '02', title: '分析研究机会', description: '按已核验证据覆盖判断候选或明确证据不足。' },
  { kind: 'claim', code: '03', title: '诊断我的 Claim', description: '录入研究想法并生成八类最小证据需求。' },
  { kind: 'plot', code: '04', title: '生成实验图表', description: '上传真实 CSV/JSON，校验、绘图并保留逐点溯源。' },
]

const evidenceById = computed(
  () => new Map((paper.value?.evidence ?? []).map((item) => [item.id, item])),
)
const selectedEvidence = computed(() => (
  selectedNode.value?.node_type === 'evidence' && selectedNode.value.local_id
    ? evidenceById.value.get(selectedNode.value.local_id) ?? null
    : null
))
const assistantRuntimeLabel = computed(() => {
  if (!assistantSession.value) return '服务端模式待确认'
  if (assistantSession.value.backend === 'offline') return '离线规则 · 本地证据工具'
  if (assistantSession.value.provider_status === 'unavailable') return '星辰工作流 · 配置不可用'
  return `星辰工作流 · ${assistantSession.value.model_label}`
})
const assistantRuntimeDescription = computed(() => {
  if (!assistantSession.value) return '首次拆解任务将创建带 trace_id 的会话，并记录实际工具调用。'
  if (assistantSession.value.backend === 'offline') return '当前会话未调用外部模型；回答由本地工具结果和固定规则组织。'
  if (assistantSession.value.provider_status === 'unavailable') return '当前会话不会降级伪装成模型回答，请检查服务端星辰配置。'
  return '当前会话由星辰工作流组织语言；事实仍必须引用本地 EvidenceAnchor。'
})

const focusedGraph = computed(() => {
  if (!graph.value) return { claim: null, paths: [], directEvidence: [] }
  const claim = graph.value.nodes.find((item) => item.node_type === 'claim' && item.local_id === focusedClaimId.value)
    ?? graph.value.nodes.find((item) => item.node_type === 'claim')
  if (!claim) return { claim: null, paths: [], directEvidence: [] }
  const workIds = new Set(graph.value.edges
    .filter((edge) => edge.relationship === 'SUPPORTS' && edge.target_id === claim.node_id)
    .map((edge) => edge.source_id))
  const evidenceNodes = new Map(
    graph.value.nodes
      .filter((item) => item.node_type === 'evidence')
      .map((item) => [item.node_id, item]),
  )
  const evidenceForNode = (nodeId: string) => graph.value!.edges
    .filter((edge) => edge.relationship === 'SUPPORTED_BY' && edge.source_id === nodeId)
    .flatMap((edge) => {
      const evidence = evidenceNodes.get(edge.target_id)
      return evidence ? [evidence] : []
    })
  return {
    claim,
    paths: graph.value.nodes
      .filter((item) => workIds.has(item.node_id))
      .map((work) => ({ work, evidence: evidenceForNode(work.node_id) })),
    directEvidence: evidenceForNode(claim.node_id),
  }
})

function addMessage(
  role: 'assistant' | 'user',
  text: string,
  meta?: string,
  evidenceIds?: string[],
  origin?: string,
) {
  messages.value.push({ id: messageSequence++, role, text, meta, evidenceIds, origin })
}

async function loadPaperAndGraph() {
  const [paperResponse, graphResponse] = await Promise.all([
    fetch(`/api/v1/tools/paper-deconstruct/${paperId}`, { method: 'POST' }),
    fetch(`/api/v1/papers/${paperId}/evidence-graph`),
  ])
  if (!paperResponse.ok || !graphResponse.ok) throw new Error('论文证据或关系图暂时不可用。')
  paper.value = await paperResponse.json()
  graph.value = await graphResponse.json()
  focusedClaimId.value = paper.value?.claims[1]?.id ?? paper.value?.claims[0]?.id ?? null
  selectedNode.value = graph.value?.nodes.find((item) => item.node_type === 'claim' && item.local_id === focusedClaimId.value) ?? null
}

function focusGraphClaim(claimId: string) {
  focusedClaimId.value = claimId
  selectedNode.value = graph.value?.nodes.find((item) => item.node_type === 'claim' && item.local_id === claimId) ?? null
}

async function ensureAssistantSession() {
  if (assistantSession.value) return assistantSession.value
  const response = await fetch('/api/v1/assistant/sessions', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ paper_id: paperId }),
  })
  if (!response.ok) throw new Error('无法创建论文拆解会话。')
  assistantSession.value = await response.json()
  return assistantSession.value!
}

async function askPaperAssistant(question: string) {
  if (loading.value) return
  loading.value = true
  error.value = ''
  activeTask.value = '拆解一篇论文'
  latestToolRuns.value = []
  setSteps([
    ['建立可追踪会话', '绑定论文、trace_id、提示词版本和运行后端'],
    ['调用本地证据工具', '先取结构化事实，再允许规则或模型组织语言'],
    ['校验证据边界', '模型回答必须引用已存在的 EvidenceAnchor'],
  ])
  taskSteps.value[0].status = 'running'
  try {
    const session = await ensureAssistantSession()
    taskSteps.value[0].status = 'done'
    taskSteps.value[1].status = 'running'
    const response = await fetch(`/api/v1/assistant/sessions/${session.session_id}/messages`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        content: question,
        expected_message_count: session.messages.length,
      }),
    })
    if (response.status === 409) {
      assistantSession.value = await fetch(`/api/v1/assistant/sessions/${session.session_id}`).then((item) => item.json())
      throw new Error('会话历史已变化，请重新发送问题。')
    }
    if (!response.ok) throw new Error('论文拆解会话执行失败。')
    const turn: AssistantTurn = await response.json()
    assistantSession.value = turn.session
    latestToolRuns.value = turn.tool_runs
    taskSteps.value[1].status = turn.tool_runs.every((item) => item.status === 'succeeded') ? 'done' : 'blocked'
    taskSteps.value[2].status = turn.status === 'succeeded' ? 'done' : 'blocked'
    await loadPaperAndGraph()
    sidePanel.value = 'evidence'
    const firstEvidence = turn.assistant_message.evidence_ids[0]
    if (firstEvidence) selectEvidenceById(firstEvidence)
    addMessage(
      'assistant',
      turn.assistant_message.content,
      `${assistantRuntimeLabel.value} · ${turn.session.trace_id.slice(0, 14)}…`,
      turn.assistant_message.evidence_ids,
      turn.assistant_message.origin,
    )
    if (turn.status === 'error') error.value = turn.warning ?? '模型回答未通过证据校验。'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
    const running = taskSteps.value.find((item) => item.status === 'running')
    if (running) running.status = 'blocked'
    addMessage('assistant', error.value, '执行失败', [], 'system_error')
  } finally {
    loading.value = false
  }
}

function setSteps(items: Array<[string, string]>) {
  taskSteps.value = items.map(([label, detail]) => ({ label, detail, status: 'pending' }))
}

async function runTask(kind: TaskKind, fromPrompt = false) {
  if (loading.value) return
  const task = quickTasks.find((item) => item.kind === kind)!
  if (!fromPrompt) addMessage('user', task.title)
  activeTask.value = task.title
  error.value = ''

  if (kind === 'paper') {
    await askPaperAssistant(task.title)
    return
  }

  if (kind === 'claim' || kind === 'plot') {
    setSteps([
      ['进入专业工作区', '保留结构化字段和版本历史'],
      ['完成用户输入', kind === 'claim' ? '系统不会改写为论文事实' : '只接受用户主动上传的 CSV/JSON'],
      ['执行并审核', kind === 'claim' ? '生成最小证据需求' : '成功执行后才展示图表'],
    ])
    taskSteps.value[0].status = 'done'
    taskSteps.value[1].status = 'pending'
    addMessage(
      'assistant',
      kind === 'claim'
        ? 'Claim 诊断需要用户提供研究问题、假设、方法和目标场景。我已为你定位到版本化录入工作区。'
        : '绘图必须绑定 ExperimentPlan 和用户上传数据。我已为你定位到实验与图表工作区，不会自动补造任何结果。',
      '结构化任务导航',
    )
    await router.push({ path: '/workspace', hash: '#project-claim' })
    return
  }

  loading.value = true
  try {
    if (kind === 'opportunity') {
      setSteps([
        ['建立查询计划', '限定 TAD 主题和最少两篇已审核论文'],
        ['应用纳入/排除规则', '排队论文不参与证据聚合'],
        ['检查覆盖范围', '不足时返回 insufficient_evidence'],
      ])
      taskSteps.value[0].status = 'running'
      const response = await fetch('/api/v1/research/opportunities', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ query: 'time series anomaly detection', minimum_evidence_papers: 2 }),
      })
      if (!response.ok) throw new Error('研究机会分析暂时不可用。')
      const result = await response.json()
      taskSteps.value[0].status = 'done'
      taskSteps.value[1].status = 'done'
      taskSteps.value[2].status = result.status === 'insufficient_evidence' ? 'blocked' : 'done'
      addMessage(
        'assistant',
        result.status === 'insufficient_evidence'
          ? '当前真实离线语料不足以覆盖至少两篇已审核、已核验证据论文，因此返回 insufficient_evidence。系统没有使用排队论文或合成数据伪造研究机会。'
          : `已生成 ${result.candidates.length} 个 Research Opportunity Candidate，请逐项核对支持和冲突证据。`,
        `规则结果 · ${result.status}`,
      )
    }
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '未知错误'
    const running = taskSteps.value.find((item) => item.status === 'running')
    if (running) running.status = 'blocked'
    addMessage('assistant', error.value, '执行失败')
  } finally {
    loading.value = false
  }
}

async function submitPrompt() {
  const value = prompt.value.trim()
  if (!value) return
  addMessage('user', value)
  prompt.value = ''
  const normalized = value.toLowerCase()
  if (/论文|anomaly|transformer|evidenceanchor|figure|table|图表角色|实验意图|消融实验|证据链/.test(normalized)) return askPaperAssistant(value)
  if (/图表|绘图|csv|json|plot/.test(normalized)) return runTask('plot', true)
  if (/claim|假设|实验设计|证据需求/.test(normalized)) return runTask('claim', true)
  if (/机会|选题|创新|前沿/.test(normalized)) return runTask('opportunity', true)
  if (/证据|拆解/.test(normalized)) return askPaperAssistant(value)
  addMessage(
    'assistant',
    '我还不能可靠判断你要执行哪类科研任务。请补充是“拆解论文、分析研究机会、诊断 Claim”还是“上传数据生成图表”。这是离线规则导航的能力边界。',
    '需要澄清',
  )
}

function selectEvidence(evidence: Evidence) {
  selectedNode.value = graph.value?.nodes.find(
    (item) => item.node_type === 'evidence' && item.local_id === evidence.id,
  ) ?? null
  sidePanel.value = 'evidence'
}

function selectEvidenceById(evidenceId: string) {
  const evidence = evidenceById.value.get(evidenceId)
  if (evidence) selectEvidence(evidence)
}

watch(
  () => route.query.panel,
  (panel) => {
    if (panel === 'graph') sidePanel.value = 'graph'
  },
)

onMounted(async () => {
  try {
    await loadPaperAndGraph()
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '初始化失败'
  }
})
</script>

<template>
  <main class="assistant-view" data-testid="assistant-shell">
    <section class="assistant-main">
      <header class="assistant-hero">
        <div>
          <p>EVIDENCE-GROUNDED RESEARCH COPILOT</p>
          <h1>让对话推进科研任务，<br /><em>让证据约束每一步。</em></h1>
          <span>{{ assistantRuntimeDescription }}</span>
        </div>
        <button data-testid="run-evidence-demo" :disabled="loading" @click="runTask('paper')">
          {{ loading ? '执行中…' : '启动证据链演示' }}
        </button>
      </header>

      <section class="quick-task-grid" aria-label="科研任务入口">
        <button v-for="item in quickTasks" :key="item.kind" :data-testid="`quick-task-${item.kind}`" @click="runTask(item.kind)">
          <span>{{ item.code }}</span><b>{{ item.title }}</b><p>{{ item.description }}</p><i>→</i>
        </button>
      </section>

      <section class="conversation-card">
        <header><div><i></i><b>科研助理</b></div><span data-testid="assistant-runtime">{{ assistantRuntimeLabel }}</span></header>
        <div class="message-list" aria-live="polite">
          <article v-for="message in messages" :key="message.id" :class="message.role">
            <small>{{ message.meta ?? (message.role === 'user' ? '你' : '科研助理') }}</small>
            <p>{{ message.text }}</p>
            <div v-if="message.evidenceIds?.length" class="chat-evidence">
              <button v-for="evidenceId in message.evidenceIds" :key="evidenceId" @click="selectEvidenceById(evidenceId)">{{ evidenceId }}</button>
            </div>
          </article>
        </div>
        <form class="assistant-prompt" @submit.prevent="submitPrompt">
          <textarea v-model="prompt" aria-label="科研任务输入" rows="3" placeholder="例如：拆解 Anomaly Transformer，并告诉我每个 Claim 由哪些证据支持"></textarea>
          <footer><span>论文问答记录 trace_id 与工具调用 · 证据不足时明确停止</span><button :disabled="loading || !prompt.trim()">发送任务</button></footer>
        </form>
      </section>
      <p v-if="error" class="assistant-error">{{ error }}</p>
    </section>

    <aside class="research-inspector">
      <section class="task-status">
        <header><div><p>CURRENT TASK</p><h2>{{ activeTask }}</h2></div><span>{{ taskSteps.length ? `${taskSteps.filter((item) => item.status === 'done').length}/${taskSteps.length}` : 'IDLE' }}</span></header>
        <ol v-if="taskSteps.length">
          <li v-for="(step, index) in taskSteps" :key="step.label" :class="step.status">
            <i>{{ index + 1 }}</i><div><b>{{ step.label }}</b><small>{{ step.detail }}</small></div><span>{{ step.status }}</span>
          </li>
        </ol>
        <p v-else class="empty-task">选择一个任务后，这里会显示实际执行步骤，而不是只返回一段聊天文本。</p>
        <div v-if="latestToolRuns.length" class="tool-run-log" data-testid="assistant-tool-runs">
          <p>TOOL RUNS</p>
          <article v-for="run in latestToolRuns" :key="run.run_id">
            <span>{{ run.status }}</span><div><b>{{ run.tool_name }}</b><small>{{ run.source }} · {{ run.result_summary }}</small></div>
          </article>
        </div>
        <footer v-if="assistantSession" data-testid="assistant-trace">
          <span>{{ assistantSession.trace_id }}</span><small>{{ assistantSession.prompt_version }} · {{ assistantSession.storage }}</small>
        </footer>
      </section>

      <section class="evidence-inspector">
        <header>
          <button :class="{ active: sidePanel === 'evidence' }" @click="sidePanel = 'evidence'">证据</button>
          <button :class="{ active: sidePanel === 'graph' }" @click="sidePanel = 'graph'">关系图</button>
          <span v-if="graph" data-testid="graph-source">{{ graph.source }}</span>
        </header>

        <div v-if="sidePanel === 'evidence'" class="evidence-panel">
          <template v-if="selectedEvidence">
            <div class="selection-label"><span>{{ selectedEvidence.kind }}</span><b>{{ selectedEvidence.verified ? '已人工核验' : '开发注释待复核' }}</b></div>
            <h3>{{ selectedEvidence.label }}</h3>
            <blockquote>{{ selectedEvidence.excerpt }}</blockquote>
            <p>这是中文开发注释，不是论文原句；真实自动解析页图请在论文逆向工程阅读器中查看。</p>
          </template>
          <template v-else>
            <h3>{{ selectedNode?.label ?? '证据检查器' }}</h3>
            <p>{{ selectedNode?.summary ?? '选择右侧关系图节点或下方 EvidenceAnchor。' }}</p>
          </template>
          <div class="evidence-list">
            <button v-for="item in paper?.evidence.slice(0, 6)" :key="item.id" @click="selectEvidence(item)">
              <span>{{ item.id }}</span><div><b>{{ item.label }}</b><small>{{ item.verified ? '已人工核验' : '开发注释待复核' }}</small></div>
            </button>
          </div>
          <RouterLink :to="`/papers/${paperId}`" data-testid="open-paper-reader">打开论文逆向工程阅读器 →</RouterLink>
        </div>

        <div v-else class="graph-panel">
          <div class="graph-legend"><span class="claim">Claim</span><span class="work">Experiment / Artifact</span><span class="evidence">Evidence</span></div>
          <div class="assistant-graph-focus"><b>只查看一个 Claim 的证据闭环</b><button v-for="claim in paper?.claims" :key="claim.id" :class="{ active: focusedClaimId === claim.id }" @click="focusGraphClaim(claim.id)">{{ claim.id }}</button></div>
          <div class="graph-paths" data-testid="evidence-graph">
            <article v-if="focusedGraph.claim" class="focused-claim-card">
              <small>当前 Claim · {{ focusedGraph.claim.local_id }}</small>
              <b>{{ focusedGraph.claim.label }}</b>
            </article>
            <article v-for="path in focusedGraph.paths" :key="path.work.node_id" class="graph-path-card" data-testid="assistant-graph-path">
              <header><span>{{ path.work.node_type === 'experiment' ? '实验' : '图表' }}</span><b>{{ path.work.local_id }} · {{ path.work.label }}</b></header>
              <p>{{ path.work.summary }}</p>
              <div class="path-relation"><i>支撑当前 Claim</i><span>→</span><i>依据 {{ path.evidence.length }} 条 EvidenceAnchor</i></div>
              <div class="path-evidence"><button v-for="evidence in path.evidence" :key="evidence.node_id" @click="selectedNode = evidence; sidePanel = 'evidence'">{{ evidence.local_id }} · {{ evidence.label }}</button></div>
            </article>
            <article class="direct-evidence-card">
              <b>Claim 直接依据</b>
              <button v-for="evidence in focusedGraph.directEvidence" :key="evidence.node_id" @click="selectedNode = evidence; sidePanel = 'evidence'">{{ evidence.local_id }} · {{ evidence.label }}</button>
            </article>
          </div>
          <p v-if="graph">当前显示 {{ focusedGraph.paths.length }} 条实验/图表支撑路径；完整索引含 {{ graph.nodes.length }} 个节点。MySQL 仍是权威事实源，Neo4j 只是可重建关系索引。</p>
          <p v-for="warning in graph?.warnings" :key="warning" class="graph-warning">{{ warning }}</p>
        </div>
      </section>
    </aside>
  </main>
</template>

<style scoped>
.assistant-view { max-width: none; display: grid; grid-template-columns: minmax(520px, 1.35fr) minmax(390px, .8fr); min-height: calc(100vh - 66px); background: #f4f6f3; }
.assistant-main { min-width: 0; padding: 45px clamp(24px, 4vw, 65px) 70px; }.assistant-hero { display: flex; justify-content: space-between; gap: 30px; align-items: end; }.assistant-hero > div { max-width: 780px; }.assistant-hero p { color: #678075; font-size: 10px; font-weight: 900; letter-spacing: 2px; }.assistant-hero h1 { margin: 12px 0 18px; color: #173126; font-size: clamp(38px, 4.6vw, 68px); line-height: 1.02; letter-spacing: -3px; }.assistant-hero h1 em { color: #ef683e; font-style: normal; }.assistant-hero span { color: #708079; font-size: 12px; }.assistant-hero > button { min-width: 160px; padding: 13px 16px; border: 0; border-radius: 10px; background: #205c45; color: white; font-weight: 800; box-shadow: 0 8px 22px rgba(32,92,69,.2); }
.quick-task-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-top: 32px; }.quick-task-grid button { min-height: 150px; display: grid; grid-template-columns: 1fr auto; align-content: start; gap: 7px; padding: 16px; border: 1px solid #dbe2dd; border-radius: 14px; background: #fff; color: #1d3429; text-align: left; transition: .18s; }.quick-task-grid button:hover { transform: translateY(-3px); border-color: #8fb5a2; box-shadow: 0 10px 25px rgba(23,49,38,.08); }.quick-task-grid button > span { color: #ef683e; font-size: 10px; font-weight: 900; }.quick-task-grid button > b { grid-column: 1 / -1; font-size: 14px; }.quick-task-grid button p { grid-column: 1 / -1; margin: 3px 0; color: #748179; font-size: 11px; line-height: 1.5; }.quick-task-grid button i { grid-column: 2; color: #205c45; font-style: normal; font-size: 20px; }
.conversation-card { margin-top: 20px; overflow: hidden; border: 1px solid #dbe2dd; border-radius: 16px; background: white; box-shadow: 0 14px 40px rgba(28,55,43,.06); }.conversation-card > header { display: flex; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #edf0ed; }.conversation-card > header div { display: flex; align-items: center; gap: 8px; }.conversation-card > header i { width: 9px; height: 9px; border-radius: 50%; background: #52a574; }.conversation-card > header b { font-size: 12px; }.conversation-card > header span { color: #8a968f; font-size: 10px; }.message-list { min-height: 245px; max-height: 440px; overflow-y: auto; padding: 22px; background: linear-gradient(180deg,#fbfcfb,#f4f7f4); }.message-list article { max-width: 82%; margin-bottom: 15px; padding: 13px 15px; border-radius: 4px 14px 14px 14px; background: white; box-shadow: 0 4px 14px rgba(33,57,46,.05); }.message-list article.user { margin-left: auto; border-radius: 14px 4px 14px 14px; background: #dfeee6; }.message-list small { color: #718078; font-size: 9px; font-weight: 800; }.message-list p { margin: 6px 0 0; color: #263b31; font-size: 13px; line-height: 1.65; white-space: pre-wrap; }.assistant-prompt { margin: 14px; border: 1px solid #cad5ce; border-radius: 12px; }.assistant-prompt textarea { width: 100%; resize: vertical; padding: 15px; border: 0; outline: 0; background: transparent; color: #20372c; font: inherit; line-height: 1.5; }.assistant-prompt footer { display: flex; justify-content: space-between; align-items: center; padding: 9px 10px 10px 15px; background: transparent; font-weight: normal; }.assistant-prompt footer span { color: #8a968f; font-size: 9px; }.assistant-prompt button { padding: 9px 15px; border: 0; border-radius: 8px; background: #205c45; color: white; font-weight: 800; }.assistant-prompt button:disabled { opacity: .45; }.assistant-error { padding: 12px; border-left: 4px solid #ef683e; background: #ffe1d5; color: #943b21; }
.chat-evidence { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 10px; }.chat-evidence button { padding: 4px 7px; border: 1px solid #b9ccc1; border-radius: 99px; background: #edf5f0; color: #275e47; font-size: 8px; font-weight: 900; }
.research-inspector { min-width: 0; padding: 28px; border-left: 1px solid #dfe4df; background: #eef2ee; }.task-status, .evidence-inspector { border: 1px solid #d8e0da; border-radius: 14px; background: white; }.task-status { padding: 18px; }.task-status > header { display: flex; justify-content: space-between; align-items: center; }.task-status header p { margin: 0; color: #8c9992; font-size: 9px; letter-spacing: 1.3px; }.task-status h2 { margin: 5px 0 0; font-size: 18px; }.task-status header > span { padding: 6px 8px; border-radius: 99px; background: #e6efe9; color: #2a634b; font-size: 9px; font-weight: 900; }.task-status ol { display: grid; gap: 7px; margin: 16px 0 0; padding: 0; list-style: none; }.task-status li { display: grid; grid-template-columns: 27px 1fr auto; gap: 9px; align-items: center; padding: 10px; border-radius: 9px; background: #f4f6f3; }.task-status li > i { display: grid; place-items: center; width: 24px; height: 24px; border: 1px solid #cbd5ce; border-radius: 50%; font-style: normal; font-size: 9px; }.task-status li div { display: grid; gap: 2px; }.task-status li b { font-size: 11px; }.task-status li small { color: #849089; font-size: 9px; }.task-status li > span { color: #849089; font-size: 8px; text-transform: uppercase; }.task-status li.done > i { border-color: #4a9c6c; background: #4a9c6c; color: white; }.task-status li.running { background: #fff5d8; }.task-status li.blocked { background: #ffe5dc; }.empty-task { color: #79867e; font-size: 11px; line-height: 1.6; }
.tool-run-log { display: grid; gap: 6px; margin-top: 14px; padding-top: 12px; border-top: 1px solid #e4e9e5; }.tool-run-log > p { margin: 0 0 3px; color: #8c9992; font-size: 8px; font-weight: 900; letter-spacing: 1.2px; }.tool-run-log article { display: grid; grid-template-columns: 54px 1fr; gap: 8px; padding: 8px; border-radius: 8px; background: #eef4f0; }.tool-run-log article > span { align-self: start; padding: 4px 5px; border-radius: 99px; background: #d8eadf; color: #26704c; font-size: 7px; font-weight: 900; text-align: center; text-transform: uppercase; }.tool-run-log article div { display: grid; gap: 2px; }.tool-run-log article b { font-size: 9px; }.tool-run-log article small { color: #7b8881; font-size: 8px; line-height: 1.4; }.task-status > footer { display: grid; gap: 3px; margin-top: 12px; padding: 10px 0 0; border-top: 1px solid #e4e9e5; background: transparent; font-weight: normal; }.task-status > footer span { overflow: hidden; color: #315d49; font-size: 8px; font-family: monospace; text-overflow: ellipsis; white-space: nowrap; }.task-status > footer small { color: #89958e; font-size: 7px; }
.evidence-inspector { margin-top: 16px; overflow: hidden; }.evidence-inspector > header { display: flex; align-items: center; padding: 8px; border-bottom: 1px solid #e4e9e5; }.evidence-inspector > header button { padding: 8px 12px; border: 0; border-radius: 8px; background: transparent; color: #718078; font-size: 11px; font-weight: 800; }.evidence-inspector > header button.active { background: #dfeee6; color: #205c45; }.evidence-inspector > header span { margin-left: auto; padding: 5px 7px; border: 1px solid #d4ddd7; border-radius: 99px; color: #6d7a72; font-size: 8px; }.evidence-panel, .graph-panel { padding: 18px; }.selection-label { display: flex; justify-content: space-between; }.selection-label span, .selection-label b { padding: 5px 7px; border-radius: 99px; background: #eef2ee; font-size: 8px; }.selection-label b { background: #ffe6dc; color: #a34224; }.evidence-panel h3 { margin: 14px 0 8px; font-size: 17px; line-height: 1.35; }.evidence-panel > p { color: #718078; font-size: 10px; line-height: 1.5; }.evidence-panel blockquote { margin: 13px 0; padding: 12px; border-left: 3px solid #ef683e; background: #f5f6f2; color: #43544b; font: 13px/1.6 Georgia,serif; }.evidence-list { display: grid; gap: 5px; margin: 17px 0; }.evidence-list button { display: grid; grid-template-columns: 34px 1fr; gap: 8px; padding: 9px; border: 1px solid #e1e6e2; border-radius: 8px; background: white; text-align: left; }.evidence-list button > span { color: #ef683e; font-size: 9px; font-weight: 900; }.evidence-list button div { display: grid; gap: 2px; }.evidence-list b { overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.evidence-list small { color: #909b94; font-size: 8px; }.evidence-panel > a { color: #205c45; font-size: 10px; font-weight: 800; text-decoration: none; }
.graph-legend { display: flex; flex-wrap: wrap; gap: 5px; }.graph-legend span { padding: 4px 6px; border-radius: 99px; font-size: 8px; }.graph-legend .claim { background: #dfff43; }.graph-legend .work { background: #ffd7c9; }.graph-legend .evidence { background: #dce8ff; }.assistant-graph-focus { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin-top: 10px; padding: 9px; border-radius: 8px; background: #f1f5f2; }.assistant-graph-focus b { margin-right: 5px; color: #66766d; font-size: 8px; }.assistant-graph-focus button { padding: 5px 7px; border: 1px solid #cbd6cf; border-radius: 99px; background: white; color: #52645a; font-size: 8px; }.assistant-graph-focus button.active { border-color: #205c45; background: #205c45; color: white; }.graph-paths { display: grid; gap: 8px; max-height: 520px; margin-top: 12px; overflow-y: auto; }.focused-claim-card, .graph-path-card, .direct-evidence-card { padding: 11px; border: 1px solid #dfe6e1; border-radius: 9px; background: #fbfcfb; }.focused-claim-card { border-color: #bdd75c; background: #f6ffd2; }.focused-claim-card small { display: block; color: #698024; font-size: 8px; }.focused-claim-card b { display: block; margin-top: 5px; color: #344218; font-size: 10px; line-height: 1.45; }.graph-path-card header { display: flex; gap: 7px; align-items: center; }.graph-path-card header span { padding: 4px 6px; border-radius: 5px; background: #ffe3d9; color: #91482e; font-size: 7px; }.graph-path-card header b { font-size: 9px; }.graph-path-card > p { margin: 7px 0; color: #66756d; font-size: 8px; line-height: 1.45; }.graph-path-card .path-relation { display: flex; gap: 5px; align-items: center; color: #718078; }.graph-path-card .path-relation i { font-size: 7px; font-style: normal; }.graph-path-card .path-evidence, .direct-evidence-card { display: flex; flex-wrap: wrap; gap: 5px; }.graph-path-card .path-evidence { margin-top: 8px; }.graph-path-card .path-evidence button, .direct-evidence-card button { padding: 5px 6px; border: 1px solid #bbc9df; border-radius: 6px; background: #edf2fc; color: #49617e; font-size: 7px; }.direct-evidence-card > b { width: 100%; color: #607268; font-size: 8px; }.graph-panel > p { color: #718078; font-size: 9px; line-height: 1.45; }.graph-warning { padding-left: 8px; border-left: 2px solid #ef683e; }
@media (max-width: 1250px) { .assistant-view { grid-template-columns: 1fr; }.research-inspector { display: grid; grid-template-columns: .8fr 1.2fr; gap: 15px; border-left: 0; border-top: 1px solid #dfe4df; }.evidence-inspector { margin-top: 0; }.quick-task-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 720px) { .assistant-main { padding: 30px 18px 45px; }.assistant-hero { display: grid; }.quick-task-grid, .research-inspector { grid-template-columns: 1fr; }.research-inspector { padding: 18px; }.message-list article { max-width: 95%; } }
</style>
