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
docker compose up -d mysql etcd minio milvus neo4j
docker compose ps
```

数据库模式仍需按 R2 路线完成真实容器验收。默认 `DOCUMENT_STRUCTURE_BACKEND=gold`，不会依赖数据库。

## 安全

- 后端持有外部服务密钥，前端不保存密钥。
- `.env` 已被 Git 忽略。
- 曾经粘贴到聊天中的令牌必须撤销，不能重复使用。

