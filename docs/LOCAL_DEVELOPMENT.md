# 本地开发

## Demo Acceptance Gate

安装后端开发依赖、前端依赖和Playwright Chromium：

```bash
python -m pip install -e './backend[dev,infra]'
cd frontend
npm install
npx playwright install chromium
```

只验收默认离线演示链：

```bash
make demo-accept-offline
```

MySQL和Neo4j已经启动时，运行完整演示门禁：

```bash
docker compose up -d --wait mysql neo4j
make demo-accept
```

`demo-accept-offline`依次运行全部后端测试、Vue生产构建和一个Playwright黄金流程。浏览器流程会
自动在独立端口启动内存后端与Vite，验证`gold_snapshot`不伪造页码、真实语料返回
`insufficient_evidence`，以及合成表单到Claim、诊断、实验计划、运行清单、CSV Schema、绘图代码、
受控执行、逐点溯源和下载产物的完整闭环。所用`synthetic_plot_smoke.csv`只用于验证程序，不能
作为论文实验或比赛成绩。`demo-accept`随后执行真实MySQL/Neo4j R2幂等接受测试。

若只需要重跑浏览器黄金流程：

```bash
cd frontend
npm run test:e2e
```

Windows没有`make`时，可以直接使用同一个跨平台接受测试入口：

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli.demo_acceptance
..\.venv\Scripts\python.exe -m app.cli.demo_acceptance --with-infrastructure
```

测试会优先使用仓库根目录`.venv`中的Python；也可以通过`KD_AGENT_PYTHON`显式指定解释器。
Playwright失败截图和trace只写入被Git忽略的`tmp/playwright-results`。

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

页面入口：

- `http://127.0.0.1:5173/assistant`：默认科研助理入口，包含任务导航、执行步骤、EvidenceAnchor和局部关系图。
- `http://127.0.0.1:5173/papers/anomaly-transformer-2022`：独立论文逆向工程阅读器，包含结构索引、叙事链、实验意图、Figure/Table角色、证据透镜与局部关系图。
- `http://127.0.0.1:5173/workspace`：论文拆解、研究机会、Project Claim、实验计划与绘图的完整专业编辑器。
- `http://127.0.0.1:5173/knowledge-graph`：导航到科研助理的关系图面板。

当前科研助理默认使用明确标记的离线规则导航：它按自然语言关键词选择现有确定性工具并在不能可靠
识别意图时要求澄清，没有连接模型时不会伪装成大模型推理。论文拆解问答由服务端会话API执行，
每轮记录`session_id`、`trace_id`、提示词版本、消息来源、实际工具运行和EvidenceAnchor。默认
`ASSISTANT_SESSION_BACKEND=memory`只保存在API进程内存，重启后清空；显式使用`mysql`时可跨重启
恢复，结构化工作区继续保存版本、证据和可复现产物。

### 论文拆解会话与星辰工作流

默认配置完全离线：

```dotenv
ASSISTANT_BACKEND=offline
ASSISTANT_SESSION_BACKEND=memory
```

创建会话并发送第一轮问题：

```http
POST /api/v1/assistant/sessions
{"paper_id":"anomaly-transformer-2022"}

POST /api/v1/assistant/sessions/{session_id}/messages
{"content":"为什么要做消融实验？","expected_message_count":0}
```

第二轮的`expected_message_count`应使用上一响应中`session.messages`的长度；过期计数返回409，避免并发
覆盖历史。`GET /api/v1/assistant/sessions/{session_id}`读取当前会话历史。前端把不透明会话ID写入
`/assistant?session=...`，刷新时重新读取服务端历史；它不把消息正文放进URL。每轮至少执行
`paper_deconstruct`；涉及页码/章节时增加`document_structure`，涉及关系图时增加`evidence_graph`。
工具选择是可测试的服务端规则，不应宣称为模型自主工具规划。

要启用跨API重启恢复，先应用迁移并在启动API前设置：

```dotenv
ASSISTANT_SESSION_BACKEND=mysql
MYSQL_URL=mysql+pymysql://<user>:<password>@127.0.0.1:<port>/<database>
```

`0007_assistant_sessions`新增会话、消息、工具运行及其EvidenceAnchor/消息—工具链接表。写入使用
`expected_message_count`做原子乐观并发检查；过期页面不会覆盖新历史。MySQL不可用时接口返回503，
不会静默转存到内存。默认内存模式不导入SQLAlchemy/PyMySQL，离线演示兼容性保持不变。

