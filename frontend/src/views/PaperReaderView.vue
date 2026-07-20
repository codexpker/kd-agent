<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'

type Evidence = {
  id: string
  kind: 'section' | 'sentence' | 'figure' | 'table' | 'caption' | 'reference'
  label: string
  excerpt: string
  page: number | null
  verified: boolean
}
type NarrativeMove = { id: string; order: number; move: string; purpose: string; evidence_ids: string[] }
type Claim = { id: string; claim_type: string; statement: string; evidence_ids: string[] }
type Experiment = {
  id: string
  title: string
  question: string
  design_reason: string
  variables: string[]
  supports_claim_ids: string[]
  evidence_ids: string[]
}
type Artifact = {
  id: string
  artifact_type: 'figure' | 'table'
  label: string
  role: string
  why_here: string
  supports_claim_ids: string[]
  evidence_ids: string[]
}
type Paper = {
  paper_id: string
  title: string
  venue: string
  year: number
  status: 'development_seed' | 'double_annotated' | 'frozen'
  narrative_moves: NarrativeMove[]
  claims: Claim[]
  experiment_intents: Experiment[]
  artifacts: Artifact[]
  evidence: Evidence[]
  limitations: string[]
}
type DocumentStructure = {
  paper_id: string
  source: 'parsed_pdf' | 'gold_snapshot'
  parser_name: string | null
  parser_version: string | null
  file_sha256: string | null
  page_count: number | null
  sections: { id: string; title: string; level: number; page_start: number | null; page_end: number | null; heading_bbox: number[] | null }[]
  artifacts: { id: string; artifact_type: 'figure' | 'table'; label: string; caption: string | null; page: number | null; bbox: number[] | null; caption_bbox: number[] | null; markdown: string | null; table_data: string[][] | null }[]
  references: { id: string; artifact_id: string; text: string; page: number | null; bbox: number[] | null }[]
  warnings: string[]
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
  source: 'neo4j' | 'gold_snapshot'
  nodes: GraphNode[]
  edges: GraphEdge[]
  warnings: string[]
}
type ReaderTab = 'story' | 'experiments' | 'artifacts' | 'graph'

const route = useRoute()
const paperId = computed(() => String(route.params.paperId || ''))
const paper = ref<Paper | null>(null)
const structure = ref<DocumentStructure | null>(null)
const graph = ref<EvidenceGraph | null>(null)
const activeTab = ref<ReaderTab>('story')
const selectedEvidenceId = ref<string | null>(null)
const focusedClaimId = ref<string | null>(null)
const question = ref('')
const navigationMessage = ref('')
const loading = ref(true)
const error = ref('')
const previewPage = ref(1)
const previewArtifactId = ref<string | null>(null)
const previewLoading = ref(false)
const previewError = ref('')

const evidenceById = computed(() => new Map((paper.value?.evidence ?? []).map((item) => [item.id, item])))
const claimById = computed(() => new Map((paper.value?.claims ?? []).map((item) => [item.id, item])))
const selectedEvidence = computed(() => selectedEvidenceId.value ? evidenceById.value.get(selectedEvidenceId.value) ?? null : null)
const verifiedEvidenceCount = computed(() => paper.value?.evidence.filter((item) => item.verified).length ?? 0)
const sourceLabel = computed(() => structure.value?.source === 'parsed_pdf' ? '已解析 PDF' : 'Gold 结构快照')
const normalizeLabel = (value: string) => value.toLowerCase().replace(/\s+/g, ' ').trim()
const selectedLayoutArtifact = computed(() => {
  if (!selectedEvidence.value || structure.value?.source !== 'parsed_pdf') return null
  const label = normalizeLabel(selectedEvidence.value.label)
  return structure.value.artifacts.find((item) => normalizeLabel(item.label) === label) ?? null
})
const selectedLayoutSection = computed(() => {
  if (!selectedEvidence.value || structure.value?.source !== 'parsed_pdf') return null
  const label = normalizeLabel(selectedEvidence.value.label)
  return structure.value.sections.find((item) => normalizeLabel(item.title) === label) ?? null
})
const selectedLayoutReferences = computed(() => {
  if (!selectedLayoutArtifact.value || !structure.value) return []
  return structure.value.references.filter((item) => item.artifact_id === selectedLayoutArtifact.value?.id)
})
const previewUrl = computed(() => {
  if (structure.value?.source !== 'parsed_pdf') return ''
  const base = `/api/v1/papers/${encodeURIComponent(paperId.value)}/document-preview`
  return previewArtifactId.value
    ? `${base}/artifacts/${encodeURIComponent(previewArtifactId.value)}`
    : `${base}/pages/${previewPage.value}`
})

