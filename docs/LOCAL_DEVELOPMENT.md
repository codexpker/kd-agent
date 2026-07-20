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

1. 从空库升级到 `0001_reconstructed` → `0002_reconstructed_authority` → `0003_reconstructed_pdf_layout` 新迁移链；它们不是旧项目 `0001–0006` 的伪造副本。
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

Gold清单中的`PaperSource`元数据与Gold实体在同一MySQL事务内写入。每个来源使用稳定
`source_key`独立保存；同键更新按以下规则处理：官方出版源、人工维护注册表、OpenReview、
Crossref、arXiv、OpenAlex、模型抽取依次降级；更高质量来源可以替换，质量相同时只有
`retrieved_at`严格更新的候选可以替换，低质量或过期候选在CLI中显示为`protected`。
不同来源不会互相删除，`is_primary`按质量、时间和稳定键确定。`access_policy=metadata_only`
仅表示可保存元数据，不能作为PDF全文持久化授权。

### Step 3 PDF版面事实闭环

安装可选解析依赖并升级数据库：

```bash
python -m pip install -e './backend[pdf]'
cd backend
python -m alembic upgrade head
```

默认dry-run只解析本地文件并输出预览，不加载MySQL仓储、不写任何表：

```bash
python -m app.cli.ingest_pdf anomaly-transformer-2022 /path/to/paper.pdf
```

持久化必须显式提交并提供权利依据和确认人：

```bash
python -m app.cli.ingest_pdf anomaly-transformer-2022 /path/to/paper.pdf \
  --commit \
  --rights-basis user_private_copy \
  --confirmed-by local-user
```

`--rights-basis`只接受`open_full_text`、`user_private_copy`或
`institution_authorized`。缺少依据时，dry-run预览仍可使用，但`--commit`返回`blocked`且数据库
调用为零。可选的`--paper-source-key`必须引用同一论文已有的PaperSource。

`0003_reconstructed_pdf_layout`建立以下规范化事实链：

```text
pdf_sources
  → pdf_parse_runs
    → pdf_sections
    → pdf_artifacts
      → pdf_body_references
```

- `pdf_sources`只保存论文ID、可选PaperSource关联、文件SHA-256、文件大小和权利确认；没有PDF
  二进制、文件路径或整篇正文列。
- `pdf_parse_runs`保存解析器名称、版本、结构内容哈希、页数、状态与warnings。
- 章节保存层级、页码范围和标题bbox；Figure/Table保存页码、对象bbox、图注bbox、图注、
  Markdown和二维表格单元格；正文引用保存所指Artifact、页码和bbox。
- 相同文件、解析器版本和结构内容重复提交返回`unchanged`，不会复制子实体。
- `DocumentStructure`只承载客观版面事实，`evidence`固定为空；科研主张、实验意图和证据判断
  继续只存在于`PaperDeconstruction`。

查询接口：

```http
GET /api/v1/papers/anomaly-transformer-2022/document-structure
```

当`DOCUMENT_STRUCTURE_BACKEND=mysql`时，接口优先返回最新成功的`source=parsed_pdf`；没有解析
运行时回退到`source=gold_snapshot`。Gold回退中的parser、文件哈希、页数、页码、bbox、图注、
表格内容和正文引用均为空，不会把语义标注伪装成PDF版面事实。默认
`DOCUMENT_STRUCTURE_BACKEND=gold`继续完全离线，导入应用不会加载SQLAlchemy仓储或PyMuPDF。

当前PyMuPDF适配器仍是可复现基线：编号标题、图注和正文引用使用规则提取，表格单元格使用
PyMuPDF表格探测。复杂双栏、扫描页、跨页表格和矢量Figure可能无法得到对象bbox或结构化
单元格，此时对应字段保持为空并写入warnings，不得据此声称解析完整。

### Step 4a 三解析器统一映射与评测框架