接入已发布并绑定应用的星辰工作流时，只在后端`.env`填写：

```dotenv
ASSISTANT_BACKEND=astron
ASTRON_AGENT_API_KEY=<server-only>
ASTRON_AGENT_API_SECRET=<server-only>
ASTRON_AGENT_FLOW_ID=<published-flow-id>
ASTRON_AGENT_MODEL_LABEL=<model-version-configured-in-workflow>
```

实现遵循讯飞官方工作流接口`https://xingchen-api.xf-yun.com/workflow/v1/chat/completions`，使用
`Bearer API_KEY:API_SECRET`，发送最多最近12条历史消息和`chat_id`。工作流开始节点需要接收
`AGENT_USER_INPUT`；后端会把当前问题、结构化工具结果和科研诚信约束放入该参数。官方接入文档：
<https://www.xfyun.cn/doc/spark/Agent04-API%E6%8E%A5%E5%85%A5.html>。

模型只能组织本地证据语言：每个事实性回答必须以`[ev-*]`引用当前论文已存在的EvidenceAnchor。
未知引用、无引用、空响应、HTTP/鉴权错误或工作流中断都会得到`status=error`和
`origin=system_error`；本轮工具日志仍保留，但不会用离线模板冒充模型回答。API Key和Secret不进入
响应、浏览器或Git。自动测试使用`httpx.MockTransport`验证真实协议形状，没有消耗外部额度，也不
代表星辰线上调用已经通过；首次真实联调必须另行保存调用时间、工作流版本和脱敏结果证据。

论文阅读器同时请求`paper-deconstruct`、`document-structure`和`evidence-graph`三条接口。语义拆解与
客观版面在界面中分栏展示：`gold_snapshot`只提供结构名称与角色卡，PDF定位按钮保持禁用；只有
`DOCUMENT_STRUCTURE_BACKEND=mysql`返回带权利记录的`parsed_pdf`时，才显示解析器、文件哈希和可核验
页码。当前页面没有PDF文件传输端点，因此不会通过前端绕过全文权利门禁。

## 完整基础设施

```bash
python -m pip install -e './backend[dev,infra]'
docker compose up -d --wait mysql etcd minio milvus neo4j
docker compose ps
```

默认 `DOCUMENT_STRUCTURE_BACKEND=gold`，不会依赖数据库。

### 证据关系图查询

默认`EVIDENCE_GRAPH_BACKEND=gold`从当前可公开的Gold development seed构造闭合关系图，保持离线
模式可用；其`source=gold_snapshot`和warnings会直接显示在前端。查询接口：

```http
GET /api/v1/papers/anomaly-transformer-2022/evidence-graph
```

要查看真实Neo4j可重建索引，先完成Gold入库和图同步，再在启动API前设置：

```powershell
$env:EVIDENCE_GRAPH_BACKEND='neo4j'
..\.venv\Scripts\python.exe -m uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port 8000 --reload
```

Neo4j模式使用延迟导入，不影响默认离线启动；连接失败、缺少驱动或找不到论文分别明确返回503或
404，不会回退成伪造的Neo4j结果。前端图谱只展示一到两跳的Paper、Claim、Experiment、Artifact
和Evidence关系，证据列表仍是主要审核界面；MySQL始终是权威事实源。

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

#### 本地私有PDF受控预览

对于已经通过上述权利门禁写入MySQL的`parsed_pdf`，可以在**仅本机演示**环境显式启用页面
渲染：

```dotenv
RESEARCH_GATEWAY_MODE=local
DOCUMENT_STRUCTURE_BACKEND=mysql
PRIVATE_PDF_PREVIEW_ENABLED=true
PRIVATE_PDF_PREVIEW_ROOT=/absolute/path/to/rights-confirmed-pdfs
```

接口只接收论文ID、页码或已解析Artifact ID，不接收文件路径：

```http
GET /api/v1/papers/{paper_id}/document-preview/pages/{page_number}
GET /api/v1/papers/{paper_id}/document-preview/artifacts/{artifact_id}
```

服务递归检查配置目录中的PDF，只有文件SHA-256与MySQL最新`DocumentStructure.file_sha256`
完全一致时才即时渲染PNG。Artifact预览会对已有对象bbox/图注bbox画框；缺少对象bbox时仍显示
整页并只标出可用图注框。响应固定为`Cache-Control: private, no-store`，不会返回原PDF、本地路径
或文件名。该能力默认关闭，并且在`RESEARCH_GATEWAY_MODE`不是`local`时硬阻断；不要在共享部署
中指向私有论文目录。自动解析页图与位置仍需人工复核，不能作为已仲裁Gold。

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