const graphLayout = computed(() => {
  if (!graph.value) return { nodes: [] as Array<GraphNode & { x: number; y: number }>, edges: [] as Array<GraphEdge & { x1: number; y1: number; x2: number; y2: number }>, height: 460 }
  const claim = graph.value.nodes.find((node) => node.node_type === 'claim' && node.local_id === focusedClaimId.value)
    ?? graph.value.nodes.find((node) => node.node_type === 'claim')
  if (!claim) return { nodes: [], edges: [], height: 320 }
  const middleIds = new Set(graph.value.edges
    .filter((edge) => edge.relationship === 'SUPPORTS' && edge.target_id === claim.node_id)
    .map((edge) => edge.source_id))
  const evidenceIds = new Set(graph.value.edges
    .filter((edge) => edge.relationship === 'SUPPORTED_BY' && (edge.source_id === claim.node_id || middleIds.has(edge.source_id)))
    .map((edge) => edge.target_id))
  const visibleIds = new Set([claim.node_id, ...middleIds, ...evidenceIds])
  const visible = graph.value.nodes.filter((node) => visibleIds.has(node.node_id))
  const columns = [
    visible.filter((node) => node.node_id === claim.node_id),
    visible.filter((node) => node.node_type === 'experiment' || node.node_type === 'artifact'),
    visible.filter((node) => node.node_type === 'evidence'),
  ]
  const height = Math.max(320, ...columns.map((items) => items.length * 72 + 70))
  const placed = new Map<string, GraphNode & { x: number; y: number }>()
  columns.forEach((items, columnIndex) => {
    const gap = (height - 70) / Math.max(items.length, 1)
    items.forEach((node, index) => placed.set(node.node_id, { ...node, x: 130 + columnIndex * 300, y: 52 + gap * index }))
  })
  return {
    height,
    nodes: [...placed.values()],
    edges: graph.value.edges.filter((edge) => visibleIds.has(edge.source_id) && visibleIds.has(edge.target_id)).flatMap((edge) => {
      const source = placed.get(edge.source_id)
      const target = placed.get(edge.target_id)
      return source && target ? [{ ...edge, x1: source.x, y1: source.y, x2: target.x, y2: target.y }] : []
    }),
  }
})

function evidenceFor(ids: string[]) {
  return ids.flatMap((id) => {
    const item = evidenceById.value.get(id)
    return item ? [item] : []
  })
}

function claimsFor(ids: string[]) {
  return ids.flatMap((id) => {
    const item = claimById.value.get(id)
    return item ? [item] : []
  })
}

function inspectEvidence(id: string) {
  selectedEvidenceId.value = id
}

function focusClaim(id: string) {
  focusedClaimId.value = id
}

function claimIsRelevant(ids: string[]) {
  return focusedClaimId.value === null || ids.includes(focusedClaimId.value)
}

function showPreviewPage(page: number | null) {
  if (!page) return
  previewPage.value = page
  previewArtifactId.value = null
  previewError.value = ''
  previewLoading.value = true
}

function showLayoutArtifact(artifact: DocumentStructure['artifacts'][number] | null) {
  if (!artifact?.page) return
  previewPage.value = artifact.page
  previewArtifactId.value = artifact.id
  previewError.value = ''
  previewLoading.value = true
}

function showSemanticArtifact(artifact: Artifact) {
  const parsed = structure.value?.artifacts.find((item) => normalizeLabel(item.label) === normalizeLabel(artifact.label)) ?? null
  showLayoutArtifact(parsed)
}

function previewFailed() {
  previewLoading.value = false
  previewError.value = '本地私有 PDF 预览未启用，或文件哈希与数据库记录不一致。'
}

function navigateQuestion(preset?: string) {
  const value = (preset ?? question.value).trim()
  if (!value) return
  question.value = ''
  if (/实验|消融|基线|变量|experiment|ablation|baseline/i.test(value)) {
    activeTab.value = 'experiments'
    navigationMessage.value = '已定位到实验意图：这里展示研究问题、设计理由、变量、Claim 和证据边界。'
  } else if (/图|表|figure|table|artifact/i.test(value)) {
    activeTab.value = 'artifacts'
    navigationMessage.value = '已定位到图表角色：这里解释为何采用该形式、支持哪些 Claim，以及对应证据。'
  } else if (/关系|图谱|证据链|graph|relation/i.test(value)) {
    activeTab.value = 'graph'
    navigationMessage.value = '已定位到局部证据关系图；它用于检查闭合关系，不替代可读证据列表。'
  } else {
    activeTab.value = 'story'
    navigationMessage.value = '已定位到科研叙事链；当前离线导航不会生成论文中不存在的回答。'
  }
}

async function loadReader() {
  loading.value = true
  error.value = ''
  try {
    const [paperResponse, structureResponse, graphResponse] = await Promise.all([
      fetch(`/api/v1/tools/paper-deconstruct/${paperId.value}`, { method: 'POST' }),
      fetch(`/api/v1/papers/${paperId.value}/document-structure`),
      fetch(`/api/v1/papers/${paperId.value}/evidence-graph`),
    ])
    if (paperResponse.status === 404) throw new Error('该论文尚无可公开加载的审核记录。')
    if (!paperResponse.ok || !structureResponse.ok || !graphResponse.ok) throw new Error('论文结构或证据关系暂时不可用。')
    paper.value = await paperResponse.json()
    structure.value = await structureResponse.json()
    graph.value = await graphResponse.json()
    selectedEvidenceId.value = paper.value?.evidence[0]?.id ?? null
    focusedClaimId.value = paper.value?.claims[1]?.id ?? paper.value?.claims[0]?.id ?? null
    previewPage.value = structure.value?.sections.find((item) => item.page_start)?.page_start ?? 1
    previewLoading.value = structure.value?.source === 'parsed_pdf'
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载失败'
  } finally {
    loading.value = false
  }
}

watch(paperId, loadReader)
watch(selectedEvidence, () => {
  if (selectedLayoutArtifact.value) showLayoutArtifact(selectedLayoutArtifact.value)
  else if (selectedLayoutSection.value) showPreviewPage(selectedLayoutSection.value.page_start)
})
onMounted(loadReader)
</script>

