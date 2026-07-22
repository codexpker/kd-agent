# 科大 Agent

面向科研新手的论文逆向工程助手。核心链路：

`Problem → Gap → Hypothesis → Method → Claim → Experiment → Figure/Table → Evidence → Boundary`

本项目参加赛题 `XH-202620 面向一流学科建设的学科垂类大模型与创新应用开发`。正式赛事
基线见 `docs/CONTEST_BASELINE.md`，产品北极星见 `docs/PROJECT_BLUEPRINT.md`。默认采用离线开发数据，可直接运行；MySQL、Milvus、Neo4j、
PDF解析和外部模型均通过可替换接口接入。

当前仓库不是比赛最终版：5篇登记论文中只有1篇`development_seed`，没有双审/冻结Gold；默认
检索是Demo/hash后端，默认助理是离线规则；星辰已有客户端、工具契约和Mock测试，但没有平台线上联调证据。
规则允许其他工具，但项目已冻结正式比赛主链路为
`Vue → FastAPI → 星辰Agent → 星火/科技文献模型、MaaS → 自研工具`。只有真实联调后才能写入比赛宣传材料。

仓库已提供星辰可注册的`search_papers`、`deconstruct_paper`、`compare_papers`和`diagnose_claim`
四个结构化工具接口；OpenAPI、系统提示词和工作流节点位于`docs/astron/`。这表示接入准备已完成，
不表示工具已经在星辰平台发布或产生真实调用。

## 快速启动

要求：Python 3.11+、Node.js 20+。

安装依赖后，可以用一个命令启动并打开五步演示引导。默认命令保持完全离线、零数据库写入：

```bash
python -m app.cli.demo_start
```

已配置Docker、MySQL、Neo4j和本地授权PDF时，显式启用真实基础设施模式：

```bash
python -m app.cli.demo_start --with-infrastructure
```

Windows 未激活虚拟环境时，可在仓库根目录运行：

```powershell
.\.venv\Scripts\python.exe -m app.cli.demo_start --with-infrastructure
```

如果 PowerShell 当前已经位于 `backend` 目录，则虚拟环境在上一级，应运行：

```powershell
..\.venv\Scripts\python.exe -m app.cli.demo_start --with-infrastructure
```

真实模式会启动MySQL/Neo4j、应用Alembic迁移，并以显式`--commit`幂等同步演示开发种子；不会
写入或复制PDF。服务启动后打开`/assistant?guide=1`，面板会分别检查语义种子、`parsed_pdf`、
SHA-256匹配的私有页图、Neo4j关系索引、科研助理语言层和会话存储。该模式启动的新API会显式使用
`ASSISTANT_SESSION_BACKEND=mysql`，会话可跨API重启恢复。已有服务会被复用；若旧API仍是内存会话，
就绪检查会给出警告，需要先停止旧API再重启真实模式。命令只会终止由它自己启动的进程。只读检查
当前运行环境可使用：

```bash
python -m app.cli.demo_start --check-only
```

下面仍保留手工分终端启动方式，便于日常开发调试：

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

前端顶部的“演示引导”会显示当前究竟是“离线演示数据”还是“本地证据基础设施”，并按“核心链 →
实验意图 → Figure/Table → EvidenceAnchor → 论证路径”导航。`GET /api/v1/demo/readiness`返回同一份
机器可读状态；`/healthz`只表示API进程存活，不能替代核心链路就绪检查。

首篇论文逆向工程阅读器位于
<http://localhost:5173/papers/anomaly-transformer-2022>。它把文档结构、科研叙事链、Claim、实验意图、
Figure/Table角色和EvidenceAnchor放在同一审核界面。当前默认数据是`development_seed + gold_snapshot`：
没有已登记的授权解析结果时，页面不会分发原PDF，也不会显示伪造页码、图注、bbox或正文引用。
`development_seed`在前端显示为“开发种子 · 未经双审”，表示语义解释可以用于学习和演示，但不能
直接当作论文原句、正式引用或冻结Gold；它不是要求普通用户进入数据库逐条确认。真实解析模式下，
图表页签会从SHA-256匹配的本地私有PDF即时渲染阅读摘图，并按结构化规则说明它回答什么、为何使用
Figure/Table、参与支撑哪个Claim以及不能推出什么。摘图窗口不写数据库、不作为解析bbox真值。

科研助理首页使用自然语言和四类任务卡导航现有科研工具。论文问答会创建带`trace_id`的会话，并
记录实际调用的本地工具、来源和EvidenceAnchor。默认`ASSISTANT_SESSION_BACKEND=memory`保持零数据库
依赖，页面明确提示API重启后清空；显式改为`mysql`并应用`0007_assistant_sessions`后，会话、消息、
工具运行和证据引用使用规范化MySQL权威表保存，URL中的不透明`session`参数可在刷新或重启后恢复
同一会话。默认`ASSISTANT_BACKEND=offline`仍明确显示“离线规则 · 本地证据工具”。可配置星辰工作流（正式比赛环境必配）
只负责依据本地工具结果组织语言，返回内容必须引用已存在的EvidenceAnchor，否则作为错误拒绝，
不会静默回退成伪造的模型成功。

默认`EVIDENCE_GRAPH_BACKEND=gold`保持完全离线，并明确显示`gold_snapshot`，不会把开发种子冒充
Neo4j查询结果。安装基础设施依赖、启动Neo4j并将该配置改为`neo4j`后，右侧关系图改为读取真实
Neo4j可重建索引；MySQL仍是权威事实源。前端将索引解释为`Claim → Experiment/Figure/Table →
EvidenceAnchor`论证路径，而不是没有阅读目的的实体大图。

## 验证

首次安装Playwright浏览器：

```bash
cd frontend && npx playwright install chromium
```

统一验证默认离线黄金流程：

```bash
make demo-accept-offline
```

Docker中的MySQL和Neo4j已启动时，可追加R2真实双库和授权私有PDF浏览器验收：

```bash
make demo-accept
```

Windows没有`make`时，在`backend`目录运行：

```powershell
..\.venv\Scripts\python.exe -m app.cli.demo_acceptance
..\.venv\Scripts\python.exe -m app.cli.demo_acceptance --with-infrastructure
```

`--with-infrastructure`要求`.env`已配置真实MySQL/Neo4j、`DOCUMENT_STRUCTURE_BACKEND=mysql`、
`EVIDENCE_GRAPH_BACKEND=neo4j`、`ASSISTANT_SESSION_BACKEND=mysql`和仅指向本机授权副本目录的
`PRIVATE_PDF_PREVIEW_ROOT`。它会在双库
幂等验收后运行`npm run test:e2e:real-infra`，验证`parsed_pdf`、即时私有PNG、EvidenceAnchor定位和
Neo4j Claim路径，并验证助理会话刷新后恢复；不会上传或提交PDF，星辰仍固定为离线。默认
`npm run test:e2e`继续只运行无外部
基础设施的合成黄金流程。

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

已确认权利并完成持久化后，本地演示可额外配置
`PRIVATE_PDF_PREVIEW_ENABLED=true`和`PRIVATE_PDF_PREVIEW_ROOT`。页面/图表预览接口只按数据库
SHA-256匹配本地文件并返回`private, no-store` PNG；它不分发原PDF、不暴露路径，非`local`模式
会硬阻断。详见`docs/LOCAL_DEVELOPMENT.md`。

详细说明见 `docs/LOCAL_DEVELOPMENT.md` 与 `docs/ROADMAP.md`。
