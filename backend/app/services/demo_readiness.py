from collections.abc import Callable
from typing import Protocol

from app.demo_models import (
    DemoReadinessCheck,
    DemoReadinessResponse,
    DemoTourStep,
)
from app.evidence_graph_models import EvidenceGraphResponse
from app.gold_dataset import GoldDataset
from app.models import DocumentStructure


DEMO_PAPER_ID = "anomaly-transformer-2022"


class ReadinessSettings(Protocol):
    document_structure_backend: str
    evidence_graph_backend: str
    private_pdf_preview_enabled: bool
    assistant_backend: str
    assistant_session_backend: str
    astron_agent_api_key: str
    astron_agent_api_secret: str
    astron_agent_flow_id: str


class DemoReadinessService:
    """Explain whether the golden demo works without leaking local configuration."""

    def __init__(
        self,
        dataset: GoldDataset,
        settings: ReadinessSettings,
        document_loader: Callable[[str], DocumentStructure],
        graph_loader: Callable[[str], EvidenceGraphResponse],
        private_pdf_probe: Callable[[DocumentStructure], None],
    ) -> None:
        self._dataset = dataset
        self._settings = settings
        self._document_loader = document_loader
        self._graph_loader = graph_loader
        self._private_pdf_probe = private_pdf_probe

    def get(self, paper_id: str = DEMO_PAPER_ID) -> DemoReadinessResponse:
        infrastructure_mode = any(
            (
                self._settings.document_structure_backend == "mysql",
                self._settings.evidence_graph_backend == "neo4j",
                self._settings.private_pdf_preview_enabled,
            )
        )
        checks = [self._gold_check(paper_id)]
        document = self._document_check(paper_id, checks, infrastructure_mode)
        self._private_pdf_check(document, checks, infrastructure_mode)
        self._graph_check(paper_id, checks, infrastructure_mode)
        checks.append(self._assistant_check())
        checks.append(self._assistant_storage_check(infrastructure_mode))

        required = [item for item in checks if item.required_for_current_mode]
        if any(item.status == "blocked" for item in required):
            status = "blocked"
        elif any(item.status != "ready" for item in required):
            status = "degraded"
        else:
            status = "ready"
        return DemoReadinessResponse(
            status=status,
            runtime_mode=(
                "local_infrastructure" if infrastructure_mode else "offline_demo"
            ),
            paper_id=paper_id,
            checks=checks,
            tour_steps=_tour_steps(paper_id),
        )

    def _gold_check(self, paper_id: str) -> DemoReadinessCheck:
        record = self._dataset.get(paper_id)
        if record is None:
            return DemoReadinessCheck(
                check_id="paper_seed",
                label="论文语义种子",
                status="blocked",
                required_for_current_mode=True,
                detail="演示论文没有可公开加载的结构化记录。",
                action="恢复经过门禁的开发种子或双审记录后重试。",
            )
        return DemoReadinessCheck(
            check_id="paper_seed",
            label="论文语义种子",
            status="ready",
            required_for_current_mode=True,
            detail=(
                f"{len(record.claims)} 个 Claim、"
                f"{len(record.experiment_intents)} 个实验意图、"
                f"{len(record.artifacts)} 个图表角色和 "
                f"{len(record.evidence)} 个 EvidenceAnchor 可用。"
            ),
        )

    def _document_check(
        self,
        paper_id: str,
        checks: list[DemoReadinessCheck],
        infrastructure_mode: bool,
    ) -> DocumentStructure | None:
        real_document_required = (
            self._settings.document_structure_backend == "mysql"
        )
        try:
            document = self._document_loader(paper_id)
        except Exception:
            checks.append(
                DemoReadinessCheck(
                    check_id="document_structure",
                    label="论文版面结构",
                    status="blocked",
                    required_for_current_mode=True,
                    detail="文档结构接口当前不可用。",
                    action="检查MySQL连接、迁移和DOCUMENT_STRUCTURE_BACKEND。",
                )
            )
            return None

        if document.source == "parsed_pdf":
            checks.append(
                DemoReadinessCheck(
                    check_id="document_structure",
                    label="论文版面结构",
                    status="ready",
                    required_for_current_mode=True,
                    detail=(
                        f"MySQL返回真实 parsed_pdf：{document.page_count or 0} 页、"
                        f"{len(document.sections)} 个章节、"
                        f"{len(document.artifacts)} 个Figure/Table。"
                    ),
                )
            )
        elif real_document_required or infrastructure_mode:
            checks.append(
                DemoReadinessCheck(
                    check_id="document_structure",
                    label="论文版面结构",
                    status="blocked" if real_document_required else "warning",
                    required_for_current_mode=True,
                    detail=(
                        "已要求MySQL版面事实，但当前只得到gold_snapshot降级结果。"
                        if real_document_required
                        else "本地基础设施模式仍在使用gold_snapshot，没有真实PDF版面事实。"
                    ),
                    action="确认授权PDF解析结果已持久化并与演示paper_id一致。",
                )
            )
        else:
            checks.append(
                DemoReadinessCheck(
                    check_id="document_structure",
                    label="论文版面结构",
                    status="ready",
                    required_for_current_mode=True,
                    detail="离线gold_snapshot可用；页码、bbox和图注保持为空，不伪造PDF事实。",
                )
            )
        return document

    def _private_pdf_check(
        self,
        document: DocumentStructure | None,
        checks: list[DemoReadinessCheck],
        infrastructure_mode: bool,
    ) -> None:
        required = infrastructure_mode
        if not self._settings.private_pdf_preview_enabled:
            checks.append(
                DemoReadinessCheck(
                    check_id="private_pdf_preview",
                    label="私有PDF页图",
                    status="blocked" if required else "not_configured",
                    required_for_current_mode=required,
                    detail=(
                        "本地基础设施演示未启用私有PDF预览。"
                        if required
                        else "离线演示不读取本地PDF，仍可使用结构化语义链。"
                    ),
                    action=(
                        "在本地模式配置PRIVATE_PDF_PREVIEW_ENABLED和授权PDF目录。"
                        if required
                        else None
                    ),
                )
            )
            return
        if document is None or document.source != "parsed_pdf":
            checks.append(
                DemoReadinessCheck(
                    check_id="private_pdf_preview",
                    label="私有PDF页图",
                    status="blocked",
                    required_for_current_mode=required,
                    detail="没有可与本地文件SHA-256闭合的parsed_pdf记录。",
                    action="先完成授权PDF解析持久化，再启用页图预览。",
                )
            )
            return
        try:
            self._private_pdf_probe(document)
        except Exception:
            checks.append(
                DemoReadinessCheck(
                    check_id="private_pdf_preview",
                    label="私有PDF页图",
                    status="blocked",
                    required_for_current_mode=required,
                    detail="已启用私有预览，但未找到SHA-256匹配且可渲染的本地PDF。",
                    action="检查授权PDF目录、文件哈希和PyMuPDF依赖。",
                )
            )
            return
        checks.append(
            DemoReadinessCheck(
                check_id="private_pdf_preview",
                label="私有PDF页图",
                status="ready",
                required_for_current_mode=required,
                detail="授权本地副本与MySQL中的SHA-256匹配；仅即时返回不可缓存PNG。",
            )
        )

    def _graph_check(
        self,
        paper_id: str,
        checks: list[DemoReadinessCheck],
        infrastructure_mode: bool,
    ) -> None:
        real_graph_required = self._settings.evidence_graph_backend == "neo4j"
        try:
            graph = self._graph_loader(paper_id)
        except Exception:
            checks.append(
                DemoReadinessCheck(
                    check_id="evidence_graph",
                    label="论证关系索引",
                    status="blocked",
                    required_for_current_mode=True,
                    detail="论证关系接口当前不可用。",
                    action="检查Neo4j连接或切回gold离线关系源。",
                )
            )
            return
        if graph.source == "neo4j":
            detail = (
                f"Neo4j真实返回{len(graph.nodes)}个节点和"
                f"{len(graph.edges)}条关系；MySQL仍是权威事实源。"
            )
            status = "ready"
        elif real_graph_required:
            detail = "已要求Neo4j关系索引，但当前只得到gold_snapshot。"
            status = "blocked"
        elif infrastructure_mode:
            detail = "本地基础设施模式仍在使用gold_snapshot关系源，尚未验证Neo4j。"
            status = "warning"
        else:
            detail = (
                f"离线gold_snapshot关系源可用：{len(graph.nodes)}个节点、"
                f"{len(graph.edges)}条关系。"
            )
            status = "ready"
        checks.append(
            DemoReadinessCheck(
                check_id="evidence_graph",
                label="论证关系索引",
                status=status,
                required_for_current_mode=True,
                detail=detail,
                action=(
                    "确认Neo4j已启动、完成Gold同步并将EVIDENCE_GRAPH_BACKEND设为neo4j。"
                    if status != "ready"
                    else None
                ),
            )
        )

    def _assistant_check(self) -> DemoReadinessCheck:
        if self._settings.assistant_backend == "offline":
            return DemoReadinessCheck(
                check_id="assistant_backend",
                label="科研助理语言层",
                status="ready",
                required_for_current_mode=False,
                detail="当前使用离线规则与本地工具；星辰未启用，不影响结构化核心演示。",
                action="星辰线上联调后可增强语言组织，但不能替代证据门禁。",
            )
        configured = all(
            (
                self._settings.astron_agent_api_key,
                self._settings.astron_agent_api_secret,
                self._settings.astron_agent_flow_id,
            )
        )
        return DemoReadinessCheck(
            check_id="assistant_backend",
            label="科研助理语言层",
            status="warning" if configured else "not_configured",
            required_for_current_mode=False,
            detail=(
                "星辰配置已加载，但就绪检查不会发起付费或外网调用，线上状态仍待真实联调。"
                if configured
                else "已选择星辰后端，但服务端配置不完整。"
            ),
            action="完成脱敏真实联调并记录工作流版本、延迟和失败案例。",
        )

    def _assistant_storage_check(
        self, infrastructure_mode: bool
    ) -> DemoReadinessCheck:
        persistent = (
            getattr(self._settings, "assistant_session_backend", "memory") == "mysql"
        )
        if persistent:
            return DemoReadinessCheck(
                check_id="assistant_session_storage",
                label="助理会话历史",
                status="ready",
                required_for_current_mode=infrastructure_mode,
                detail="会话、消息、工具运行和EvidenceAnchor引用写入MySQL，可跨API重启恢复。",
            )
        return DemoReadinessCheck(
            check_id="assistant_session_storage",
            label="助理会话历史",
            status="ready" if not infrastructure_mode else "warning",
            required_for_current_mode=infrastructure_mode,
            detail=(
                "离线演示使用进程内临时会话；API重启后历史会丢失。"
                if not infrastructure_mode
                else "本地基础设施已启用，但助理会话仍是进程内临时存储。"
            ),
            action=(
                "将ASSISTANT_SESSION_BACKEND设为mysql并重启API。"
                if infrastructure_mode
                else None
            ),
        )