### Step 4b 第一篇真实版面Gold工作流与质控

2026-07-20初次本地审计没有发现Anomaly Transformer PDF；随后用户指定了一个被Git忽略的本地
候选PDF，但尚未确认其权利依据和来源记录。MySQL仍没有该论文的`PdfSource`或解析运行，唯一
PaperSource为`metadata_only`且`full_text_rights_confirmed=false`。仓库也没有
第二标注员或仲裁员身份记录。因此当前案例同时保持`rights_status=needs_authorized_pdf`、
`annotation_status=needs_second_annotator`和`workflow_status=blocked`，没有真实版面Gold或真实
解析器成绩。阻塞清单与数据清单分别位于：

- `backend/app/data/evaluation/anomaly_transformer_layout_gold_manifest.json`
- `backend/app/data/evaluation/layout_gold_inventory.json`

不得为解除阻塞从来源不明的网站下载PDF。团队成员提供私有合法副本时，`source_uri`留空并填写
来源说明；开放全文只记录官方HTTP(S)来源。工具不接受本地路径作为来源URI，也不会把PDF路径写入
案例文件。初始化默认dry-run；只有`--commit`才写结构化工作文件，原PDF始终不复制：

```bash
cd backend
python -m app.cli.layout_gold_workflow prepare \
  anomaly-transformer-2022 /private/path/anomaly-transformer.pdf \
  --title "Anomaly Transformer: Time Series Anomaly Detection with Association Discrepancy" \
  --source-description "User-provided private copy" \
  --rights-basis user_private_copy \
  --confirmed-by team-member-id \
  --annotator-a reviewer-a \
  --output-dir /private/work/anomaly-transformer-layout
```

该命令计算精确文件SHA-256和页数，记录PyMuPDF版本并生成PyMuPDF候选，但A/B标注文件为空，
不会用解析器结果预填人工答案。缺少B时返回退出码2，案例停在`needs_second_annotator`。确认真实且
不同的B后再显式注册；工具只创建B自己的空白文件，不覆盖A：

```bash
python -m app.cli.layout_gold_workflow register-second-annotator \
  --manifest /private/work/anomaly-transformer-layout/case_manifest.json \
  --annotator-b reviewer-b \
  --commit
```

GROBID必须开启`head`、`figure`、`ref`坐标并记录服务版本；MinerU必须固定版本并保留输出类型。
外部原始输出不复制进案例目录，只导入统一契约：

```bash
python -m app.cli.layout_gold_workflow import-candidate \
  --manifest /private/work/anomaly-transformer-layout/case_manifest.json \
  --parser grobid \
  --parser-version 0.x.y \
  --input /private/output/anomaly-transformer.tei.xml \
  --commit
```

#### 独立标注质控

1. A和B文件各自只能有一个`role=annotator`身份，状态保持`draft`；两人不得互看、复制或共同编辑。
2. 两份文件必须引用同一`paper_id`、PDF SHA-256、页数和权利依据；不一致时导入直接失败。
3. 稳定ID按可见事实维护：章节使用`sec-*`，图表使用可核验标签，正文引用必须指向文件内图表ID。
4. 标注章节标题/层级/页码范围/标题bbox、Figure/Table标签/页码/bbox/图注/图注bbox、正文引用
   文本/目标/页码/bbox，以及可核验的表格二维单元格；看不清时留空或记录问题，不猜测。
5. 导入工具按稳定ID生成`missing_in_a`、`missing_in_b`和逐字段`field_mismatch`，保存两份标注内容
   哈希；它不修改A/B，不选择胜者，也不自动生成最终Gold。
6. 即使差异数为0，仍需独立仲裁员签字；仲裁模板默认所有决策为空、`status=pending`、
   `final_gold_status=not_generated`。仲裁完成前不得使用`frozen`或运行真实成绩发布流程。

```bash
python -m app.cli.layout_gold_workflow import-annotations \
  --manifest /private/work/anomaly-transformer-layout/case_manifest.json \
  --annotator-a /private/work/anomaly-transformer-layout/annotations/annotator_a.json \
  --annotator-b /private/work/anomaly-transformer-layout/annotations/annotator_b.json \
  --output-dir /private/work/anomaly-transformer-layout/review \
  --commit
```