`PyMuPdfAdapter`、`GrobidTeiAdapter`和`MinerUJsonAdapter`统一返回`ParsedDocument`。GROBID映射
TEI的嵌套章节、`coords`、Figure/Table、`figDesc`、表格行列和正文`ref`；MinerU映射
`pages/blocks`、`pdf_info/para_blocks`或官方`content_list.json`中的标题、图片/Chart、表格、
显式正文引用、bbox和结构化单元格。GROBID的多行`coords`按同页外接框归一化，MinerU的
`table_body` HTML按可见`th/td`提取二维单元格；当前不展开`rowspan/colspan`。
适配器模块不依赖SQLAlchemy或仓储；需要持久化时仍只能把解析结果交给`PdfLayoutService`，并
经过Step 3的权利硬门禁。

仓库没有静默启动或模拟GROBID/MinerU服务。应用代码注入对应客户端后才能解析真实PDF；未配置
客户端时，`ingest_pdf --parser grobid`或`--parser mineru`返回`overall_status=unavailable`和退出码4，
不会回退到合成结果。当前映射覆盖仓库Gold Schema声明的字段；接入具体上游版本时仍需用其真实
输出建立兼容性fixture。

字段口径以[GROBID PDF coordinates](https://grobid.readthedocs.io/en/latest/Coordinates-in-PDF/)
和[MinerU Output File Format](https://opendatalab.github.io/MinerU/reference/output_files/)为上游基准。
MinerU官方输出在版本/后端间存在不兼容变化，因此报告必须保存真实解析器版本；官方输出没有
稳定目标ID的正文图表引用不会被规则猜测，而是保持为空并写入warning。

人工标注模板位于`backend/app/data/evaluation/layout_gold_template.json`。标注前必须替换论文ID、
文件SHA-256、页数和权利依据；两名标注员先独立工作，仲裁后增加`adjudicator`并把状态改为
`adjudicated`。真实报告会拒绝`draft`或仅双人未仲裁的Gold。可打印机器可读JSON Schema：

```bash
cd backend
python -m app.cli.evaluate_pdf_layout --print-gold-schema
```

CI使用内置合成TEI、MinerU JSON和统一契约样例验证映射与评测程序：

```bash
python -m app.cli.evaluate_pdf_layout \
  --synthetic-smoke-test \
  --json-report tmp/pdf-layout-report.json \
  --markdown-report tmp/pdf-layout-report.md
```

两份报告都强制标记`synthetic_smoke_test`，Markdown标题同时显示`SYNTHETIC SMOKE TEST`；满分只
表示fixture和评测程序闭合，不是PyMuPDF、GROBID或MinerU的真实论文成绩。真实Gold完成仲裁后可用：

```bash
python -m app.cli.evaluate_pdf_layout \
  --gold /path/to/adjudicated-layout-gold.json \
  --prediction /path/to/pymupdf-parsed.json \
  --prediction /path/to/grobid-parsed.json \
  --prediction /path/to/mineru-parsed.json \
  --json-report /path/to/report.json \
  --markdown-report /path/to/report.md
```

指标包括章节标题F1、匹配章节的层级准确率、Figure与Table检测F1、匹配图表的图注字符序列
相似度、匹配章节范围/图表/正文引用的页码准确率、按目标图表和页码匹配的正文引用F1，以及按
表格、行、列和规范化文本计算的单元格F1。章节和图表检测分别用规范化标题与标签匹配；报告中
保留该口径，后续若采用模糊匹配必须提升Schema版本并重新跑基线。

使用 MySQL 文档结构读模型时，将 `.env` 中的配置切换为：

```dotenv
DOCUMENT_STRUCTURE_BACKEND=mysql
```

未执行迁移、数据库不可达时，该 API 明确返回 503；没有解析结果但有本地Gold时返回Gold回退，
两者都没有时返回404。迁移链已在SQLite和Docker Desktop + WSL2的MySQL 8.4完成升降级验证。

若宿主机 `3306` 已被其他 MySQL 占用，可为 Compose 和应用指定一致的备用端口：

```bash
MYSQL_PORT=3307 MYSQL_URL=mysql+pymysql://kd_agent:kd_agent_local@127.0.0.1:3307/kd_agent docker compose up -d --wait mysql neo4j
```

## 安全

- 后端持有外部服务密钥，前端不保存密钥。
- `.env` 已被 Git 忽略。
- 曾经粘贴到聊天中的令牌必须撤销，不能重复使用。