def _tour_steps(paper_id: str) -> list[DemoTourStep]:
    base = f"/papers/{paper_id}"
    return [
        DemoTourStep(
            step_id="core_chain",
            label="先看完整论证链",
            route=base,
            instruction="选择一个Claim，确认问题、缺口、方法、证据和边界如何闭合。",
            success_signal="页面显示9个阶段，且每一阶段只引用已有结构化实体。",
        ),
        DemoTourStep(
            step_id="experiment_intent",
            label="再看实验为什么存在",
            route=f"{base}?tab=experiments",
            instruction="检查研究问题、设计理由、变量以及它实际支撑的Claim。",
            success_signal="实验卡同时说明能验证什么，且不生成实验数值。",
        ),
        DemoTourStep(
            step_id="artifact_role",
            label="阅读真实图表和解释",
            route=f"{base}?tab=artifacts",
            instruction="查看Figure/Table摘图、形式选择、对应Claim和禁止结论。",
            success_signal="真实模式显示PDF摘图；离线模式明确说明没有授权页图。",
        ),
        DemoTourStep(
            step_id="evidence_anchor",
            label="检查EvidenceAnchor用途",
            route=f"{base}?tab=evidence",
            instruction="选择证据，查看它参与哪些Claim、实验、图表和叙事动作。",
            success_signal="真实模式可跳到原页；未核验内容仍标记为开发转述。",
        ),
        DemoTourStep(
            step_id="argument_path",
            label="最后检查论证路径",
            route=f"{base}?tab=graph",
            instruction="按Claim查看实验/图表如何落到EvidenceAnchor，而不是浏览关系大球。",
            success_signal="页面显示关系来源和MySQL权威边界；有关系不等于人工确认。",
        ),
    ]
