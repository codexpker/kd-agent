<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute, useRouter } from 'vue-router'

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
type DocumentSection = { id: string; title: string; level: number; page_start: number | null; page_end: number | null; heading_bbox: number[] | null }
type DocumentArtifact = { id: string; artifact_type: 'figure' | 'table'; label: string; caption: string | null; page: number | null; bbox: number[] | null; caption_bbox: number[] | null; markdown: string | null; table_data: string[][] | null }
type DocumentReference = { id: string; artifact_id: string; text: string; page: number | null; bbox: number[] | null }
type DocumentStructure = {
  paper_id: string
  source: 'parsed_pdf' | 'gold_snapshot'
  parser_name: string | null
  parser_version: string | null
  file_sha256: string | null
  page_count: number | null
  sections: DocumentSection[]
  artifacts: DocumentArtifact[]
  references: DocumentReference[]
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
type ReaderTab = 'chain' | 'experiments' | 'artifacts' | 'evidence' | 'graph'
type ChainStage = {
  key: string
  label: string
  summary: string
  sourceIds: string[]
  evidenceIds: string[]
  tab: ReaderTab
  note: string
}

const route = useRoute()
const router = useRouter()
const paperId = computed(() => String(route.params.paperId || ''))
const paper = ref<Paper | null>(null)
const structure = ref<DocumentStructure | null>(null)
const graph = ref<EvidenceGraph | null>(null)
const graphError = ref('')
const activeTab = ref<ReaderTab>('chain')
const selectedEvidenceId = ref<string | null>(null)
const focusedClaimId = ref<string | null>(null)
const question = ref('')
const navigationMessage = ref('')
const loading = ref(true)
const error = ref('')
const previewPage = ref(1)
const previewArtifactId = ref<string | null>(null)
const previewSectionId = ref<string | null>(null)
const previewLoading = ref(false)
const previewError = ref('')
const viewerZoom = ref(100)
const outlineOpen = ref(false)

const normalizeLabel = (value: string) => value.toLowerCase().replace(/[：:]/g, '').replace(/\s+/g, ' ').trim()
const evidenceById = computed(() => new Map((paper.value?.evidence ?? []).map((item) => [item.id, item])))
const claimById = computed(() => new Map((paper.value?.claims ?? []).map((item) => [item.id, item])))
const selectedEvidence = computed(() => selectedEvidenceId.value ? evidenceById.value.get(selectedEvidenceId.value) ?? null : null)
const focusedClaim = computed(() => focusedClaimId.value ? claimById.value.get(focusedClaimId.value) ?? null : null)
const verifiedEvidenceCount = computed(() => paper.value?.evidence.filter((item) => item.verified).length ?? 0)
const sourceLabel = computed(() => structure.value?.source === 'parsed_pdf' ? '真实 PDF 自动解析' : 'Gold 结构快照')

function matchLayoutArtifact(evidence: Evidence | null) {
  if (!evidence || structure.value?.source !== 'parsed_pdf') return null
  const label = normalizeLabel(evidence.label)
  return structure.value.artifacts.find((item) => normalizeLabel(item.label) === label) ?? null
}

function matchLayoutSection(evidence: Evidence | null) {
  if (!evidence || structure.value?.source !== 'parsed_pdf') return null
  const label = normalizeLabel(evidence.label)
  return structure.value.sections.find((item) => normalizeLabel(item.title) === label) ?? null
}

const selectedLayoutArtifact = computed(() => matchLayoutArtifact(selectedEvidence.value))
const selectedLayoutSection = computed(() => matchLayoutSection(selectedEvidence.value))
const selectedLayoutReferences = computed(() => {
  if (!selectedLayoutArtifact.value || !structure.value) return []
  return structure.value.references.filter((item) => item.artifact_id === selectedLayoutArtifact.value?.id)
})
const linkedEvidenceCount = computed(() => paper.value?.evidence.filter((item) => matchLayoutArtifact(item) || matchLayoutSection(item)).length ?? 0)
const previewUrl = computed(() => {
  if (structure.value?.source !== 'parsed_pdf') return ''
  const base = `/api/v1/papers/${encodeURIComponent(paperId.value)}/document-preview`
  if (previewArtifactId.value) return `${base}/artifacts/${encodeURIComponent(previewArtifactId.value)}`
  if (previewSectionId.value) return `${base}/sections/${encodeURIComponent(previewSectionId.value)}`
  return `${base}/pages/${previewPage.value}`
})
const previewTarget = computed(() => {
  if (previewArtifactId.value) return structure.value?.artifacts.find((item) => item.id === previewArtifactId.value)?.label ?? '图表'
  if (previewSectionId.value) return structure.value?.sections.find((item) => item.id === previewSectionId.value)?.title ?? '章节'
  return `第 ${previewPage.value} 页`
})

const coreChain = computed<ChainStage[]>(() => {
  if (!paper.value) return []
  const problem = paper.value.claims.find((item) => item.claim_type === 'problem')
  const gap = paper.value.claims.find((item) => item.claim_type === 'gap')
  const gapMove = paper.value.narrative_moves.find((item) => item.order === 2)
  const methodClaim = paper.value.claims.find((item) => item.claim_type === 'method')
  const methodMoves = paper.value.narrative_moves.filter((item) => item.order === 3 || item.order === 4)
  const claim = focusedClaim.value ?? methodClaim ?? paper.value.claims[0]
  const experiments = paper.value.experiment_intents.filter((item) => claim && item.supports_claim_ids.includes(claim.id))
  const artifacts = paper.value.artifacts.filter((item) => claim && item.supports_claim_ids.includes(claim.id))
  const evidenceIds = [...new Set([...(claim?.evidence_ids ?? []), ...experiments.flatMap((item) => item.evidence_ids), ...artifacts.flatMap((item) => item.evidence_ids)])]
  const boundaryClaims = paper.value.claims.filter((item) => item.claim_type === 'boundary')
  return [
    { key: 'problem', label: 'Problem', summary: problem?.statement ?? '未单独标注', sourceIds: problem ? [problem.id] : [], evidenceIds: problem?.evidence_ids ?? [], tab: 'chain', note: '研究对象与问题表述' },
    { key: 'gap', label: 'Gap', summary: gap?.statement ?? gapMove?.purpose ?? '未单独标注', sourceIds: gap ? [gap.id] : gapMove ? [gapMove.id] : [], evidenceIds: gap?.evidence_ids ?? gapMove?.evidence_ids ?? [], tab: 'chain', note: gap ? '显式 Gap Claim' : '由叙事动作映射，不新增论文事实' },
    { key: 'hypothesis', label: 'Hypothesis', summary: methodClaim?.statement ?? '未单独标注', sourceIds: methodClaim ? [methodClaim.id] : [], evidenceIds: methodClaim?.evidence_ids ?? [], tab: 'chain', note: '以待检验的 method Claim 呈现，不改写为已证实事实' },
    { key: 'method', label: 'Method', summary: methodMoves.map((item) => item.purpose).join('；') || methodClaim?.statement || '未单独标注', sourceIds: methodMoves.map((item) => item.id), evidenceIds: methodMoves.flatMap((item) => item.evidence_ids), tab: 'chain', note: '来自有序 NarrativeMove' },
    { key: 'claim', label: 'Claim', summary: claim?.statement ?? '请选择 Claim', sourceIds: claim ? [claim.id] : [], evidenceIds: claim?.evidence_ids ?? [], tab: 'chain', note: '当前聚焦的科研主张' },
    { key: 'experiment', label: 'Experiment', summary: experiments.map((item) => item.title).join('；') || '当前 Claim 没有关联实验', sourceIds: experiments.map((item) => item.id), evidenceIds: experiments.flatMap((item) => item.evidence_ids), tab: 'experiments', note: '回答研究问题并检验 Claim' },
    { key: 'artifact', label: 'Figure/Table', summary: artifacts.map((item) => `${item.label} ${item.role}`).join('；') || '当前 Claim 没有关联图表', sourceIds: artifacts.map((item) => item.id), evidenceIds: artifacts.flatMap((item) => item.evidence_ids), tab: 'artifacts', note: '把实验结果组织成可审核产物' },
    { key: 'evidence', label: 'Evidence', summary: evidenceIds.map((id) => evidenceById.value.get(id)?.label ?? id).join('；') || '当前 Claim 没有关联证据', sourceIds: evidenceIds, evidenceIds, tab: 'evidence', note: '稳定 EvidenceAnchor，可联动真实页图' },
    { key: 'boundary', label: 'Boundary', summary: boundaryClaims.map((item) => item.statement).join('；') || paper.value.limitations[0] || '未单独标注', sourceIds: boundaryClaims.map((item) => item.id), evidenceIds: boundaryClaims.flatMap((item) => item.evidence_ids), tab: 'chain', note: '限制适用范围，阻止过度结论' },
  ]
})

const graphPaths = computed(() => {
  if (!graph.value) return []
  const claimNode = graph.value.nodes.find((node) => node.node_type === 'claim' && node.local_id === focusedClaimId.value)
    ?? graph.value.nodes.find((node) => node.node_type === 'claim')
  if (!claimNode) return []
  const supportingIds = graph.value.edges
    .filter((edge) => edge.relationship === 'SUPPORTS' && edge.target_id === claimNode.node_id)
    .map((edge) => edge.source_id)
  return supportingIds.flatMap((sourceId) => {
    const entity = graph.value?.nodes.find((node) => node.node_id === sourceId)
    if (!entity) return []
    const evidenceNodeIds = graph.value?.edges
      .filter((edge) => edge.relationship === 'SUPPORTED_BY' && edge.source_id === sourceId)
      .map((edge) => edge.target_id) ?? []
    return [{ entity, evidence: graph.value?.nodes.filter((node) => evidenceNodeIds.includes(node.node_id)) ?? [] }]
  })
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

function routeTab(value: unknown): ReaderTab {
  return ['chain', 'experiments', 'artifacts', 'evidence', 'graph'].includes(String(value)) ? String(value) as ReaderTab : 'chain'
}

function setActiveTab(tab: ReaderTab) {
  activeTab.value = tab
  const query = { ...route.query }
  if (tab === 'chain') delete query.tab
  else query.tab = tab
  void router.replace({ query })
}

function inspectEvidence(id: string, openInspector = true) {
  selectedEvidenceId.value = id
  if (openInspector) setActiveTab('evidence')
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
  previewSectionId.value = null
  previewError.value = ''
  previewLoading.value = true
}

function showLayoutSection(section: DocumentSection | null) {
  if (!section?.page_start) return
  previewPage.value = section.page_start
  previewArtifactId.value = null
  previewSectionId.value = section.id
  previewError.value = ''
  previewLoading.value = true
  outlineOpen.value = false
}

function showLayoutArtifact(artifact: DocumentArtifact | null) {
  if (!artifact?.page) return
  previewPage.value = artifact.page
  previewArtifactId.value = artifact.id
  previewSectionId.value = null
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

function changeZoom(delta: number) {
  viewerZoom.value = Math.min(180, Math.max(70, viewerZoom.value + delta))
}

function activateStage(stage: ChainStage) {
  setActiveTab(stage.tab)
  if (stage.key === 'claim' || stage.key === 'hypothesis') {
    const claimId = stage.sourceIds.find((id) => id.startsWith('cl-'))
    if (claimId) focusClaim(claimId)
  }
  if (stage.tab === 'evidence' && stage.evidenceIds[0]) selectedEvidenceId.value = stage.evidenceIds[0]
}

function navigateQuestion(preset?: string) {
  const value = (preset ?? question.value).trim()
  if (!value) return
  question.value = ''
  if (/实验|消融|基线|变量|experiment|ablation|baseline/i.test(value)) {
    setActiveTab('experiments')
    navigationMessage.value = '已定位到实验意图：研究问题、设计理由、变量、Claim 与证据边界在同一处。'
  } else if (/图|表|figure|table|artifact/i.test(value)) {
    setActiveTab('artifacts')
    navigationMessage.value = '已定位到图表角色；点击“定位原页”可在左侧查看真实 PDF 页。'
  } else if (/关系|图谱|证据链|graph|relation/i.test(value)) {
    setActiveTab('graph')
    navigationMessage.value = '已定位到 Neo4j 关系路径；默认只展开当前 Claim，避免全图毛线团。'
  } else if (/证据|原文|页码|定位|evidence|page/i.test(value)) {
    setActiveTab('evidence')
    navigationMessage.value = '已打开证据透镜：语义注释与 PDF 客观版面事实分开显示。'
  } else {
    setActiveTab('chain')
    navigationMessage.value = '已定位到九阶段核心链；当前离线导航不会生成论文中不存在的回答。'
  }
}

async function loadReader() {
  loading.value = true
  error.value = ''
  graphError.value = ''
  try {
    const [paperResponse, structureResponse, graphResponse] = await Promise.all([
      fetch(`/api/v1/tools/paper-deconstruct/${paperId.value}`, { method: 'POST' }),
      fetch(`/api/v1/papers/${paperId.value}/document-structure`),
      fetch(`/api/v1/papers/${paperId.value}/evidence-graph`),
    ])
    if (paperResponse.status === 404) throw new Error('该论文尚无可公开加载的审核记录。')
    if (!paperResponse.ok || !structureResponse.ok) throw new Error('论文语义记录或文档结构暂时不可用。')
    paper.value = await paperResponse.json()
    structure.value = await structureResponse.json()
    if (graphResponse.ok) graph.value = await graphResponse.json()
    else {
      graph.value = null
      graphError.value = `Neo4j 关系索引不可用（HTTP ${graphResponse.status}）；论文与证据阅读仍可继续。`
    }
    selectedEvidenceId.value = paper.value?.evidence[0]?.id ?? null
    focusedClaimId.value = paper.value?.claims.find((item) => item.claim_type === 'method')?.id ?? paper.value?.claims[0]?.id ?? null
    const firstSection = structure.value?.sections.find((item) => item.page_start) ?? null
    if (firstSection && structure.value?.source === 'parsed_pdf') showLayoutSection(firstSection)
  } catch (reason) {
    error.value = reason instanceof Error ? reason.message : '加载失败'
  } finally {
    loading.value = false
  }
}

watch(paperId, loadReader)
watch(() => route.query.tab, (value) => { activeTab.value = routeTab(value) }, { immediate: true })
watch(selectedEvidence, () => {
  if (selectedLayoutArtifact.value) showLayoutArtifact(selectedLayoutArtifact.value)
  else if (selectedLayoutSection.value) showLayoutSection(selectedLayoutSection.value)
})
onMounted(loadReader)
</script>

<template>
  <main class="paper-reader" data-testid="paper-reader">
    <header class="reader-header">
      <div class="paper-identity">
        <div class="reader-breadcrumb"><RouterLink to="/assistant">科研助理</RouterLink><span>/</span><b>论文逆向工程</b></div>
        <template v-if="paper">
          <div class="status-line"><span>{{ paper.venue }} {{ paper.year }}</span><span class="status-pill warning">{{ paper.status }}</span><span class="status-pill">{{ sourceLabel }}</span></div>
          <h1>{{ paper.title }}</h1>
        </template>
      </div>
      <dl v-if="paper && structure" class="runtime-audit" data-testid="core-service-status">
        <div><dt>语义记录</dt><dd>{{ paper.claims.length }} Claim</dd><small>development seed</small></div>
        <div><dt>PDF 版面</dt><dd>{{ structure.page_count ?? '—' }} 页</dd><small>{{ structure.source }}</small></div>
        <div><dt>证据定位</dt><dd>{{ linkedEvidenceCount }}/{{ paper.evidence.length }}</dd><small>标签闭合</small></div>
        <div><dt>关系索引</dt><dd>{{ graph ? `${graph.nodes.length}/${graph.edges.length}` : '不可用' }}</dd><small>{{ graph?.source ?? '显式降级' }}</small></div>
      </dl>
    </header>

    <div v-if="loading" class="reader-state">正在读取语义记录、PDF 版面与关系索引…</div>
    <div v-else-if="error" class="reader-state error"><b>无法打开论文</b><p>{{ error }}</p><RouterLink to="/assistant">返回科研助理</RouterLink></div>

    <template v-else-if="paper && structure">
      <section class="reader-integrity" data-testid="reader-integrity">
        <b>{{ structure.source === 'parsed_pdf' ? '自动解析，尚未双审' : '无授权解析结果' }}</b>
        <p v-if="structure.source === 'gold_snapshot'">只展示不会伪造位置的结构快照；页码、bbox、真实图注和正文引用保持为空。</p>
        <p v-else>{{ structure.parser_name }} {{ structure.parser_version }} 提供客观版面事实；中文解释是开发注释，不是论文原句或冻结 Gold。</p>
        <span>已核验 {{ verifiedEvidenceCount }}/{{ paper.evidence.length }}</span>
      </section>

      <div class="reader-grid">
        <section class="document-pane" data-testid="document-workspace">
          <header class="viewer-toolbar">
            <button class="outline-toggle" data-testid="outline-toggle" @click="outlineOpen = !outlineOpen">☰ 章节</button>
            <div class="page-controls">
              <button :disabled="previewPage <= 1" @click="showPreviewPage(previewPage - 1)">←</button>
              <b>第 {{ previewPage }} / {{ structure.page_count ?? '—' }} 页</b>
              <button :disabled="previewPage >= (structure.page_count ?? 1)" @click="showPreviewPage(previewPage + 1)">→</button>
            </div>
            <div class="zoom-controls"><button :disabled="viewerZoom <= 70" @click="changeZoom(-15)">−</button><span>{{ viewerZoom }}%</span><button :disabled="viewerZoom >= 180" @click="changeZoom(15)">＋</button></div>
          </header>

          <div v-if="structure.source === 'gold_snapshot'" class="pdf-placeholder" data-testid="pdf-permission-state">
            <div class="paper-sheet"><span>PDF</span><i></i><i></i><i></i><b>原文未在网页分发</b></div>
            <h2>当前没有合法持久化的 PDF 版面结果</h2>
            <p>离线演示仍可审核语义链，但定位按钮保持禁用，不会编造页码或图注。</p>
          </div>

          <div v-else class="viewer-shell" data-testid="private-pdf-preview">
            <aside v-if="outlineOpen" class="outline-drawer">
              <header><div><small>DOCUMENT OUTLINE</small><b>28 个解析章节</b></div><button @click="outlineOpen = false">×</button></header>
              <nav class="section-outline" aria-label="论文章节">
                <button v-for="(section, index) in structure.sections" :key="section.id" :class="{ active: previewSectionId === section.id }" @click="showLayoutSection(section)">
                  <span>{{ String(index + 1).padStart(2, '0') }}</span><div><b>{{ section.title }}</b><small>{{ section.page_start ? `p.${section.page_start}` : '页码待核验' }}</small></div>
                </button>
              </nav>
            </aside>
            <div class="preview-status"><span>本地私有副本</span><b>{{ previewTarget }}</b><small>SHA-256 匹配 · private, no-store</small></div>
            <div class="preview-scroll" data-testid="pdf-viewer-canvas">
              <span v-if="previewLoading" class="preview-loading">正在按 SHA-256 渲染…</span>
              <img :key="previewUrl" :src="previewUrl" :style="{ width: `${viewerZoom}%` }" :alt="`论文第 ${previewPage} 页的本地受控预览`" @load="previewLoading = false; previewError = ''" @error="previewFailed" />
            </div>
            <p v-if="previewError" class="preview-error">{{ previewError }}</p>
          </div>

          <footer class="viewer-footer">
            <div><b>{{ previewArtifactId || previewSectionId ? '定位已联动' : '整页阅读' }}</b><span>{{ previewArtifactId || previewSectionId ? '橙色框标出自动解析的对象、图注或章节标题' : '选择右侧 EvidenceAnchor 可自动定位' }}</span></div>
            <div><span>{{ structure.parser_name }} {{ structure.parser_version }}</span><span>{{ structure.file_sha256?.slice(0, 16) }}…</span></div>
          </footer>
        </section>

        <section class="analysis-pane">
          <form class="reader-question" @submit.prevent="navigateQuestion()">
            <label for="reader-question">阅读目标</label>
            <input id="reader-question" v-model="question" placeholder="例如：消融实验如何支撑方法 Claim？" />
            <button>定位</button>
            <p v-if="navigationMessage">{{ navigationMessage }}</p>
          </form>

          <nav class="reader-tabs" aria-label="逆向工程视图">
            <button :class="{ active: activeTab === 'chain' }" @click="setActiveTab('chain')">核心链</button>
            <button :class="{ active: activeTab === 'experiments' }" @click="setActiveTab('experiments')">实验</button>
            <button :class="{ active: activeTab === 'artifacts' }" @click="setActiveTab('artifacts')">图表</button>
            <button :class="{ active: activeTab === 'evidence' }" @click="setActiveTab('evidence')">证据</button>
            <button :class="{ active: activeTab === 'graph' }" @click="setActiveTab('graph')">Neo4j 路径</button>
          </nav>

          <section v-if="activeTab === 'chain'" class="chain-view" data-testid="core-evidence-chain">
            <header class="view-heading"><div><small>GOLDEN REASONING LOOP</small><h2>一条可追溯的科研论证链</h2></div><span>当前聚焦 {{ focusedClaimId }}</span></header>
            <p class="view-note">每个阶段只引用已有结构化实体；Hypothesis 以待检验的 method Claim 呈现，不新增或改写论文事实。</p>
            <div class="chain-stage-grid">
              <button v-for="(stage, index) in coreChain" :key="stage.key" data-testid="core-chain-stage" @click="activateStage(stage)">
                <span>{{ String(index + 1).padStart(2, '0') }}</span><div><small>{{ stage.label }}</small><b>{{ stage.summary }}</b><em>{{ stage.sourceIds.join(' · ') || 'missing' }}</em></div><i>→</i>
              </button>
            </div>

            <section class="claim-focus">
              <header><b>选择要解释的 Claim</b><span>实验、图表、EvidenceAnchor 与 Neo4j 路径会一起变化</span></header>
              <div><button v-for="claim in paper.claims" :key="claim.id" :class="{ active: focusedClaimId === claim.id }" @click="focusClaim(claim.id)"><small>{{ claim.id }} · {{ claim.claim_type }}</small><span>{{ claim.statement }}</span></button></div>
            </section>

            <section class="story-view" data-testid="narrative-chain">
              <header><b>作者叙事动作</b><span>8 步开发转述 · 点击证据进入原页定位</span></header>
              <ol>
                <li v-for="move in paper.narrative_moves" :key="move.id"><span>{{ String(move.order).padStart(2, '0') }}</span><article><small>{{ move.move }} · {{ move.id }}</small><h3>{{ move.purpose }}</h3><div class="anchor-row"><button v-for="anchor in evidenceFor(move.evidence_ids)" :key="anchor.id" @click="inspectEvidence(anchor.id)">{{ anchor.id }} · {{ anchor.label }}</button></div></article></li>
              </ol>
            </section>
          </section>

          <section v-else-if="activeTab === 'experiments'" class="card-view" data-testid="experiment-intents">
            <header class="view-heading"><div><small>EXPERIMENT INTENT</small><h2>实验为什么存在</h2></div><span>{{ focusedClaimId }}</span></header>
            <p class="view-note">回答研究问题、控制变量并支撑 Claim；这里不生成或推断实验数值。</p>
            <article v-for="experiment in paper.experiment_intents" :key="experiment.id" :class="{ muted: !claimIsRelevant(experiment.supports_claim_ids) }">
              <div class="card-index">{{ experiment.id }}</div><div class="card-body"><h3>{{ experiment.title }}</h3><dl><div><dt>研究问题</dt><dd>{{ experiment.question }}</dd></div><div><dt>设计理由</dt><dd>{{ experiment.design_reason }}</dd></div><div><dt>变量 / 指标</dt><dd><span v-for="variable in experiment.variables" :key="variable">{{ variable }}</span></dd></div><div><dt>支持 Claim</dt><dd><button v-for="claim in claimsFor(experiment.supports_claim_ids)" :key="claim.id" @click="focusClaim(claim.id)">{{ claim.id }} · {{ claim.claim_type }}</button></dd></div></dl><div class="anchor-row"><button v-for="anchor in evidenceFor(experiment.evidence_ids)" :key="anchor.id" @click="inspectEvidence(anchor.id)">{{ anchor.id }} · {{ anchor.label }}</button></div></div>
            </article>
          </section>

          <section v-else-if="activeTab === 'artifacts'" class="card-view" data-testid="artifact-roles">
            <header class="view-heading"><div><small>FIGURE / TABLE ROLE</small><h2>图表承担什么论证作用</h2></div><span>{{ focusedClaimId }}</span></header>
            <p class="view-note">已根据真实 PDF 校正演示涉及的 Figure/Table 标签；角色仍是待双人复核的开发注释。</p>
            <article v-for="artifact in paper.artifacts" :key="artifact.id" :class="{ muted: !claimIsRelevant(artifact.supports_claim_ids) }">
              <div class="artifact-mark" :class="artifact.artifact_type"><small>{{ artifact.artifact_type }}</small><b>{{ artifact.label }}</b><button v-if="structure.source === 'parsed_pdf'" @click="showSemanticArtifact(artifact)">定位原页</button></div><div class="card-body"><h3>{{ artifact.role }}</h3><dl><div><dt>为什么放在这里</dt><dd>{{ artifact.why_here }}</dd></div><div><dt>支持 Claim</dt><dd><button v-for="claim in claimsFor(artifact.supports_claim_ids)" :key="claim.id" @click="focusClaim(claim.id)">{{ claim.id }} · {{ claim.claim_type }}</button></dd></div></dl><div class="anchor-row"><button v-for="anchor in evidenceFor(artifact.evidence_ids)" :key="anchor.id" @click="inspectEvidence(anchor.id)">{{ anchor.id }} · {{ anchor.label }}</button></div></div>
            </article>
          </section>

          <section v-else-if="activeTab === 'evidence'" class="evidence-view" data-testid="evidence-inspector">
            <header class="view-heading"><div><small>EVIDENCE INSPECTOR</small><h2>证据透镜</h2></div><span>{{ linkedEvidenceCount }}/{{ paper.evidence.length }} 可定位</span></header>
            <template v-if="selectedEvidence">
              <article class="evidence-detail">
                <header><span>{{ selectedEvidence.kind }}</span><b>{{ selectedEvidence.id }}</b><em>{{ selectedEvidence.verified ? '已人工核验' : '开发注释待复核' }}</em></header>
                <h3>{{ selectedEvidence.label }}</h3>
                <section class="semantic-layer"><small>科研语义层 · development_seed</small><p>{{ selectedEvidence.excerpt }}</p><span>这是开发转述，不是论文原句。</span></section>
                <section v-if="selectedLayoutArtifact || selectedLayoutSection" class="layout-layer">
                  <small>客观版面层 · {{ structure.parser_name }} 自动解析</small>
                  <h4 v-if="selectedLayoutArtifact">{{ selectedLayoutArtifact.label }} · 第 {{ selectedLayoutArtifact.page }} 页</h4>
                  <h4 v-else-if="selectedLayoutSection">{{ selectedLayoutSection.title }} · 第 {{ selectedLayoutSection.page_start }}–{{ selectedLayoutSection.page_end }} 页</h4>
                  <p v-if="selectedLayoutArtifact?.caption">解析图注：{{ selectedLayoutArtifact.caption }}</p>
                  <p v-if="selectedLayoutReferences.length">正文检测到 {{ selectedLayoutReferences.length }} 处引用，例如：{{ selectedLayoutReferences[0].text }}</p>
                  <p v-if="selectedLayoutArtifact && !selectedLayoutArtifact.bbox">对象框未检测到；定位页仍显示真实图注位置，不伪造对象 bbox。</p>
                  <button class="locate-button" @click="selectedLayoutArtifact ? showLayoutArtifact(selectedLayoutArtifact) : showLayoutSection(selectedLayoutSection)">在左侧真实页图中定位</button>
                </section>
                <button v-else class="locate-button" disabled>没有可匹配的自动解析位置</button>
              </article>
            </template>
            <div class="anchor-catalog"><p>全部 EvidenceAnchor</p><button v-for="item in paper.evidence" :key="item.id" :class="{ active: selectedEvidenceId === item.id }" @click="inspectEvidence(item.id, false)"><span>{{ item.id }}</span><div><b>{{ item.label }}</b><small>{{ matchLayoutArtifact(item) || matchLayoutSection(item) ? '可定位真实页' : '没有版面映射' }}</small></div></button></div>
            <section class="boundary-box"><b>当前不能得出的结论</b><ul><li v-for="item in paper.limitations" :key="item">{{ item }}</li></ul></section>
          </section>

          <section v-else class="graph-view" data-testid="paper-evidence-graph">
            <header class="view-heading"><div><small>NEO4J CLAIM PATH</small><h2>按 Claim 阅读关系，而不是看毛线团</h2></div><span :class="{ danger: graphError }">{{ graph?.source ?? 'unavailable' }}</span></header>
            <p v-if="graphError" class="graph-error">{{ graphError }}</p>
            <template v-else-if="graph">
              <section class="graph-proof"><div><small>索引来源</small><b>{{ graph.source }}</b></div><div><small>完整索引</small><b>{{ graph.nodes.length }} 节点 / {{ graph.edges.length }} 关系</b></div><div><small>权威边界</small><b>MySQL 是事实源</b></div></section>
              <div class="graph-focus"><b>当前 Claim</b><button v-for="claim in paper.claims" :key="claim.id" :class="{ active: focusedClaimId === claim.id }" @click="focusClaim(claim.id)">{{ claim.id }} · {{ claim.claim_type }}</button></div>
              <article class="graph-claim"><small>CLAIM · {{ focusedClaim?.id }}</small><h3>{{ focusedClaim?.statement }}</h3></article>
              <div class="graph-path-list">
                <article v-for="path in graphPaths" :key="path.entity.node_id" data-testid="graph-path">
                  <div class="relation-arrow"><span>SUPPORTS</span><i>↓</i></div>
                  <section class="graph-entity" :class="path.entity.node_type"><small>{{ path.entity.node_type }} · {{ path.entity.local_id }}</small><h4>{{ path.entity.label }}</h4><p>{{ path.entity.summary }}</p></section>
                  <div class="relation-arrow"><span>SUPPORTED_BY</span><i>↓</i></div>
                  <div class="graph-evidence-list"><button v-for="node in path.evidence" :key="node.node_id" @click="node.local_id && inspectEvidence(node.local_id)"><span>{{ node.local_id }}</span><div><b>{{ node.label }}</b><small>{{ node.verified ? 'verified' : 'unverified · 点击定位' }}</small></div></button></div>
                </article>
                <p v-if="!graphPaths.length" class="graph-empty">当前 Claim 没有 Experiment/Artifact → Evidence 的闭合路径。</p>
              </div>
              <p v-for="warning in graph.warnings" :key="warning" class="graph-warning">{{ warning }}</p>
            </template>
          </section>
        </section>
      </div>
    </template>
  </main>
</template>

<style scoped>
.paper-reader { max-width: none; height: calc(100vh - 66px); overflow: hidden; background: #edf1ed; color: #193027; }
.reader-header { min-height: 112px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 24px; align-items: center; padding: 14px 22px; border-bottom: 1px solid #d7ded9; background: #fbfcfa; }
.reader-breadcrumb { display: flex; gap: 7px; color: #819087; font-size: 9px; }.reader-breadcrumb a { color: #28654e; text-decoration: none; }.reader-breadcrumb b { color: #506158; }
.status-line { display: flex; gap: 6px; align-items: center; margin-top: 9px; }.status-line > span:first-child { color: #ef683e; font-size: 9px; font-weight: 900; letter-spacing: 1px; }.status-pill { padding: 4px 7px; border-radius: 99px; background: #e3eee8; color: #28634c; font-size: 8px; font-weight: 800; }.status-pill.warning { background: #fff0d6; color: #875411; }
.paper-identity h1 { margin: 5px 0 0; overflow: hidden; font-family: Georgia, 'Times New Roman', serif; font-size: clamp(21px, 2.1vw, 31px); font-weight: 500; line-height: 1.1; text-overflow: ellipsis; white-space: nowrap; }
.runtime-audit { display: grid; grid-template-columns: repeat(4, 116px); margin: 0; overflow: hidden; border: 1px solid #d9e1dc; border-radius: 12px; background: white; }.runtime-audit div { padding: 10px 12px; border-right: 1px solid #e7ebe8; }.runtime-audit div:last-child { border: 0; }.runtime-audit dt { color: #849189; font-size: 8px; }.runtime-audit dd { margin: 4px 0 2px; color: #205c45; font-size: 15px; font-weight: 900; }.runtime-audit small { color: #94a098; font-size: 7px; }
.reader-integrity { min-height: 40px; display: flex; gap: 12px; align-items: center; padding: 7px 22px; border-bottom: 1px solid #e6d2a7; background: #fff7e5; }.reader-integrity b { color: #8a5919; font-size: 9px; white-space: nowrap; }.reader-integrity p { flex: 1; margin: 0; color: #705d3d; font-size: 9px; line-height: 1.45; }.reader-integrity span { color: #8a5919; font-size: 8px; white-space: nowrap; }
.reader-grid { height: calc(100vh - 218px); min-height: 500px; display: grid; grid-template-columns: minmax(580px, 1.12fr) minmax(460px, .88fr); }
.document-pane { min-width: 0; min-height: 0; display: grid; grid-template-rows: 46px minmax(0, 1fr) 48px; border-right: 1px solid #cfd8d2; background: #27322d; }
.viewer-toolbar { display: grid; grid-template-columns: 1fr auto 1fr; align-items: center; gap: 10px; padding: 7px 12px; border-bottom: 1px solid #3d4943; background: #1b2520; color: white; }.viewer-toolbar button { min-height: 30px; padding: 5px 9px; border: 1px solid #54625b; border-radius: 7px; background: #303d37; color: #edf4ef; font-size: 9px; }.viewer-toolbar button:disabled { opacity: .3; }.outline-toggle { justify-self: start; }.page-controls, .zoom-controls { display: flex; gap: 7px; align-items: center; }.page-controls b { min-width: 90px; text-align: center; font-size: 10px; }.zoom-controls { justify-self: end; }.zoom-controls span { min-width: 40px; color: #b9c5be; font-size: 9px; text-align: center; }
.viewer-shell { min-height: 0; position: relative; overflow: hidden; }.preview-status { position: absolute; top: 12px; left: 18px; z-index: 3; display: grid; gap: 2px; max-width: calc(100% - 36px); padding: 8px 10px; border-radius: 8px; background: rgba(20,33,27,.9); color: white; box-shadow: 0 5px 18px rgba(0,0,0,.18); }.preview-status span { color: #a9d8c0; font-size: 7px; font-weight: 900; text-transform: uppercase; }.preview-status b { overflow: hidden; font-size: 10px; text-overflow: ellipsis; white-space: nowrap; }.preview-status small { color: #abb8b1; font-size: 7px; }
.preview-scroll { width: 100%; height: 100%; overflow: auto; padding: 62px 26px 34px; background: #59625d; text-align: center; }.preview-scroll img { display: block; height: auto; margin: 0 auto; background: white; box-shadow: 0 12px 35px rgba(0,0,0,.28); }.preview-loading { position: absolute; z-index: 2; top: 50%; left: 50%; translate: -50% -50%; padding: 8px 10px; border-radius: 7px; background: rgba(20,36,29,.88); color: white; font-size: 9px; }.preview-error { position: absolute; right: 15px; bottom: 12px; left: 15px; z-index: 4; margin: 0; padding: 9px; border-radius: 7px; background: #9d3f27; color: white; font-size: 9px; }
.outline-drawer { position: absolute; inset: 0 auto 0 0; z-index: 6; width: min(330px, 78%); overflow-y: auto; border-right: 1px solid #bcc9c1; background: #f4f7f4; box-shadow: 14px 0 34px rgba(11,28,20,.24); }.outline-drawer > header { position: sticky; top: 0; z-index: 1; display: flex; justify-content: space-between; align-items: center; padding: 14px; border-bottom: 1px solid #d8e0da; background: #edf3ef; }.outline-drawer header div { display: grid; gap: 3px; }.outline-drawer header small { color: #7a8a81; font-size: 7px; letter-spacing: 1px; }.outline-drawer header b { font-size: 11px; }.outline-drawer header button { border: 0; background: transparent; font-size: 21px; }.section-outline { display: grid; padding: 8px; }.section-outline button { display: grid; grid-template-columns: 27px 1fr; gap: 8px; padding: 9px; border: 0; border-radius: 8px; background: transparent; color: #31473c; text-align: left; }.section-outline button:hover, .section-outline button.active { background: white; }.section-outline button > span { color: #ef683e; font-size: 8px; font-weight: 900; }.section-outline button div { display: grid; gap: 3px; }.section-outline b { font-size: 9px; }.section-outline small { color: #8b9790; font-size: 7px; }
.viewer-footer { display: flex; justify-content: space-between; gap: 18px; align-items: center; padding: 7px 13px; border-top: 1px solid #3d4943; background: #1b2520; color: #dce5df; }.viewer-footer > div { display: grid; gap: 2px; }.viewer-footer > div:last-child { text-align: right; }.viewer-footer b { color: #a8d9c0; font-size: 8px; }.viewer-footer span { color: #9ca9a2; font-size: 7px; }
.pdf-placeholder { display: grid; place-content: center; justify-items: center; padding: 30px; background: #e9eeea; text-align: center; }.paper-sheet { width: 180px; height: 230px; display: flex; flex-direction: column; gap: 12px; padding: 22px 18px; border: 1px solid #d6ddd8; border-radius: 5px; background: white; box-shadow: 0 12px 28px rgba(35,58,47,.12); text-align: left; }.paper-sheet span { color: #ef683e; font-size: 11px; font-weight: 900; }.paper-sheet i { display: block; height: 4px; background: #dce3de; }.paper-sheet i:nth-of-type(2) { width: 80%; }.paper-sheet b { margin-top: auto; color: #7b8881; font-size: 9px; text-align: center; }.pdf-placeholder h2 { margin: 20px 0 7px; font-size: 16px; }.pdf-placeholder p { max-width: 420px; margin: 0; color: #69766f; font-size: 10px; line-height: 1.6; }
.analysis-pane { min-width: 0; min-height: 0; overflow-y: auto; padding: 14px 18px 60px; background: #f5f7f5; }
.reader-question { display: grid; grid-template-columns: auto minmax(0, 1fr) auto; align-items: center; overflow: hidden; border: 1px solid #d5ddd8; border-radius: 10px; background: white; }.reader-question label { padding-left: 12px; color: #42624f; font-size: 9px; font-weight: 900; }.reader-question input { min-width: 0; padding: 10px 12px; border: 0; outline: 0; color: #263b31; font-size: 10px; }.reader-question > button { align-self: stretch; padding: 0 16px; border: 0; background: #205c45; color: white; font-size: 10px; font-weight: 900; }.reader-question p { grid-column: 1 / -1; margin: 0; padding: 7px 12px; border-top: 1px solid #edf0ed; color: #47715e; font-size: 8px; }
.reader-tabs { position: sticky; top: -14px; z-index: 5; display: grid; grid-template-columns: repeat(5, 1fr); gap: 4px; margin: 10px 0 14px; padding: 4px; border: 1px solid #d5ddd8; border-radius: 9px; background: #e6ece8; }.reader-tabs button { padding: 8px 5px; border: 0; border-radius: 6px; background: transparent; color: #66756d; font-size: 9px; font-weight: 800; }.reader-tabs button.active { background: white; color: #1c5a42; box-shadow: 0 2px 8px rgba(35,61,49,.08); }
.view-heading { display: flex; justify-content: space-between; gap: 16px; align-items: end; }.view-heading small { color: #87958d; font-size: 7px; font-weight: 900; letter-spacing: 1.2px; }.view-heading h2 { margin: 4px 0 0; font-family: Georgia, serif; font-size: 21px; font-weight: 500; }.view-heading > span { padding: 5px 7px; border-radius: 6px; background: #dfe9e3; color: #3c6955; font-size: 8px; font-weight: 800; }.view-heading > span.danger { background: #ffe0d5; color: #963e24; }.view-note { margin: 7px 0 13px; color: #738179; font-size: 9px; line-height: 1.5; }
.chain-stage-grid { display: grid; gap: 6px; }.chain-stage-grid > button { min-height: 65px; display: grid; grid-template-columns: 30px 1fr 18px; gap: 9px; align-items: center; padding: 9px 11px; border: 1px solid #d7dfda; border-radius: 10px; background: white; color: #263b31; text-align: left; }.chain-stage-grid > button:hover { border-color: #80a893; box-shadow: inset 3px 0 #205c45; }.chain-stage-grid > button > span { width: 26px; height: 26px; display: grid; place-items: center; border-radius: 50%; background: #e5f0ea; color: #205c45; font-size: 8px; font-weight: 900; }.chain-stage-grid button div { min-width: 0; display: grid; gap: 3px; }.chain-stage-grid small { color: #ef683e; font-size: 7px; font-weight: 900; letter-spacing: .8px; }.chain-stage-grid b { overflow: hidden; font-family: Georgia, serif; font-size: 11px; font-weight: 500; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }.chain-stage-grid em { color: #88958e; font-size: 7px; font-style: normal; }.chain-stage-grid i { color: #6f897b; font-style: normal; }
.claim-focus { margin-top: 16px; padding: 12px; border: 1px solid #d6dfd9; border-radius: 10px; background: #edf2ef; }.claim-focus > header { display: flex; justify-content: space-between; gap: 12px; }.claim-focus header b { font-size: 9px; }.claim-focus header span { color: #78867f; font-size: 7px; }.claim-focus > div { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; margin-top: 8px; }.claim-focus button { min-height: 72px; display: grid; gap: 5px; padding: 9px; border: 1px solid #d4ddd7; border-radius: 8px; background: white; color: #34473d; text-align: left; }.claim-focus button.active { border-color: #ef683e; box-shadow: inset 3px 0 #ef683e; }.claim-focus small { color: #ef683e; font-size: 7px; font-weight: 900; }.claim-focus button span { font-size: 9px; line-height: 1.45; }
.story-view { margin-top: 17px; padding-top: 14px; border-top: 1px solid #d9e0db; }.story-view > header { display: flex; justify-content: space-between; }.story-view header b { font-size: 10px; }.story-view header span { color: #819087; font-size: 7px; }.story-view ol { margin: 10px 0 0; padding: 0; list-style: none; }.story-view li { display: grid; grid-template-columns: 31px 1fr; position: relative; }.story-view li::before { content: ''; position: absolute; left: 13px; top: 31px; bottom: -3px; width: 1px; background: #c9d5ce; }.story-view li:last-child::before { display: none; }.story-view li > span { width: 27px; height: 27px; display: grid; place-items: center; border: 1px solid #a6bbaf; border-radius: 50%; background: #f7f9f7; color: #2a674f; font-size: 7px; font-weight: 900; }.story-view article { margin-bottom: 7px; padding: 9px 11px; border: 1px solid #dbe2dd; border-radius: 9px; background: white; }.story-view article > small { color: #ef683e; font-size: 7px; font-weight: 900; }.story-view article h3 { margin: 4px 0 7px; font-family: Georgia, serif; font-size: 11px; font-weight: 500; line-height: 1.4; }
.anchor-row { display: flex; flex-wrap: wrap; gap: 4px; }.anchor-row button, .card-body dd button { padding: 4px 6px; border: 1px solid #d5dfd8; border-radius: 5px; background: #f1f5f2; color: #34624e; font-size: 7px; }
.card-view > article { display: grid; grid-template-columns: 76px 1fr; gap: 13px; margin-bottom: 9px; padding: 13px; border: 1px solid #d9e0db; border-radius: 10px; background: white; transition: opacity .2s; }.card-view > article.muted { opacity: .35; }.card-index { display: grid; place-items: center; height: 58px; border-radius: 9px; background: #dfeee6; color: #215b43; font-size: 11px; font-weight: 900; }.card-body h3 { margin: 1px 0 9px; font-family: Georgia, serif; font-size: 16px; }.card-body dl { margin: 0; }.card-body dl > div { display: grid; grid-template-columns: 92px 1fr; padding: 7px 0; border-top: 1px solid #edf0ed; }.card-body dt { color: #7a8780; font-size: 8px; font-weight: 800; }.card-body dd { margin: 0; color: #35493f; font-size: 9px; line-height: 1.55; }.card-body dd > span { display: inline-block; margin: 0 3px 3px 0; padding: 3px 5px; border-radius: 4px; background: #f1f4f2; }.artifact-mark { min-height: 76px; display: grid; align-content: center; padding: 9px; border-radius: 8px; background: #e1eee8; color: #235e46; }.artifact-mark.table { background: #fff0dc; color: #8a581a; }.artifact-mark small { font-size: 7px; text-transform: uppercase; }.artifact-mark b { margin-top: 3px; font-size: 12px; }.artifact-mark button { margin-top: 8px; padding: 5px; border: 1px solid currentColor; border-radius: 5px; background: rgba(255,255,255,.65); color: inherit; font-size: 7px; font-weight: 800; }
.evidence-detail { margin-top: 12px; padding: 14px; border: 1px solid #d7dfda; border-radius: 11px; background: white; }.evidence-detail > header { display: flex; gap: 7px; align-items: center; color: #ef683e; font-size: 8px; text-transform: uppercase; }.evidence-detail header em { margin-left: auto; padding: 4px 6px; border-radius: 99px; background: #fff0dc; color: #8a5919; font-size: 7px; font-style: normal; }.evidence-detail h3 { margin: 10px 0; font-family: Georgia, serif; font-size: 23px; }.semantic-layer, .layout-layer { padding: 12px; border-radius: 8px; }.semantic-layer { border-left: 3px solid #ef683e; background: #fff7ed; }.layout-layer { margin-top: 9px; border-left: 3px solid #2d7556; background: #edf5f0; }.semantic-layer small, .layout-layer small { color: #7a6754; font-size: 7px; font-weight: 900; letter-spacing: .8px; }.layout-layer small { color: #46705c; }.semantic-layer p { margin: 8px 0; font-family: Georgia, serif; font-size: 12px; line-height: 1.55; }.semantic-layer span, .layout-layer p { color: #6e796f; font-size: 8px; line-height: 1.5; }.layout-layer h4 { margin: 8px 0; font-size: 12px; }.locate-button { width: 100%; margin-top: 8px; padding: 9px; border: 0; border-radius: 7px; background: #205c45; color: white; font-size: 8px; font-weight: 900; }.locate-button:disabled { background: #dfe4e0; color: #89938d; }
.anchor-catalog { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; margin-top: 15px; }.anchor-catalog > p { grid-column: 1 / -1; margin: 0 0 3px; color: #849189; font-size: 8px; font-weight: 900; }.anchor-catalog > button { display: grid; grid-template-columns: 31px 1fr; gap: 6px; padding: 8px; border: 1px solid #e0e5e1; border-radius: 8px; background: white; color: #34483e; text-align: left; }.anchor-catalog > button.active { border-color: #ef683e; box-shadow: inset 3px 0 #ef683e; }.anchor-catalog > button > span { color: #ef683e; font-size: 7px; font-weight: 900; }.anchor-catalog b, .anchor-catalog small { display: block; }.anchor-catalog b { font-size: 8px; }.anchor-catalog small { margin-top: 2px; color: #728178; font-size: 7px; }.boundary-box { margin-top: 14px; padding: 12px; border: 1px solid #ead5b7; border-radius: 9px; background: #fff9ef; }.boundary-box b { color: #865718; font-size: 9px; }.boundary-box ul { margin: 7px 0 0; padding-left: 15px; }.boundary-box li { margin: 4px 0; color: #6f644f; font-size: 8px; line-height: 1.5; }
.graph-error { padding: 12px; border-left: 4px solid #ef683e; background: #ffe6dc; color: #8e3c24; font-size: 9px; }.graph-proof { display: grid; grid-template-columns: repeat(3, 1fr); gap: 6px; margin: 12px 0; }.graph-proof div { display: grid; gap: 4px; padding: 10px; border: 1px solid #d6dfd9; border-radius: 8px; background: white; }.graph-proof small { color: #829087; font-size: 7px; }.graph-proof b { color: #245d45; font-size: 9px; }.graph-focus { display: flex; flex-wrap: wrap; gap: 5px; align-items: center; margin-bottom: 9px; }.graph-focus b { margin-right: 3px; color: #66766d; font-size: 8px; }.graph-focus button { padding: 5px 7px; border: 1px solid #cbd7cf; border-radius: 99px; background: white; color: #52645a; font-size: 7px; }.graph-focus button.active { border-color: #205c45; background: #205c45; color: white; }.graph-claim { padding: 13px; border: 1px solid #a8c250; border-radius: 9px; background: #f3ffca; }.graph-claim small { color: #668115; font-size: 7px; font-weight: 900; }.graph-claim h3 { margin: 6px 0 0; font-family: Georgia, serif; font-size: 14px; line-height: 1.45; }.graph-path-list { display: grid; gap: 10px; }.graph-path-list > article { padding-left: 18px; border-left: 2px solid #a9bbb0; }.relation-arrow { display: flex; gap: 8px; align-items: center; min-height: 28px; color: #718078; }.relation-arrow span { font-size: 7px; font-weight: 900; }.relation-arrow i { color: #ef683e; font-style: normal; }.graph-entity { padding: 11px; border: 1px solid #b8cbbf; border-radius: 8px; background: #e9f2ed; }.graph-entity.artifact { border-color: #e0bd83; background: #fff3df; }.graph-entity small { color: #4c7662; font-size: 7px; font-weight: 900; }.graph-entity h4 { margin: 5px 0; font-size: 12px; }.graph-entity p { margin: 0; color: #65736c; font-size: 8px; line-height: 1.45; }.graph-evidence-list { display: grid; grid-template-columns: 1fr 1fr; gap: 5px; }.graph-evidence-list button { display: grid; grid-template-columns: 32px 1fr; gap: 6px; padding: 8px; border: 1px solid #cfc9e8; border-radius: 7px; background: #f4f1ff; color: #3c3b4a; text-align: left; }.graph-evidence-list button > span { color: #6e61a3; font-size: 7px; font-weight: 900; }.graph-evidence-list b, .graph-evidence-list small { display: block; }.graph-evidence-list b { font-size: 8px; }.graph-evidence-list small { margin-top: 2px; color: #817c97; font-size: 6px; }.graph-empty, .graph-warning { color: #7d8982; font-size: 8px; }.graph-warning { padding-top: 8px; border-top: 1px solid #dbe2dd; }
.reader-state { margin: 70px auto; max-width: 520px; padding: 28px; border: 1px solid #dce3de; border-radius: 14px; background: white; text-align: center; }.reader-state.error { border-color: #edb69e; }.reader-state a { color: #205c45; }
@media (max-width: 1120px) { .runtime-audit { grid-template-columns: repeat(2, 105px); }.runtime-audit div:nth-child(2) { border-right: 0; }.runtime-audit div:nth-child(-n+2) { border-bottom: 1px solid #e7ebe8; }.reader-grid { grid-template-columns: minmax(520px, 1.05fr) minmax(410px, .95fr); } }
@media (max-width: 900px) { .paper-reader { height: auto; overflow: visible; }.reader-header { grid-template-columns: 1fr; }.paper-identity h1 { white-space: normal; }.runtime-audit { grid-template-columns: repeat(4, 1fr); }.runtime-audit div { border-bottom: 0 !important; border-right: 1px solid #e7ebe8 !important; }.runtime-audit div:last-child { border-right: 0 !important; }.reader-grid { height: auto; display: block; }.document-pane { height: 72vh; min-height: 560px; border-right: 0; border-bottom: 1px solid #cfd8d2; }.analysis-pane { overflow: visible; }.reader-integrity { align-items: start; flex-wrap: wrap; } }
@media (max-width: 600px) { .reader-header { padding: 12px; }.runtime-audit { grid-template-columns: repeat(2, 1fr); }.runtime-audit div:nth-child(2) { border-right: 0 !important; }.runtime-audit div:nth-child(-n+2) { border-bottom: 1px solid #e7ebe8 !important; }.document-pane { height: 68vh; min-height: 500px; }.viewer-toolbar { grid-template-columns: auto 1fr; }.zoom-controls { display: none; }.page-controls { justify-self: end; }.analysis-pane { padding: 12px 10px 40px; }.reader-tabs { overflow-x: auto; }.reader-tabs button { min-width: 74px; }.claim-focus > div, .anchor-catalog, .graph-evidence-list, .graph-proof { grid-template-columns: 1fr; }.card-view > article { grid-template-columns: 1fr; }.reader-question label { display: none; }.reader-question { grid-template-columns: 1fr auto; }.reader-question p { grid-column: 1 / -1; } }
</style>
