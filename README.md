# 科大 Agent（重建交接版）

面向科研新手的论文逆向工程助手。核心链路：

`Problem → Gap → Hypothesis → Method → Claim → Experiment → Figure/Table → Evidence → Boundary`

本版本依据项目对话与方案记录重建，默认采用离线 Gold 数据，可直接运行；MySQL、Milvus、Neo4j、PDF 解析和讯飞星辰均作为可替换基础设施保留接口。

## 快速启动

要求：Python 3.11+、Node.js 20+。

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate          # Windows: .\.venv\Scripts\Activate.ps1
python -m pip install -e './backend[dev]'
cd backend
python -m uvicorn app.main:app --reload --port 8000
```

另开终端：

```bash
cd frontend
npm install
npm run dev
```

访问 <http://localhost:5173>，默认进入“科研助理”对话式工作台；原有完整结构化编辑器移动到
<http://localhost:5173/workspace>。API 文档位于 <http://localhost:8000/docs>。

首篇论文逆向工程阅读器位于
<http://localhost:5173/papers/anomaly-transformer-2022>。它把文档结构、科研叙事链、Claim、实验意图、
Figure/Table角色和EvidenceAnchor放在同一审核界面。当前默认数据是`development_seed + gold_snapshot`：
没有已登记的授权解析结果时，页面不会分发原PDF，也不会显示伪造页码、图注、bbox或正文引用。

科研助理首页使用自然语言和四类任务卡导航现有确定性科研工具，右侧固定展示EvidenceAnchor和
局部关系图。默认`EVIDENCE_GRAPH_BACKEND=gold`保持完全离线，并明确显示`gold_snapshot`，不会把
开发种子冒充Neo4j查询结果。安装基础设施依赖、启动Neo4j并将该配置改为`neo4j`后，右侧关系图
改为读取真实Neo4j可重建索引；MySQL仍是权威事实源。

## 验证

首次安装Playwright浏览器：

```bash
cd frontend && npx playwright install chromium
```

统一验证默认离线黄金流程：

```bash
make demo-accept-offline
```

Docker中的MySQL和Neo4j已启动时，可追加R2真实双库接受测试：

```bash
make demo-accept
```

Windows没有`make`时，在`backend`目录运行：

```powershell
..\.venv\Scripts\python.exe -m app.cli.demo_acceptance
..\.venv\Scripts\python.exe -m app.cli.demo_acceptance --with-infrastructure
```

也可以分别运行：

```bash
cd backend && python -m pytest
cd frontend && npm run build
cd frontend && npm run test:e2e
```

R2 的 MySQL/Neo4j 验收需要 Docker 与基础设施依赖：

```bash
python -m pip install -e './backend[dev,infra]'
docker compose up -d --wait mysql neo4j
cd backend
python -m app.cli.r2_acceptance
```

验收命令会应用新的重建迁移链，连续执行两次Gold→MySQL规范化实体与Neo4j同步，并检查第二次MySQL写入和PaperSource元数据均为`unchanged`、图中节点数不增长。PaperSource按稳定来源键并存，低质量或过期的同键候选不会覆盖已存权威元数据。它只导入已完成的开发记录，`queued`论文仍不会入库。日常运行`python -m app.cli.ingest_gold`默认为零写入dry-run；只有增加`--commit`才写MySQL。

只读证据关系接口：

```http
GET /api/v1/papers/anomaly-transformer-2022/evidence-graph
```

返回`source=gold_snapshot`或`source=neo4j`、闭合节点和关系、以及对应来源边界；Neo4j显式模式
连接失败时返回503，不会静默回退或伪造图数据库结果。

PDF版面事实链路需要可选解析依赖，并且默认只做本地预览：

```bash
python -m pip install -e './backend[pdf]'
cd backend
python -m app.cli.ingest_pdf anomaly-transformer-2022 /path/to/paper.pdf
```

只有显式`--commit`并同时提供`--rights-basis`与`--confirmed-by`才会把结构化结果写入MySQL。
允许的依据仅为`open_full_text`、`user_private_copy`或`institution_authorized`。数据库保存
SHA-256、权利确认、解析器版本、章节、Figure/Table、bbox、图注、结构化表格和正文引用位置，
不保存PDF二进制或本地路径。将`DOCUMENT_STRUCTURE_BACKEND=mysql`后，
`GET /api/v1/papers/{paper_id}/document-structure`优先返回`parsed_pdf`，否则返回不带伪造版面字段的
`gold_snapshot`。

详细说明见 `docs/LOCAL_DEVELOPMENT.md` 与 `docs/ROADMAP.md`。