<template>
  <main class="paper-reader" data-testid="paper-reader">
    <header class="reader-header">
      <div class="reader-breadcrumb"><RouterLink to="/assistant">科研助理</RouterLink><span>/</span><b>论文逆向工程</b></div>
      <div v-if="paper" class="paper-heading">
        <div>
          <div class="status-line">
            <span>{{ paper.venue }} {{ paper.year }}</span>
            <span class="status-pill warning">{{ paper.status }}</span>
            <span class="status-pill">{{ sourceLabel }}</span>
          </div>
          <h1>{{ paper.title }}</h1>
          <p>目标：理解问题、方法、实验和图表如何组成可核验的科研证据链。</p>
        </div>
        <dl>
          <div><dt>Claim</dt><dd>{{ paper.claims.length }}</dd></div>
          <div><dt>实验意图</dt><dd>{{ paper.experiment_intents.length }}</dd></div>
          <div><dt>图表角色</dt><dd>{{ paper.artifacts.length }}</dd></div>
          <div><dt>已核验证据</dt><dd>{{ verifiedEvidenceCount }}/{{ paper.evidence.length }}</dd></div>
        </dl>
      </div>
    </header>

    <div v-if="loading" class="reader-state">正在读取结构化论文记录…</div>
    <div v-else-if="error" class="reader-state error"><b>无法打开论文</b><p>{{ error }}</p><RouterLink to="/assistant">返回科研助理</RouterLink></div>

    <template v-else-if="paper && structure">
      <section class="reader-integrity" data-testid="reader-integrity">
        <b>当前证据边界</b>
        <p v-if="structure.source === 'gold_snapshot'">这是语义开发种子与 Gold 结构快照，不是已授权 PDF 阅读页。页码、bbox、真实图注和正文引用均保持为空；原 PDF 不由本页面分发。</p>
        <p v-else>当前结构来自 {{ structure.parser_name }} {{ structure.parser_version }} 的真实自动解析，尚未经过双人版面标注；PDF 原文件仍不写数据库、不进入 Git。</p>
      </section>

      <div class="reader-grid">
        <aside class="document-pane">
          <div class="pane-title"><div><small>DOCUMENT STRUCTURE</small><h2>文档结构</h2></div><span>{{ structure.source }}</span></div>
          <div v-if="structure.source === 'gold_snapshot'" class="pdf-placeholder" data-testid="pdf-permission-state">
            <div class="paper-sheet"><span>PDF</span><i></i><i></i><i></i><b>原文未在网页分发</b></div>
            <p>缺少已持久化的授权解析结果，仅展示不会伪造位置的结构快照。</p>
          </div>
          <figure v-else class="private-preview" data-testid="private-pdf-preview">
            <header><b>本地私有副本 · 第 {{ previewPage }} 页</b><span>不提供原 PDF 下载</span></header>
            <div class="preview-canvas">
              <span v-if="previewLoading">正在按 SHA-256 渲染…</span>
              <img :key="previewUrl" :src="previewUrl" :alt="`论文第 ${previewPage} 页的本地受控预览`" @load="previewLoading = false; previewError = ''" @error="previewFailed" />
            </div>
            <figcaption v-if="previewError">{{ previewError }}</figcaption>
            <figcaption v-else-if="previewArtifactId">橙色框为自动解析的图表或图注位置，仅用于本机演示，仍需人工复核。</figcaption>
            <figcaption v-else>页面由哈希匹配的授权私有副本即时渲染，不写数据库、不进入 Git。</figcaption>
            <nav><button :disabled="previewPage <= 1" @click="showPreviewPage(previewPage - 1)">上一页</button><button :disabled="previewPage >= (structure.page_count ?? 1)" @click="showPreviewPage(previewPage + 1)">下一页</button></nav>
          </figure>
          <dl v-if="structure.source === 'parsed_pdf'" class="parse-provenance">
            <div><dt>解析器</dt><dd>{{ structure.parser_name }} {{ structure.parser_version }}</dd></div>
            <div><dt>页数</dt><dd>{{ structure.page_count }}</dd></div>
            <div><dt>文件哈希</dt><dd>{{ structure.file_sha256?.slice(0, 16) }}…</dd></div>
          </dl>
          <nav class="section-outline" aria-label="论文章节">
            <p>章节索引</p>
            <button v-for="(section, index) in structure.sections" :key="section.id" @click="activeTab = 'story'; showPreviewPage(section.page_start)">
              <span>{{ String(index + 1).padStart(2, '0') }}</span>
              <b>{{ section.title }}</b>
              <small>{{ section.page_start ? `p.${section.page_start}` : '页码待核验' }}</small>
            </button>
          </nav>
          <div class="document-warnings"><p v-for="warning in structure.warnings" :key="warning">{{ warning }}</p></div>
        </aside>

        <section class="analysis-pane">
          <form class="reader-question" @submit.prevent="navigateQuestion()">
            <label for="reader-question">你想重点理解什么？</label>
            <div><input id="reader-question" v-model="question" placeholder="例如：为什么需要消融实验？" /><button>定位</button></div>
            <nav><button type="button" @click="navigateQuestion('这篇论文如何讲故事')">叙事链</button><button type="button" @click="navigateQuestion('为什么做这些实验')">实验意图</button><button type="button" @click="navigateQuestion('图表为什么这样设计')">图表角色</button></nav>
            <p v-if="navigationMessage">{{ navigationMessage }}</p>
          </form>

          <nav class="reader-tabs" aria-label="逆向工程视图">
            <button :class="{ active: activeTab === 'story' }" @click="activeTab = 'story'">科研叙事链</button>
            <button :class="{ active: activeTab === 'experiments' }" @click="activeTab = 'experiments'">实验意图</button>
            <button :class="{ active: activeTab === 'artifacts' }" @click="activeTab = 'artifacts'">Figure / Table</button>
            <button :class="{ active: activeTab === 'graph' }" @click="activeTab = 'graph'">证据关系</button>
          </nav>

          <section v-if="activeTab === 'story'" class="story-view" data-testid="narrative-chain">
            <header><small>PROBLEM → GAP → METHOD → EVIDENCE → BOUNDARY</small><h2>作者如何建立论证</h2><p>以下中文内容是开发阶段的语义转述，不是论文原句，也不等同于 PDF 客观版面事实。</p></header>
            <ol>
              <li v-for="move in paper.narrative_moves" :key="move.id">
                <span>{{ String(move.order).padStart(2, '0') }}</span>
                <article><small>{{ move.move }}</small><h3>{{ move.purpose }}</h3><div class="anchor-row"><button v-for="anchor in evidenceFor(move.evidence_ids)" :key="anchor.id" @click="inspectEvidence(anchor.id)">{{ anchor.id }} · {{ anchor.label }}</button></div></article>
              </li>
            </ol>
            <div class="claim-section"><header><h2>核心 Claim</h2><span>点击可筛选关联实验与图表</span></header><div class="claim-grid">
              <button v-for="claim in paper.claims" :key="claim.id" :class="{ selected: focusedClaimId === claim.id }" @click="focusClaim(claim.id)">
                <small>{{ claim.claim_type }} · {{ claim.id }}</small><p>{{ claim.statement }}</p><span>{{ claim.evidence_ids.length }} 条关联证据</span>
              </button>
            </div></div>
          </section>

          <section v-else-if="activeTab === 'experiments'" class="card-view" data-testid="experiment-intents">
            <header><small>EXPERIMENT INTENT</small><h2>实验为什么存在</h2><p>说明它回答什么问题、控制哪些变量、支持什么 Claim；不生成或推断实验数值。</p></header>
            <article v-for="experiment in paper.experiment_intents" :key="experiment.id" :class="{ muted: !claimIsRelevant(experiment.supports_claim_ids) }">
              <div class="card-index">{{ experiment.id }}</div><div class="card-body"><h3>{{ experiment.title }}</h3><dl><div><dt>研究问题</dt><dd>{{ experiment.question }}</dd></div><div><dt>为什么这样设计</dt><dd>{{ experiment.design_reason }}</dd></div><div><dt>变量 / 指标</dt><dd><span v-for="variable in experiment.variables" :key="variable">{{ variable }}</span></dd></div><div><dt>支持的 Claim</dt><dd><button v-for="claim in claimsFor(experiment.supports_claim_ids)" :key="claim.id" @click="focusClaim(claim.id)">{{ claim.id }} · {{ claim.claim_type }}</button></dd></div></dl><div class="anchor-row"><button v-for="anchor in evidenceFor(experiment.evidence_ids)" :key="anchor.id" @click="inspectEvidence(anchor.id)">{{ anchor.id }} · {{ anchor.label }}</button></div></div>
            </article>
          </section>

          <section v-else-if="activeTab === 'artifacts'" class="card-view" data-testid="artifact-roles">
            <header><small>FIGURE / TABLE ROLE</small><h2>图表承担什么论证作用</h2><p>角色卡解释表现形式与 Claim 的关系；真实页图来自自动解析结果，语义角色仍是待双人复核的开发注释。</p></header>
            <article v-for="artifact in paper.artifacts" :key="artifact.id" :class="{ muted: !claimIsRelevant(artifact.supports_claim_ids) }">
              <div class="artifact-mark" :class="artifact.artifact_type"><small>{{ artifact.artifact_type }}</small><b>{{ artifact.label }}</b><button v-if="structure.source === 'parsed_pdf'" @click="showSemanticArtifact(artifact)">查看真实页图</button></div><div class="card-body"><h3>{{ artifact.role }}</h3><dl><div><dt>为什么放在这里</dt><dd>{{ artifact.why_here }}</dd></div><div><dt>支持的 Claim</dt><dd><button v-for="claim in claimsFor(artifact.supports_claim_ids)" :key="claim.id" @click="focusClaim(claim.id)">{{ claim.id }} · {{ claim.claim_type }}</button></dd></div></dl><div class="anchor-row"><button v-for="anchor in evidenceFor(artifact.evidence_ids)" :key="anchor.id" @click="inspectEvidence(anchor.id)">{{ anchor.id }} · {{ anchor.label }}</button></div></div>
            </article>
          </section>

          <section v-else class="reader-graph" data-testid="paper-evidence-graph">
            <header><div><small>CLAIM → EXPERIMENT / ARTIFACT → EVIDENCE</small><h2>局部证据关系</h2></div><span>{{ graph?.source }}</span></header>
            <div class="graph-focus"><b>当前只解释一个 Claim</b><button v-for="claim in paper.claims" :key="claim.id" :class="{ active: focusedClaimId === claim.id }" @click="focusClaim(claim.id)">{{ claim.id }} · {{ claim.claim_type }}</button></div>
            <div class="graph-labels"><span>Claim</span><span>实验 / 图表</span><span>EvidenceAnchor</span></div>
            <svg v-if="graph" :viewBox="`0 0 860 ${graphLayout.height}`" role="img" aria-label="论文证据关系图">
              <line v-for="edge in graphLayout.edges" :key="`${edge.source_id}:${edge.relationship}:${edge.target_id}`" :x1="edge.x1" :y1="edge.y1" :x2="edge.x2" :y2="edge.y2" />
              <text v-for="edge in graphLayout.edges" :key="`label:${edge.source_id}:${edge.relationship}:${edge.target_id}`" class="edge-label" :x="(edge.x1 + edge.x2) / 2" :y="(edge.y1 + edge.y2) / 2 - 4" text-anchor="middle">{{ edge.relationship === 'SUPPORTS' ? '支撑' : '依据' }}</text>
              <g v-for="node in graphLayout.nodes" :key="node.node_id" :class="node.node_type" role="button" tabindex="0" @click="node.node_type === 'evidence' && node.local_id ? inspectEvidence(node.local_id) : undefined">
                <rect :x="node.x - 92" :y="node.y - 20" width="184" height="40" rx="9" /><text :x="node.x" :y="node.y + 4" text-anchor="middle">{{ node.local_id }} · {{ node.label.slice(0, 18) }}</text>
              </g>
            </svg>
            <p>图中仅保留所选 Claim、支撑它的实验/图表及其 EvidenceAnchor；完整 Neo4j 图仍作为可重建索引存在。</p>
            <p v-for="warning in graph?.warnings" :key="warning">{{ warning }}</p>
          </section>
        </section>

        <aside class="evidence-pane" data-testid="evidence-inspector">
          <div class="pane-title"><div><small>EVIDENCE INSPECTOR</small><h2>证据透镜</h2></div><span>{{ selectedEvidence?.verified ? 'verified' : 'unverified' }}</span></div>
          <template v-if="selectedEvidence">
            <div class="evidence-kind"><span>{{ selectedEvidence.kind }}</span><b>{{ selectedEvidence.id }}</b></div>
            <h3>{{ selectedEvidence.label }}</h3>
            <blockquote>{{ selectedEvidence.excerpt }}</blockquote>
            <p class="annotation-note">上方是人工整理方向的开发注释，不是论文原句。</p>
            <dl><div><dt>语义核验</dt><dd>{{ selectedEvidence.verified ? '已人工核验' : '尚未双人复核' }}</dd></div><div><dt>注释来源</dt><dd>development_seed / semantic_annotation</dd></div><div><dt>版面来源</dt><dd>{{ structure.source === 'parsed_pdf' ? `${structure.parser_name} 自动解析（待复核）` : '无真实解析结果' }}</dd></div></dl>
            <section v-if="selectedLayoutArtifact || selectedLayoutSection" class="layout-fact-card">
              <b>PDF 自动解析事实</b>
              <p v-if="selectedLayoutArtifact">{{ selectedLayoutArtifact.label }} · 第 {{ selectedLayoutArtifact.page }} 页</p>
              <p v-if="selectedLayoutArtifact?.caption">图注：{{ selectedLayoutArtifact.caption }}</p>
              <p v-if="selectedLayoutSection">章节 {{ selectedLayoutSection.title }} · 第 {{ selectedLayoutSection.page_start }}–{{ selectedLayoutSection.page_end }} 页</p>
              <p v-if="selectedLayoutReferences.length">检测到 {{ selectedLayoutReferences.length }} 处正文引用：{{ selectedLayoutReferences[0].text }}</p>
              <button class="locate-button" @click="selectedLayoutArtifact ? showLayoutArtifact(selectedLayoutArtifact) : showPreviewPage(selectedLayoutSection?.page_start ?? null)">在左侧真实页图中定位</button>
            </section>
            <button v-else class="locate-button" disabled>没有可匹配的自动解析位置</button>
          </template>
          <div class="anchor-catalog"><p>全部 EvidenceAnchor</p><button v-for="item in paper.evidence" :key="item.id" :class="{ active: selectedEvidenceId === item.id }" @click="inspectEvidence(item.id)"><span>{{ item.id }}</span><div><b>{{ item.label }}</b><small>{{ item.verified ? '已人工核验' : '开发注释待复核' }}</small></div></button></div>
          <section class="boundary-box"><b>不能由当前记录得出</b><ul><li v-for="item in paper.limitations" :key="item">{{ item }}</li></ul></section>
        </aside>
      </div>
    </template>
  </main>
