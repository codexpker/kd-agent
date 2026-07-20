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
  claims: { id: string; statement: string; evidence_ids: string[] }[]
  experiment_intents: { id: string; title: string; evidence_ids: string[] }[]
  artifacts: { id: string; label: string; role: string; evidence_ids: string[] }[]
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
type ChatMessage = { id: number; role: 'assistant' | 'user'; text: string; meta?: string }
type TaskStep = { label: string; status: 'pending' | 'running' | 'done' | 'blocked'; detail: string }
type TaskKind = 'paper' | 'opportunity' | 'claim' | 'plot'

const router = useRouter()
const route = useRoute()
const paperId = 'anomaly-transformer-2022'
const loading = ref(false)
const error = ref('')
const prompt = ref('')
const paper = ref<Paper | null>(null)
const graph = ref<EvidenceGraph | null>(null)
const selectedNode = ref<GraphNode | null>(null)
const sidePanel = ref<'evidence' | 'graph'>(route.query.panel === 'graph' ? 'graph' : 'evidence')
const activeTask = ref('等待任务')
const taskSteps = ref<TaskStep[]>([])
let messageSequence = 2
const messages = ref<ChatMessage[]>([
  {
    id: 1,
    role: 'assistant',
    meta: '科研助理 · 离线规则导航',
    text: '你好。我会先确认任务和证据边界，再调用结构化科研工具。当前离线模式不冒充大模型推理，也不会把候选问题写成确定创新点。',
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

const graphLayout = computed(() => {
  if (!graph.value) return { nodes: [], edges: [], height: 480 }
  const visible = graph.value.nodes.filter((item) => item.node_type !== 'narrative_move')
  const groups = {
    paper: visible.filter((item) => item.node_type === 'paper'),
    claim: visible.filter((item) => item.node_type === 'claim'),
    work: visible.filter((item) => ['experiment', 'artifact'].includes(item.node_type)),
    evidence: visible.filter((item) => item.node_type === 'evidence'),
  }
  const height = Math.max(520, groups.evidence.length * 55 + 60, groups.work.length * 63 + 60)
  const positions = new Map<string, { node: GraphNode; x: number; y: number }>()
  const place = (items: GraphNode[], x: number, gap: number) => {
    const start = Math.max(42, (height - Math.max(0, items.length - 1) * gap) / 2)
    items.forEach((node, index) => positions.set(node.node_id, { node, x, y: start + index * gap }))
  }
  place(groups.paper, 74, 60)
  place(groups.claim, 245, 92)
  place(groups.work, 465, 63)
  place(groups.evidence, 720, 55)
  return {
    height,
    nodes: [...positions.values()],
    edges: graph.value.edges
      .map((edge) => ({ edge, source: positions.get(edge.source_id), target: positions.get(edge.target_id) }))
      .filter((item) => item.source && item.target),
  }
})

function addMessage(role: 'assistant' | 'user', text: string, meta?: string) {
  messages.value.push({ id: messageSequence++, role, text, meta })
}

async function loadPaperAndGraph() {
  const [paperResponse, graphResponse] = await Promise.all([
    fetch(`/api/v1/tools/paper-deconstruct/${paperId}`, { method: 'POST' }),
    fetch(`/api/v1/papers/${paperId}/evidence-graph`),
  ])
  if (!paperResponse.ok || !graphResponse.ok) throw new Error('论文证据或关系图暂时不可用。')
  paper.value = await paperResponse.json()
  graph.value = await graphResponse.json()
  selectedNode.value = graph.value?.nodes.find((item) => item.node_type === 'paper') ?? null
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
    if (kind === 'paper') {
      setSteps([
        ['读取论文记录', '只加载当前可公开的 development seed'],
        ['闭合证据关系', '核对 Claim、Experiment、Artifact 与 EvidenceAnchor'],
        ['呈现证据边界', '不伪造页码、图注或核验状态'],
      ])
      taskSteps.value[0].status = 'running'
      await loadPaperAndGraph()
      taskSteps.value.forEach((item) => { item.status = 'done' })
      sidePanel.value = 'evidence'
      addMessage(
        'assistant',
        `已加载 ${paper.value!.title}：${paper.value!.claims.length} 个 Claim、${paper.value!.experiment_intents.length} 个实验意图、${paper.value!.artifacts.length} 个 Figure/Table 角色和 ${paper.value!.evidence.length} 个 EvidenceAnchor。它仍是开发种子，不是冻结 Gold。`,
        `证据图来源 · ${graph.value!.source}`,
      )
    } else {
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
  if (/图表|绘图|csv|json|plot/.test(normalized)) return runTask('plot', true)
  if (/claim|假设|实验设计|证据需求/.test(normalized)) return runTask('claim', true)
  if (/机会|选题|创新|前沿/.test(normalized)) return runTask('opportunity', true)
  if (/论文|anomaly|transformer|证据|拆解/.test(normalized)) return runTask('paper', true)
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
          <span>当前为离线规则导航；未连接模型时不会伪装成智能体推理。</span>
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
        <header><div><i></i><b>科研助理</b></div><span>对话入口 · 结构化工具执行</span></header>
        <div class="message-list" aria-live="polite">
          <article v-for="message in messages" :key="message.id" :class="message.role">
            <small>{{ message.meta ?? (message.role === 'user' ? '你' : '科研助理') }}</small>
            <p>{{ message.text }}</p>
          </article>
        </div>
        <form class="assistant-prompt" @submit.prevent="submitPrompt">
          <textarea v-model="prompt" aria-label="科研任务输入" rows="3" placeholder="例如：拆解 Anomaly Transformer，并告诉我每个 Claim 由哪些证据支持"></textarea>
          <footer><span>自然语言发起任务 · 证据不足时明确停止</span><button :disabled="loading || !prompt.trim()">发送任务</button></footer>
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
      </section>

      <section class="evidence-inspector">
        <header>
          <button :class="{ active: sidePanel === 'evidence' }" @click="sidePanel = 'evidence'">证据</button>
          <button :class="{ active: sidePanel === 'graph' }" @click="sidePanel = 'graph'">关系图</button>
          <span v-if="graph" data-testid="graph-source">{{ graph.source }}</span>
        </header>

        <div v-if="sidePanel === 'evidence'" class="evidence-panel">
          <template v-if="selectedEvidence">
            <div class="selection-label"><span>{{ selectedEvidence.kind }}</span><b>{{ selectedEvidence.verified ? '已核验' : '待核验' }}</b></div>
            <h3>{{ selectedEvidence.label }}</h3>
            <blockquote>{{ selectedEvidence.excerpt }}</blockquote>
            <p>页码：{{ selectedEvidence.page ?? '尚未由授权 PDF 核验' }}</p>
          </template>
          <template v-else>
            <h3>{{ selectedNode?.label ?? '证据检查器' }}</h3>
            <p>{{ selectedNode?.summary ?? '选择右侧关系图节点或下方 EvidenceAnchor。' }}</p>
          </template>
          <div class="evidence-list">
            <button v-for="item in paper?.evidence.slice(0, 6)" :key="item.id" @click="selectEvidence(item)">
              <span>{{ item.id }}</span><div><b>{{ item.label }}</b><small>{{ item.verified ? 'verified' : 'unverified' }}</small></div>
            </button>
          </div>
          <RouterLink :to="`/papers/${paperId}`" data-testid="open-paper-reader">打开论文逆向工程阅读器 →</RouterLink>
        </div>

        <div v-else class="graph-panel">
          <div class="graph-legend"><span class="paper">Paper</span><span class="claim">Claim</span><span class="work">Experiment / Artifact</span><span class="evidence">Evidence</span></div>
          <div class="graph-scroll" data-testid="evidence-graph">
            <svg v-if="graph" :viewBox="`0 0 800 ${graphLayout.height}`" role="img" aria-label="论文局部证据关系图">
              <line v-for="item in graphLayout.edges" :key="`${item.edge.source_id}:${item.edge.relationship}:${item.edge.target_id}`" :x1="item.source!.x" :y1="item.source!.y" :x2="item.target!.x" :y2="item.target!.y" />
              <g v-for="item in graphLayout.nodes" :key="item.node.node_id" :class="item.node.node_type" role="button" tabindex="0" @click="selectedNode = item.node">
                <rect :x="item.x - 54" :y="item.y - 19" width="108" height="38" rx="9" />
                <text :x="item.x" :y="item.y + 3" text-anchor="middle">{{ item.node.local_id ?? item.node.label.slice(0, 10) }}</text>
              </g>
            </svg>
          </div>
          <p v-if="graph">{{ graph.nodes.length }} 个节点 · {{ graph.edges.length }} 条关系 · MySQL 仍是权威事实源</p>
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
.conversation-card { margin-top: 20px; overflow: hidden; border: 1px solid #dbe2dd; border-radius: 16px; background: white; box-shadow: 0 14px 40px rgba(28,55,43,.06); }.conversation-card > header { display: flex; justify-content: space-between; padding: 14px 18px; border-bottom: 1px solid #edf0ed; }.conversation-card > header div { display: flex; align-items: center; gap: 8px; }.conversation-card > header i { width: 9px; height: 9px; border-radius: 50%; background: #52a574; }.conversation-card > header b { font-size: 12px; }.conversation-card > header span { color: #8a968f; font-size: 10px; }.message-list { min-height: 245px; max-height: 440px; overflow-y: auto; padding: 22px; background: linear-gradient(180deg,#fbfcfb,#f4f7f4); }.message-list article { max-width: 82%; margin-bottom: 15px; padding: 13px 15px; border-radius: 4px 14px 14px 14px; background: white; box-shadow: 0 4px 14px rgba(33,57,46,.05); }.message-list article.user { margin-left: auto; border-radius: 14px 4px 14px 14px; background: #dfeee6; }.message-list small { color: #718078; font-size: 9px; font-weight: 800; }.message-list p { margin: 6px 0 0; color: #263b31; font-size: 13px; line-height: 1.65; }.assistant-prompt { margin: 14px; border: 1px solid #cad5ce; border-radius: 12px; }.assistant-prompt textarea { width: 100%; resize: vertical; padding: 15px; border: 0; outline: 0; background: transparent; color: #20372c; font: inherit; line-height: 1.5; }.assistant-prompt footer { display: flex; justify-content: space-between; align-items: center; padding: 9px 10px 10px 15px; }.assistant-prompt footer span { color: #8a968f; font-size: 9px; }.assistant-prompt button { padding: 9px 15px; border: 0; border-radius: 8px; background: #205c45; color: white; font-weight: 800; }.assistant-prompt button:disabled { opacity: .45; }.assistant-error { padding: 12px; border-left: 4px solid #ef683e; background: #ffe1d5; color: #943b21; }
.research-inspector { min-width: 0; padding: 28px; border-left: 1px solid #dfe4df; background: #eef2ee; }.task-status, .evidence-inspector { border: 1px solid #d8e0da; border-radius: 14px; background: white; }.task-status { padding: 18px; }.task-status > header { display: flex; justify-content: space-between; align-items: center; }.task-status header p { margin: 0; color: #8c9992; font-size: 9px; letter-spacing: 1.3px; }.task-status h2 { margin: 5px 0 0; font-size: 18px; }.task-status header > span { padding: 6px 8px; border-radius: 99px; background: #e6efe9; color: #2a634b; font-size: 9px; font-weight: 900; }.task-status ol { display: grid; gap: 7px; margin: 16px 0 0; padding: 0; list-style: none; }.task-status li { display: grid; grid-template-columns: 27px 1fr auto; gap: 9px; align-items: center; padding: 10px; border-radius: 9px; background: #f4f6f3; }.task-status li > i { display: grid; place-items: center; width: 24px; height: 24px; border: 1px solid #cbd5ce; border-radius: 50%; font-style: normal; font-size: 9px; }.task-status li div { display: grid; gap: 2px; }.task-status li b { font-size: 11px; }.task-status li small { color: #849089; font-size: 9px; }.task-status li > span { color: #849089; font-size: 8px; text-transform: uppercase; }.task-status li.done > i { border-color: #4a9c6c; background: #4a9c6c; color: white; }.task-status li.running { background: #fff5d8; }.task-status li.blocked { background: #ffe5dc; }.empty-task { color: #79867e; font-size: 11px; line-height: 1.6; }
.evidence-inspector { margin-top: 16px; overflow: hidden; }.evidence-inspector > header { display: flex; align-items: center; padding: 8px; border-bottom: 1px solid #e4e9e5; }.evidence-inspector > header button { padding: 8px 12px; border: 0; border-radius: 8px; background: transparent; color: #718078; font-size: 11px; font-weight: 800; }.evidence-inspector > header button.active { background: #dfeee6; color: #205c45; }.evidence-inspector > header span { margin-left: auto; padding: 5px 7px; border: 1px solid #d4ddd7; border-radius: 99px; color: #6d7a72; font-size: 8px; }.evidence-panel, .graph-panel { padding: 18px; }.selection-label { display: flex; justify-content: space-between; }.selection-label span, .selection-label b { padding: 5px 7px; border-radius: 99px; background: #eef2ee; font-size: 8px; }.selection-label b { background: #ffe6dc; color: #a34224; }.evidence-panel h3 { margin: 14px 0 8px; font-size: 17px; line-height: 1.35; }.evidence-panel > p { color: #718078; font-size: 10px; line-height: 1.5; }.evidence-panel blockquote { margin: 13px 0; padding: 12px; border-left: 3px solid #ef683e; background: #f5f6f2; color: #43544b; font: 13px/1.6 Georgia,serif; }.evidence-list { display: grid; gap: 5px; margin: 17px 0; }.evidence-list button { display: grid; grid-template-columns: 34px 1fr; gap: 8px; padding: 9px; border: 1px solid #e1e6e2; border-radius: 8px; background: white; text-align: left; }.evidence-list button > span { color: #ef683e; font-size: 9px; font-weight: 900; }.evidence-list button div { display: grid; gap: 2px; }.evidence-list b { overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.evidence-list small { color: #909b94; font-size: 8px; }.evidence-panel > a { color: #205c45; font-size: 10px; font-weight: 800; text-decoration: none; }
.graph-legend { display: flex; flex-wrap: wrap; gap: 5px; }.graph-legend span { padding: 4px 6px; border-radius: 99px; font-size: 8px; }.graph-legend .paper { background: #205c45; color: white; }.graph-legend .claim { background: #dfff43; }.graph-legend .work { background: #ffd7c9; }.graph-legend .evidence { background: #dce8ff; }.graph-scroll { max-height: 520px; margin-top: 12px; overflow: auto; border: 1px solid #e3e8e4; border-radius: 10px; background: #f9fbf9; }.graph-scroll svg { display: block; min-width: 720px; width: 100%; }.graph-scroll line { stroke: #c2ccc6; stroke-width: 1; }.graph-scroll g { cursor: pointer; }.graph-scroll rect { fill: white; stroke: #aebbb3; stroke-width: 1.3; }.graph-scroll text { fill: #23382e; font-size: 8px; pointer-events: none; }.graph-scroll g.paper rect { fill: #205c45; stroke: #205c45; }.graph-scroll g.paper text { fill: white; }.graph-scroll g.claim rect { fill: #efffb0; stroke: #b7d64c; }.graph-scroll g.experiment rect, .graph-scroll g.artifact rect { fill: #ffe3d9; stroke: #ef9b7e; }.graph-scroll g.evidence rect { fill: #e8effd; stroke: #9fb4dc; }.graph-panel > p { color: #718078; font-size: 9px; line-height: 1.45; }.graph-warning { padding-left: 8px; border-left: 2px solid #ef683e; }
@media (max-width: 1250px) { .assistant-view { grid-template-columns: 1fr; }.research-inspector { display: grid; grid-template-columns: .8fr 1.2fr; gap: 15px; border-left: 0; border-top: 1px solid #dfe4df; }.evidence-inspector { margin-top: 0; }.quick-task-grid { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 720px) { .assistant-main { padding: 30px 18px 45px; }.assistant-hero { display: grid; }.quick-task-grid, .research-inspector { grid-template-columns: 1fr; }.research-inspector { padding: 18px; }.message-list article { max-width: 95%; } }
</style>