仲裁后的真实评测除总分外，错误分析至少分类为：章节漏检/误检/层级错误，Figure/Table漏检/误检，
图注截断/OCR错误，页码偏移，正文引用漏检/目标错误，以及表格行列合并、拆分和跨页/跨单元格错误。
当前这些条目仍是待办，不能用合成冒烟结果代替。

Git只允许提交案例清单、最终可再分发的结构化Gold、评测报告和质控记录；原PDF、渲染页、无权
再分发的原图、临时外部解析输出和任何本地绝对路径都禁止提交。

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

## R3 研究进展与候选研究机会

离线 API 使用本地 Gold 注册表，不会调用外部检索服务，也不会把排队记录、开发种子或未核验
EvidenceAnchor 当作研究证据：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/research/opportunities \
  -H 'Content-Type: application/json' \
  -d '{"query":"time series anomaly detection","year_from":2019,"year_to":2024,"minimum_evidence_papers":2}'
```

响应包含`query_plan`、线性`progress_map`和`candidates`。`query_plan`列出查询步骤、纳入/排除
规则、逐论文选择理由、年份覆盖和可能遗漏。候选只能由规则匹配到的已核验 EvidenceAnchor 产生，
并包含支持/冲突证据、不同论文数量、置信度计算、人工确认事项、适用条件和禁止结论。置信度上限
为0.85，表示当前证据覆盖与一致性，不是新颖性概率，也不证明优先权、可行性或必然贡献。

当前仓库真实离线清单有5篇注册论文，但0篇同时达到`double_annotated/frozen`和已核验证据要求，
所以默认请求返回HTTP 200、`status=insufficient_evidence`和空候选。八类规则的正向输出仅由
`synthetic-opportunity-fixture`测试数据验证；该 fixture 不参与运行时语料，也不是实际论文分析成绩。
前端在`http://127.0.0.1:5173/workspace#opportunities`展示同一查询计划、证据列表和时间线，不用知识
图谱大球。

### 研究假设到实验/图表计划

先从研究机会响应中选择一个`candidate_id`，再提交用户自己的Project Claim：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/research/experiment-plans \
  -H 'Content-Type: application/json' \
  -d '{
    "opportunity":{"query":"time series anomaly detection","minimum_evidence_papers":2},
    "candidate_id":"<candidate_id_from_previous_response>",
    "project_claim":{
      "research_question":"Does the proposed detector remain reliable under a controlled shift?",
      "hypothesis":"The proposed method degrades more slowly than comparable baselines as shift severity increases.",
      "proposed_method":"A user-defined association-aware detector"
    }
  }'
```

Project Claim固定标记`origin=user_supplied`。服务端重新执行同一研究机会查询，不能用客户端伪造
或已离开查询范围的候选；没有合格候选时返回`insufficient_evidence`且`plan=null`，候选ID不属于
当前查询时返回404。

成功计划包含主实验、基线覆盖、消融、敏感性、鲁棒性和失败案例分析，以及与实验ID闭合的六类
图表。实验记录验证目标、变量、控制条件、所需输入、输出Schema、反驳条件和解释边界；图表记录
变量、输出字段、表达建议和证据边界。每项规划推断均引用候选的EvidenceAnchor快照，并明确标记
`system_planning_inference`。接口只生成计划Schema，不生成实验数据、图表数值或结果结论。

当前真实离线语料仍没有合格候选，因此本接口默认展示证据不足门禁。正向计划只在
`synthetic-opportunity-fixture`测试中验证契约和关系闭合，不是实际研究建议质量成绩。

## R4 Project Claim与证据需求诊断

前端入口为`http://127.0.0.1:5173/workspace#project-claim`。默认配置使用进程内存存储，重启后数据清空：

```dotenv
PROJECT_CLAIM_BACKEND=memory
```

需要MySQL权威持久化时，先运行`python -m alembic upgrade head`，再改为：

```dotenv
PROJECT_CLAIM_BACKEND=mysql
```

获取明确标记、且不含实验结果的合成TAD表单示例：

```bash
curl http://127.0.0.1:8000/api/v1/research/project-claims/examples/tad
```

创建首个不可变Claim版本并同时生成八项规则诊断：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/research/projects/tad-noise-study/claims \
  -H 'Content-Type: application/json' \
  -d '{
    "expected_latest_version":0,
    "claim":{
      "research_question":"Does an association-aware detector remain reliable under sensor noise?",
      "hypothesis":"Under one fixed protocol, the proposed method degrades more slowly than selected strong baselines as noise increases.",
      "proposed_method":"A user-defined association-aware detector",
      "target_scenario":"Offline multivariate sensor anomaly detection",
      "existing_results":[]
    }
  }'
