# 科大 Agent（重建交接版）

面向科研新手的论文逆向工程助手。核心链路：

`Problem → Gap → Claim → Experiment → Figure/Table → Evidence → Boundary`

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

访问 <http://localhost:5173>，API 文档位于 <http://localhost:8000/docs>。

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
