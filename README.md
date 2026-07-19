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

详细说明见 `docs/LOCAL_DEVELOPMENT.md` 与 `docs/ROADMAP.md`。