```

同一项目再次POST完整Claim内容会创建v2，必须提交正确的`expected_latest_version`；过期版本返回
409。`GET /api/v1/research/projects/{project_id}/claims`返回不可变版本历史。诊断的八种类型固定为
`main_experiment`、`strong_baseline`、`fair_comparison`、`ablation`、
`parameter_sensitivity`、`robustness`、`efficiency`和`failure_cases`。

前端可编辑诊断理由、变量、输出字段、推荐图表、证明边界、状态和备注；保存时调用
`PUT /api/v1/research/projects/{project_id}/claims/{version}/diagnosis`并创建新修订，不覆盖Claim
或上一诊断修订。所有自动文案来自`project-claim-evidence-rules-v1`确定性模板；本轮未调用模型，
也不评估实验可行性或研究创新性。

### Project Claim到实验与图表计划

Claim创建后，可选择一个或多个同项目Claim版本生成第一版计划：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/research/projects/tad-noise-study/experiment-plans \
  -H 'Content-Type: application/json' \
  -d '{"expected_latest_revision":0,"claim_versions":[1]}'
```

响应包含八类`experiments`、相互闭合的`artifacts`、`generation_basis`和逐实验
`quality_report`。每个ExperimentPlan保存所关联的一个或多个稳定`claim_version_id`，RQ和
Hypothesis必须与这些Claim版本原文一致。Dataset、Baseline、Variables、Controls、Metrics、
ExpectedArtifact、Boundary和Status均为计划字段，不是实验结果。

自动生成器不知道用户最终选择的数据集、强基线实现和指标定义，所以使用
`dataset_pending_user_selection`、`strong_baseline_pending_user_selection`和
`primary_metric_to_predeclare`等显式待办；待选强基线默认为`excluded`，质量检查会提示
`missing_strong_baseline`。团队必须在确认前替换这些待办，不能把它们写成已经执行的配置。

图表计划明确保存`artifact_kind=figure/table`、形式理由、横纵轴或行列设计、数据字段、支持Claim
以及常见误读。计划器不接受额外结果字段，不生成`metric_value`、预期提升或图表数值。五类检查为：
`missing_strong_baseline`、`data_leakage`、`unfair_setup`、`metric_inconsistency`和
`overclaiming`。

前端在同一`#project-claim`工作区编辑计划。每个Experiment/Artifact可以标记为`suggested`、
`confirmed`、`modified`或`rejected`；保存调用：

```text
PUT /api/v1/research/projects/{project_id}/experiment-plans/{revision}
```

后端追加`user_edited`新修订并重新计算质量检查，不覆盖旧版本。以下接口用于读取历史和指定修订：

```text
GET /api/v1/research/projects/{project_id}/experiment-plans
GET /api/v1/research/projects/{project_id}/experiment-plans/{revision}
```

合成TAD端到端演示沿用`/research/project-claims/examples/tad`：先创建Claim，再生成并编辑计划。
它只验证Claim→诊断→Experiment→Artifact关系和版本流转，不是实际实验结果或计划质量成绩。

### 用户实验数据到可追溯图表草稿

在`#project-claim`工作区加载一个包含Figure ArtifactPlan的计划后，选择本地CSV或JSON上传。接口不接收
URL、服务器文件路径或用户Python：

```bash
curl -X POST \
  http://127.0.0.1:8000/api/v1/research/projects/tad-noise-study/plot-drafts/uploads \
  -F "file=@./my-real-results.csv;type=text/csv"
```

响应返回列类型、缺失值、行数和原始文件SHA-256。`authenticity_statement`固定为
`user_uploaded_not_independently_verified`：这表示数据确由用户通过接口提供，不表示系统已核验实验真实发生。
CSV使用原始文件行号，JSON使用数组中从1开始的记录号。关键绘图字段如果缺失、类型不一致或含空值，
下一步会硬阻断；系统不做插补。

选择计划修订和其中一个Figure ArtifactPlan后生成代码：

```text
POST /api/v1/research/projects/{project_id}/plot-drafts
```

请求必须包含`upload_id`、`plan_revision`、`artifact_plan_id`、`plot_kind`、X/Y/可选分组字段、标题、
轴标签、显式单位、聚合与误差线策略、坐标范围和PNG/SVG/PDF格式。服务端只生成
`matplotlib-traceable-v1`固定模板，不接受客户端代码，也不会生成结果值。代码生成后尚无图片；先检查
`plot-integrity-rules-v1`对截断轴、平滑、误差线和视觉风险的报告，再显式执行：

