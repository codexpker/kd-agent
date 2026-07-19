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

```bash
cd backend && python -m pytest
cd frontend && npm run build
```

R2 的 MySQL/Neo4j 验收需要 Docker 与基础设施依赖：

```bash
python -m pip install -e './backend[dev,infra]'
docker compose up -d --wait mysql neo4j
cd backend
python -m app.cli.r2_acceptance
```

验收命令会应用新的重建迁移链，连续执行两次Gold→MySQL规范化实体与Neo4j同步，并检查第二次MySQL写入和PaperSource元数据均为`unchanged`、图中节点数不增长。PaperSource按稳定来源键并存，低质量或过期的同键候选不会覆盖已存权威元数据。它只导入已完成的开发记录，`queued`论文仍不会入库。日常运行`python -m app.cli.ingest_gold`默认为零写入dry-run；只有增加`--commit`才写MySQL。

详细说明见 `docs/LOCAL_DEVELOPMENT.md` 与 `docs/ROADMAP.md`。
