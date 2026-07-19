# 本地开发

## 离线演示

在仓库根目录复制 `.env.example` 为 `.env`，然后：

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e './backend[dev]'
cd backend
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

Windows 激活命令为 `.\.venv\Scripts\Activate.ps1`。

前端：

```bash
cd frontend
npm install
npm run dev
```

## 完整基础设施

```bash
python -m pip install -e './backend[dev,infra]'
docker compose up -d --wait mysql etcd minio milvus neo4j
docker compose ps
```

默认 `DOCUMENT_STRUCTURE_BACKEND=gold`，不会依赖数据库。

### R2 迁移与幂等入库验收

在仓库根目录启动 MySQL 与 Neo4j 后执行：

```bash
cd backend
python -m alembic upgrade head
python -m app.cli.r2_acceptance
```

`r2_acceptance` 会完成以下检查：

1. 从空库升级到 `0001_reconstructed` → `0002_reconstructed_authority` 新迁移链；它们不是旧项目 `0001–0006` 的伪造副本。
2. 验证规范化Gold记录先提交到MySQL、再同步Neo4j；图同步失败时MySQL保留，状态记为`failed/partial`。
3. 强制连续同步两次，第二次规范化写入必须为`unchanged`，Neo4j的Paper和受管子节点数量必须保持稳定。

默认命令只生成入库计划，不写数据库：

```bash
python -m app.cli.ingest_gold
```

显式写入MySQL：

```bash
python -m app.cli.ingest_gold --commit
```

MySQL提交成功后再同步Neo4j：

```bash
python -m app.cli.ingest_gold --commit --sync-neo4j
```

`--sync-neo4j`或`--force-graph-sync`未同时提供`--commit`时命令直接拒绝执行。

使用 MySQL 文档结构读模型时，将 `.env` 中的配置切换为：

```dotenv
DOCUMENT_STRUCTURE_BACKEND=mysql
```

未执行迁移、数据库不可达时，该 API 明确返回 503；没有对应记录时返回 404。真实容器验收已在 Docker Desktop + WSL2、MySQL 8.4 与 Neo4j 5.26 上通过。

若宿主机 `3306` 已被其他 MySQL 占用，可为 Compose 和应用指定一致的备用端口：

```bash
MYSQL_PORT=3307 MYSQL_URL=mysql+pymysql://kd_agent:kd_agent_local@127.0.0.1:3307/kd_agent docker compose up -d --wait mysql neo4j
```

## 安全

- 后端持有外部服务密钥，前端不保存密钥。
- `.env` 已被 Git 忽略。
- 曾经粘贴到聊天中的令牌必须撤销，不能重复使用。