```text
POST /api/v1/research/projects/{project_id}/plot-drafts/{draft_id}/execute
```

执行器只运行哈希与草稿记录一致的服务端模板，使用独立临时目录、`python -I`、无shell、Agg后端、
最小环境和20秒超时。当前是受控子进程边界，不是容器或虚拟机级恶意代码沙箱；安全性依赖“不接收
用户代码”和固定模板。失败时响应包含`error_code/error_message`，并删除任何不完整图片。

成功后可下载单个图或`plot-draft-bundle.zip`。可复现包包含：

- `plot.py`和`plot_config.json`；
- `data.normalized.json`（未插补，含源行号）；
- `traceability.json`（每个图中数值对应的源行和聚合规则）；
- `execution_manifest.json`（数据/代码哈希、生成参数、Python和Matplotlib版本）；
- 实际成功导出的PNG/SVG/PDF。

上传和草稿当前保存在操作系统临时目录及进程内索引，API进程重启后失效。仓库内的
`synthetic_plot_smoke.csv`只验证绘图程序和溯源闭合，不是论文、TAD或比赛实验成绩。

### 持久化实验运行清单与数据生命周期

运行清单默认沿用离线内存模式。要让清单修订跨重启保存到MySQL，计划与Claim也必须使用同一
MySQL权威库：

```dotenv
PROJECT_CLAIM_BACKEND=mysql
EXPERIMENT_RUN_BACKEND=mysql
```

运行`python -m alembic upgrade head`升级到`0006_experiment_run_manifests`。数据库只保存运行清单、
配置/数据/Schema/绘图代码哈希和生命周期状态，不保存上传CSV/JSON的原始字节或规范化数据载荷。
默认`EXPERIMENT_RUN_BACKEND=memory`继续支持完全离线演示，但不跨进程保存清单。

先从现有计划中选择一个Experiment并登记实际运行：

```text
POST /api/v1/research/projects/{project_id}/experiment-runs
```

请求记录以下内容：

- `plan_revision + experiment_id`；
- 自报`actor_id/display_name`，身份保证固定为`self_asserted_local_identity`；
- 实际入口命令、代码修订、数据集版本、随机种子、命令参数和普通JSON参数；
- 用户报告的操作系统、Python、硬件、框架版本和可选容器镜像摘要；
- `user_declared`或`externally_verifiable`结果来源；
- `process_session`或`metadata_only`数据生命周期。

服务端按键排序和规范JSON序列化计算`run_configuration_sha256`。任何名称包含password、secret、
token或API key语义的参数键会被拒绝，密钥只能留在实验环境变量或秘密管理系统中。

`externally_verifiable`不是“已验证”。它必须带签发方、引用和证据文件SHA-256，且状态只能为
`pending_external_verification`；当前没有受信任核验账号或审批端点，上传者不能自行升级状态。

将数据绑定到运行时必须再次提交同一自报`actor_id`：

```text
POST /api/v1/research/projects/{project_id}/experiment-runs/{run_id}/data
```

`process_session`把规范化数据保存在受控临时目录，最长可配置72小时，但进程退出时可能更早清除；
`metadata_only`立即丢弃可绘图数据，只保留文件哈希、Schema哈希、行数和审计修订。原始上传字节在
两种模式下都不会写MySQL或长期文件系统。

绘图请求增加`run_id + actor_id`。后端同时检查运行的计划修订、Experiment、上传ID和ArtifactPlan
关系；跨运行、跨Experiment或已删除/到期数据都不能生成图。执行终态追加`plot_succeeded`或
`plot_failed`修订。读取历史和显式删除接口为：

```text
GET    /api/v1/research/projects/{project_id}/experiment-runs/{run_id}/history
DELETE /api/v1/research/projects/{project_id}/experiment-runs/{run_id}/data
```

删除会清除规范化数据、生成代码、图像和下载包，但保留包含数据SHA-256及删除时间的审计修订。
本地`actor_id`只是防止界面误操作的自报绑定，不是安全认证；多用户部署前必须接入真正的认证、
授权、加密对象存储和可信外部核验流程。

## 安全

- 后端持有外部服务密钥，前端不保存密钥。
- `.env` 已被 Git 忽略。
- 曾经粘贴到聊天中的令牌必须撤销，不能重复使用。