</template>

<style scoped>
.paper-reader { min-height: calc(100vh - 66px); background: #f4f6f3; color: #193027; }
.reader-header { padding: 26px 34px 22px; border-bottom: 1px solid #dce3de; background: #fbfcfa; }
.reader-breadcrumb { display: flex; gap: 8px; align-items: center; color: #849189; font-size: 10px; }.reader-breadcrumb a { color: #28654e; text-decoration: none; }.reader-breadcrumb b { color: #506158; }
.paper-heading { display: flex; justify-content: space-between; gap: 32px; align-items: end; margin-top: 18px; }.paper-heading > div { max-width: 830px; }.paper-heading h1 { margin: 10px 0 8px; max-width: 900px; font-family: Georgia, 'Times New Roman', serif; font-size: clamp(28px, 3vw, 44px); font-weight: 500; line-height: 1.08; letter-spacing: -1.2px; }.paper-heading p { margin: 0; color: #718079; font-size: 12px; }.status-line { display: flex; gap: 7px; align-items: center; }.status-line > span:first-child { color: #ef683e; font-size: 10px; font-weight: 900; letter-spacing: 1.2px; }.status-pill { padding: 5px 8px; border-radius: 99px; background: #e3eee8; color: #28634c; font-size: 9px; font-weight: 800; }.status-pill.warning { background: #fff0d6; color: #875411; }
.paper-heading dl { min-width: 340px; display: grid; grid-template-columns: repeat(4, 1fr); margin: 0; padding: 12px; border: 1px solid #dce3de; border-radius: 14px; background: white; }.paper-heading dl div { padding: 0 11px; border-right: 1px solid #e6ebe7; }.paper-heading dl div:last-child { border: 0; }.paper-heading dt { color: #89958e; font-size: 8px; white-space: nowrap; }.paper-heading dd { margin: 5px 0 0; color: #1d5741; font-size: 18px; font-weight: 900; }
.reader-integrity { display: flex; gap: 18px; align-items: center; margin: 16px 28px 0; padding: 11px 15px; border: 1px solid #efd6a8; border-radius: 10px; background: #fff8e9; }.reader-integrity b { white-space: nowrap; color: #815314; font-size: 10px; }.reader-integrity p { margin: 0; color: #715e3f; font-size: 10px; line-height: 1.5; }
.reader-grid { display: grid; grid-template-columns: 285px minmax(400px, 1fr) 300px; align-items: start; min-height: 800px; }.document-pane, .evidence-pane { position: sticky; top: 66px; max-height: calc(100vh - 66px); overflow-y: auto; padding: 24px 18px 48px; }.document-pane { border-right: 1px solid #dce3de; background: #eef2ee; }.evidence-pane { border-left: 1px solid #dce3de; background: #f9faf8; }.analysis-pane { min-width: 0; padding: 25px 26px 80px; }
.pane-title { display: flex; justify-content: space-between; align-items: start; }.pane-title small, .analysis-pane header > small, .reader-graph header small { color: #87958d; font-size: 8px; font-weight: 900; letter-spacing: 1.3px; }.pane-title h2, .analysis-pane header h2, .reader-graph h2 { margin: 5px 0 0; font-size: 18px; }.pane-title > span { padding: 5px 7px; border-radius: 6px; background: #dfe9e3; color: #3c6955; font-size: 8px; font-weight: 800; }
.pdf-placeholder { margin-top: 18px; padding: 15px; border: 1px dashed #c8d3cc; border-radius: 12px; background: #f8faf8; text-align: center; }.paper-sheet { width: 118px; height: 150px; display: flex; flex-direction: column; gap: 9px; margin: 0 auto 13px; padding: 15px 12px; border: 1px solid #d6ddd8; border-radius: 4px; background: white; box-shadow: 0 7px 18px rgba(35,58,47,.08); text-align: left; }.paper-sheet span { color: #ef683e; font-size: 9px; font-weight: 900; }.paper-sheet i { display: block; height: 3px; background: #dce3de; }.paper-sheet i:nth-of-type(2) { width: 80%; }.paper-sheet b { margin-top: auto; color: #7b8881; font-size: 8px; text-align: center; }.pdf-placeholder p { margin: 0; color: #77847d; font-size: 9px; line-height: 1.55; }
.private-preview { margin: 16px 0 0; overflow: hidden; border: 1px solid #cad6ce; border-radius: 11px; background: white; }.private-preview > header { display: grid; gap: 3px; padding: 9px 10px; background: #e3eee8; }.private-preview > header b { color: #285b46; font-size: 9px; }.private-preview > header span { color: #708078; font-size: 7px; }.preview-canvas { position: relative; min-height: 220px; display: grid; place-items: center; background: #d8ddd9; }.preview-canvas > span { position: absolute; z-index: 1; padding: 6px 8px; border-radius: 6px; background: rgba(22,48,37,.8); color: white; font-size: 8px; }.preview-canvas img { display: block; width: 100%; min-height: 220px; object-fit: contain; background: white; }.private-preview figcaption { padding: 8px 10px; color: #68776f; font-size: 8px; line-height: 1.45; }.private-preview nav { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; padding: 0 9px 9px; }.private-preview nav button { padding: 7px; border: 1px solid #cad6ce; border-radius: 7px; background: #f6f8f6; color: #315c49; font-size: 8px; font-weight: 800; }.private-preview nav button:disabled { opacity: .35; }
.section-outline { display: grid; gap: 5px; margin-top: 22px; }.section-outline > p, .anchor-catalog > p { margin: 0 0 6px; color: #88948e; font-size: 8px; font-weight: 900; letter-spacing: 1px; }.section-outline button { display: grid; grid-template-columns: 24px 1fr; gap: 3px 7px; padding: 9px; border: 0; border-radius: 8px; background: transparent; color: #31473c; text-align: left; }.section-outline button:hover { background: white; }.section-outline button > span { grid-row: 1 / 3; color: #ef683e; font-size: 9px; font-weight: 900; }.section-outline b { font-size: 10px; }.section-outline small { color: #8b9790; font-size: 8px; }.document-warnings { margin-top: 18px; padding-top: 10px; border-top: 1px solid #d9e0db; }.document-warnings p { color: #7b8881; font-size: 8px; line-height: 1.5; }
.parse-provenance { margin: 12px 0 0; padding: 10px; border-radius: 8px; background: #e5ede8; }.parse-provenance div { display: grid; grid-template-columns: 48px 1fr; gap: 5px; padding: 3px 0; }.parse-provenance dt { color: #7d8a82; font-size: 8px; }.parse-provenance dd { margin: 0; overflow-wrap: anywhere; color: #355243; font-size: 8px; }
.reader-question { padding: 15px 16px; border: 1px solid #dce3de; border-radius: 13px; background: white; }.reader-question label { display: block; margin-bottom: 8px; font-size: 11px; font-weight: 900; }.reader-question > div { display: flex; }.reader-question input { flex: 1; min-width: 0; padding: 10px 12px; border: 1px solid #cad5ce; border-radius: 8px 0 0 8px; outline: none; font: inherit; font-size: 11px; }.reader-question > div button { padding: 0 17px; border: 0; border-radius: 0 8px 8px 0; background: #205c45; color: white; font-weight: 800; }.reader-question nav { display: flex; gap: 6px; margin-top: 9px; }.reader-question nav button { padding: 5px 8px; border: 1px solid #dce3de; border-radius: 99px; background: #f5f7f5; color: #596960; font-size: 9px; }.reader-question > p { margin: 9px 0 0; padding-top: 8px; border-top: 1px solid #edf0ed; color: #47715e; font-size: 9px; }
.reader-tabs { display: flex; gap: 5px; margin: 19px 0; padding: 5px; border: 1px solid #dce3de; border-radius: 10px; background: #e9eeea; }.reader-tabs button { flex: 1; padding: 9px 8px; border: 0; border-radius: 7px; background: transparent; color: #65736c; font-size: 10px; font-weight: 800; }.reader-tabs button.active { background: white; color: #1c5a42; box-shadow: 0 3px 10px rgba(35,61,49,.08); }
.story-view > header p, .card-view > header p { margin: 7px 0 18px; color: #78857e; font-size: 10px; }.story-view ol { margin: 0; padding: 0; list-style: none; }.story-view li { display: grid; grid-template-columns: 43px 1fr; position: relative; }.story-view li::before { content: ''; position: absolute; left: 17px; top: 38px; bottom: -4px; width: 1px; background: #ccd7d0; }.story-view li:last-child::before { display: none; }.story-view li > span { width: 35px; height: 35px; display: grid; place-items: center; border: 1px solid #9db5a8; border-radius: 50%; background: #f6f9f7; color: #2a674f; font-size: 9px; font-weight: 900; }.story-view article { margin-bottom: 11px; padding: 13px 15px; border: 1px solid #dce3de; border-radius: 11px; background: white; }.story-view article > small { color: #ef683e; font-size: 8px; font-weight: 900; text-transform: uppercase; }.story-view article h3 { margin: 6px 0 11px; font-family: Georgia, serif; font-size: 15px; font-weight: 500; line-height: 1.4; }
.anchor-row { display: flex; flex-wrap: wrap; gap: 5px; }.anchor-row button, .card-body dd button { padding: 5px 7px; border: 1px solid #d8e1db; border-radius: 6px; background: #f2f6f3; color: #34624e; font-size: 8px; }.claim-section { margin-top: 24px; padding-top: 20px; border-top: 1px solid #dbe2dd; }.claim-section > header { display: flex; justify-content: space-between; align-items: end; }.claim-section > header span { color: #87938c; font-size: 8px; }.claim-grid { display: grid; grid-template-columns: repeat(2, 1fr); gap: 9px; margin-top: 11px; }.claim-grid > button { min-height: 130px; padding: 14px; border: 1px solid #dce3de; border-radius: 11px; background: white; color: #263b31; text-align: left; }.claim-grid > button.selected { border-color: #ef683e; box-shadow: inset 3px 0 #ef683e; }.claim-grid small { color: #ef683e; font-size: 8px; font-weight: 900; text-transform: uppercase; }.claim-grid p { font-family: Georgia, serif; font-size: 13px; line-height: 1.5; }.claim-grid span { color: #79867f; font-size: 8px; }
.card-view > article { display: grid; grid-template-columns: 88px 1fr; gap: 16px; margin-bottom: 11px; padding: 16px; border: 1px solid #dce3de; border-radius: 12px; background: white; transition: opacity .2s; }.card-view > article.muted { opacity: .3; }.card-index { display: grid; place-items: center; height: 64px; border-radius: 10px; background: #dfeee6; color: #215b43; font-weight: 900; }.card-body h3 { margin: 2px 0 12px; font-family: Georgia, serif; font-size: 18px; }.card-body dl { margin: 0; }.card-body dl > div { display: grid; grid-template-columns: 110px 1fr; padding: 9px 0; border-top: 1px solid #edf0ed; }.card-body dt { color: #7a8780; font-size: 9px; font-weight: 800; }.card-body dd { margin: 0; color: #35493f; font-size: 10px; line-height: 1.55; }.card-body dd > span { display: inline-block; margin: 0 4px 4px 0; padding: 4px 6px; border-radius: 5px; background: #f1f4f2; }.artifact-mark { min-height: 80px; display: grid; align-content: center; padding: 10px; border-radius: 9px; background: #e1eee8; color: #235e46; }.artifact-mark.table { background: #fff0dc; color: #8a581a; }.artifact-mark small { font-size: 8px; text-transform: uppercase; }.artifact-mark b { margin-top: 4px; font-size: 13px; }.artifact-mark button { margin-top: 10px; padding: 6px; border: 1px solid currentColor; border-radius: 6px; background: rgba(255,255,255,.6); color: inherit; font-size: 8px; font-weight: 800; }
.reader-graph { padding: 17px; overflow: hidden; border: 1px solid #dce3de; border-radius: 12px; background: white; }.reader-graph > header { display: flex; justify-content: space-between; }.reader-graph > header > span { color: #47725e; font-size: 9px; }.graph-focus { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; margin-top: 14px; padding: 10px; border-radius: 9px; background: #f1f5f2; }.graph-focus b { margin-right: 5px; color: #64746b; font-size: 8px; }.graph-focus button { padding: 5px 7px; border: 1px solid #cbd7cf; border-radius: 99px; background: white; color: #52645a; font-size: 8px; }.graph-focus button.active { border-color: #205c45; background: #205c45; color: white; }.graph-labels { display: grid; grid-template-columns: repeat(3, 1fr); margin: 18px 0 3px; color: #819087; font-size: 8px; font-weight: 900; text-align: center; }.reader-graph svg { width: 100%; max-height: 720px; border-radius: 10px; background: #f5f7f5; }.reader-graph line { stroke: #aebfb5; stroke-width: 1.2; }.reader-graph g { cursor: pointer; }.reader-graph rect { fill: white; stroke: #a8b9af; }.reader-graph g.claim rect { fill: #efffb0; stroke: #a6c53a; }.reader-graph g.experiment rect { fill: #e2eee8; stroke: #74a087; }.reader-graph g.artifact rect { fill: #fff0dc; stroke: #d39b56; }.reader-graph g.evidence rect { fill: #f1efff; stroke: #9d94c7; }.reader-graph text { fill: #31463b; font-size: 8px; }.reader-graph text.edge-label { fill: #718078; font-size: 7px; paint-order: stroke; stroke: #f5f7f5; stroke-width: 4px; }.reader-graph > p { color: #7e8a83; font-size: 8px; }
.evidence-kind { display: flex; justify-content: space-between; margin-top: 20px; color: #ef683e; font-size: 9px; font-weight: 900; text-transform: uppercase; }.evidence-pane h3 { margin: 12px 0; font-family: Georgia, serif; font-size: 21px; }.evidence-pane blockquote { margin: 0; padding: 14px; border-left: 3px solid #ef683e; background: #fff7ed; color: #4d4a3d; font-family: Georgia, serif; font-size: 12px; line-height: 1.65; }.annotation-note { margin: 7px 0 0; color: #8b603b; font-size: 8px; line-height: 1.5; }.evidence-pane dl { margin: 14px 0; }.evidence-pane dl > div { display: grid; grid-template-columns: 72px 1fr; padding: 8px 0; border-bottom: 1px solid #e5eae6; }.evidence-pane dt { color: #859188; font-size: 8px; }.evidence-pane dd { margin: 0; color: #3f5348; font-size: 9px; }.layout-fact-card { margin: 13px 0; padding: 11px; border: 1px solid #cbdcd2; border-radius: 9px; background: #edf5f0; }.layout-fact-card > b { color: #205c45; font-size: 9px; }.layout-fact-card > p { margin: 7px 0; color: #4f6559; font-size: 8px; line-height: 1.5; }.locate-button { width: 100%; padding: 10px; border: 0; border-radius: 8px; background: #205c45; color: white; font-size: 9px; font-weight: 900; }.locate-button:disabled { background: #dfe4e0; color: #89938d; }
.anchor-catalog { display: grid; gap: 5px; margin-top: 24px; }.anchor-catalog > button { display: grid; grid-template-columns: 34px 1fr; gap: 7px; padding: 8px; border: 1px solid transparent; border-radius: 8px; background: transparent; color: #34483e; text-align: left; }.anchor-catalog > button:hover, .anchor-catalog > button.active { border-color: #cdd9d1; background: white; }.anchor-catalog > button > span { color: #ef683e; font-size: 8px; font-weight: 900; }.anchor-catalog b, .anchor-catalog small { display: block; }.anchor-catalog b { font-size: 9px; }.anchor-catalog small { margin-top: 3px; color: #87938c; font-size: 7px; }.boundary-box { margin-top: 22px; padding: 13px; border: 1px solid #edd8bd; border-radius: 9px; background: #fff9ef; }.boundary-box b { color: #865718; font-size: 9px; }.boundary-box ul { margin: 8px 0 0; padding-left: 15px; }.boundary-box li { margin: 5px 0; color: #6f644f; font-size: 8px; line-height: 1.5; }
.reader-state { margin: 70px auto; max-width: 520px; padding: 28px; border: 1px solid #dce3de; border-radius: 14px; background: white; text-align: center; }.reader-state.error { border-color: #edb69e; }.reader-state a { color: #205c45; }
@media (max-width: 1200px) { .reader-grid { grid-template-columns: 210px minmax(450px, 1fr); }.evidence-pane { position: static; grid-column: 1 / -1; max-height: none; border-top: 1px solid #dce3de; border-left: 0; }.paper-heading { align-items: start; flex-direction: column; }.paper-heading dl { min-width: min(100%, 420px); } }
@media (max-width: 820px) { .reader-grid { display: block; }.document-pane, .evidence-pane { position: static; max-height: none; }.document-pane { border-right: 0; border-bottom: 1px solid #dce3de; }.analysis-pane { padding: 22px 15px 60px; }.paper-heading dl { width: 100%; min-width: 0; }.reader-header { padding: 22px 17px; }.reader-integrity { align-items: start; flex-direction: column; margin: 12px; }.claim-grid { grid-template-columns: 1fr; }.reader-question nav { flex-wrap: wrap; }.card-view > article { grid-template-columns: 1fr; } }
</style>
