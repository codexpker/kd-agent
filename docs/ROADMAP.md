# 研发路线

## 已在重建交接版恢复

- [x] 离线可运行的 FastAPI + Vue 工作台。
- [x] 论文逆向工程稳定数据契约。
- [x] Anomaly Transformer Gold 开发种子。
- [x] 实验意图、图表角色与证据锚点。
- [x] 文档结构查询的 Gold 降级接口。
- [x] PDF 统一结构契约与解析器适配接口。
- [x] 本地部署与三库 Compose 配置。

## R2 下一步

> 2026-07-20 排期调整：需要全文权利确认、第二标注员或仲裁员参与的工作统一后推；
> 5 篇 TAD Gold 和正式多解析器比较不作为当前 R3 工程工作的阻塞项。下列未完成状态保持不变。

- [ ] 确认 5 篇 TAD 论文的合法全文来源。
- [ ] 两名标注员独立完成章节、图表、正文引用与页码真值。
- [ ] 正式比较 PyMuPDF、GROBID、MinerU。
- [x] Step 1：重新建立MySQL权威实体和新的Alembic迁移基线。
  - [x] 保留`0001_reconstructed`引导基线，新增`0002_reconstructed_authority`，不伪造旧迁移历史。
  - [x] 建立Paper、PaperSource、GoldDatasetVersion、PaperGoldRecord、NarrativeMove、Claim、ExperimentIntent、ArtifactRole、EvidenceAnchor、Limitation及关系表。
  - [x] 以SQLite验证空库升级、降级和再升级，并在MySQL 8.4真实容器验证迁移与外键。
- [x] Step 2：恢复面向规范化权威实体的可重复入库。
  - [x] CLI默认dry-run且零写入，只有显式`--commit`才写MySQL；图同步参数必须与`--commit`同时使用。
  - [x] 按`paper_id + dataset_version`事务性创建或替换NarrativeMove、Claim、ExperimentIntent、ArtifactRole、EvidenceAnchor、Limitation及关系。
  - [x] MySQL提交后才同步Neo4j；MySQL失败时图调用为零，Neo4j失败时返回并持久化`partial/failed`。
  - [x] 通过单元测试、SQLite CLI集成测试，以及MySQL 8.4 / Neo4j 5.26真实双次入库验收。
  - [x] PaperSource按稳定`source_key`并存；同键按来源质量优先、同质量按`retrieved_at`更新，低质量候选返回`protected`且不能覆盖，主来源按质量与时间确定。
- [x] Step 3：恢复PDF客观版面事实的解析、持久化和查询闭环。
  - [x] 新增`0003_reconstructed_pdf_layout`，建立PDF来源、解析运行、章节、Figure/Table与正文引用规范化实体；SQLite和MySQL 8.4升降级通过。
  - [x] 只保存权利依据、文件SHA-256/大小、解析器版本和结构化事实，不保存PDF二进制或本地路径。
  - [x] CLI默认dry-run；只有显式`--commit`且提供开放全文、用户私有副本或机构授权依据才持久化，无依据时硬阻断且零写入。
  - [x] 保存章节层级/页码/标题bbox、Artifact页码/bbox/图注/结构化表格，以及正文引用的目标、页码和bbox。
  - [x] 查询优先返回规范化`parsed_pdf`，缺失时回退到无伪造页码、bbox、图注、表格和正文引用的`gold_snapshot`。
  - [x] `DocumentStructure`保持客观事实、`PaperDeconstruction`保持科研语义；离线默认模式继续延迟加载数据库仓储和PyMuPDF。
- [x] Step 4a：建立三解析器统一映射与可重复评测框架（不代表真实论文评测已完成）。
  - [x] PyMuPDF、GROBID TEI和MinerU JSON统一输出`ParsedDocument`；适配器不依赖数据库，持久化继续由独立服务及权利门禁负责。
  - [x] 建立`layout-gold-v1` Schema、双人标注/仲裁约束和人工模板；真实报告拒绝未仲裁Gold。
  - [x] 实现章节标题F1、层级准确率、Figure/Table检测F1、图注相似度、页码准确率、正文引用F1和表格单元格F1。
  - [x] 生成JSON与Markdown报告；CI内置样例强制标记`synthetic_smoke_test`，不得作为真实解析成绩。
  - [x] 未配置GROBID或MinerU客户端时明确返回`unavailable`，不静默生成或替代解析结果。
- [ ] Step 4b：建立Anomaly Transformer第一篇可审核真实版面Gold。
  - [x] 用户已明确提供本地私有副本并授权本地处理；记录`user_private_copy`依据、确认人、不可再分发说明、文件大小及SHA-256 `ff8d3bb627fce9914eb8a9e78c4139e4852771dbee801da2c766dea028a17053`，未联网下载、未提交PDF。
  - [x] PyMuPDF 1.28.0真实解析已写入MySQL：20页、28个TOC章节、25个Figure/Table和27处正文引用；查询返回最新成功运行，原PDF与本地路径未入库。该结果是待复核的`parsed_pdf`，不是版面Gold或解析器成绩。
  - [x] 案例清单准确标记`annotation_not_started`：没有把PDF提供者伪记为标注员，也没有把开发种子标记为frozen；人工工作按当前排期后推。
  - [x] 提供默认dry-run的授权PDF初始化、SHA-256/来源记录、PyMuPDF候选、GROBID/MinerU候选导入工具；不复制PDF或外部原始输出。
  - [x] 提供A/B独立空白标注、第二标注员显式注册、来源一致性校验、字段级差异报告和全未决仲裁模板；不自动覆盖分歧。
  - [ ] 注册两名不同标注员和独立仲裁员，完成章节、图表、引用、页码/bbox、图注及表格结构标注与仲裁。
  - [ ] 为同一SHA生成可审计的GROBID和MinerU真实候选；待双人仲裁Gold完成后，正式运行三解析器评测并输出分项错误类型分析。
- [ ] 将 Gold 扩至 5–10 篇并完成仲裁。

## R3

- [ ] 多论文对比矩阵（后推；等待足量双审、已核验论文，不用开发种子或合成数据填充）。
- [x] 研究进展与 Research Opportunity Candidate 分析框架。
  - [x] 通过版本化结构规则覆盖共同未解局限、结论冲突、少数据集验证、鲁棒性缺口、成本过高、基准饱和、消融不足和评价协议不一致八类候选。
  - [x] 每个候选返回完整 EvidenceAnchor、支持/冲突证据、语料与年份覆盖、可复算置信度依据、人工确认项、适用条件和禁止结论。
  - [x] API 显示查询计划、纳入/排除规则、逐论文选择理由和可能遗漏；低于最少不同论文覆盖时返回`insufficient_evidence`且候选为空。
  - [x] Vue 提供可读的时间线式研究进展地图和证据候选列表，不以知识图谱大球代替证据。
  - [x] 八类正向路径只使用明确标记的合成双审 fixture 做规则测试；当前真实离线清单为 5 篇注册、0 篇满足双审与已核验证据，实际接口返回`insufficient_evidence`，没有真实研究机会成绩。
- [ ] 扩充足量双审、已核验 EvidenceAnchor 的真实论文语料后，验证真实候选及冲突召回质量。
- [x] 从用户研究假设反推实验和图表计划的证据约束框架。
  - [x] 用户显式提交研究问题、可证伪假设和拟议方法，保存为`origin=user_supplied`，系统不擅自补成事实。
  - [x] 只有当前查询中证据门禁通过的 Research Opportunity Candidate 才能生成计划；真实离线语料不足时返回`insufficient_evidence`且不生成实验或图表。
  - [x] 生成主实验、基线覆盖、消融、敏感性、鲁棒性和失败案例六类计划；每项记录验证目标、自/因/控制变量、输入、输出字段、反驳条件、证据边界及 EvidenceAnchor 引用。
  - [x] 生成主结果表、消融表、敏感性曲线、鲁棒性图、失败案例面板和效果—资源权衡图；图表与来源实验ID闭合，并显式保存变量、输出字段和禁止解读边界。
  - [x] Vue支持选择候选、录入可编辑Project Claim并展示实验/图表计划；不生成实验数值、结果或结论。
- [ ] 使用真实合格候选与实际实验配置验证研究教练计划质量（人工评审与实验执行统一后推）。

## R4 推进我的研究

- [x] Project Claim录入和最小证据需求诊断。
  - [x] 录入研究问题、假设、拟议方法、目标场景和已有结果；所有内容标记为`user_supplied`或`user_reported`，已有结果固定为未核验，不改写成事实。
  - [x] 新增`0004_project_claim_versions`，以不可变Claim版本、父版本链接、内容SHA-256和乐观并发控制建立MySQL权威模型；诊断编辑保存为独立修订。
  - [x] 默认离线`PROJECT_CLAIM_BACKEND=memory`不依赖数据库；显式切换`mysql`后延迟加载SQLAlchemy仓储。
  - [x] `project-claim-evidence-rules-v1`固定诊断主实验、强基线、公平比较、消融、参数敏感性、鲁棒性、效率和失败案例八项最小证据。
  - [x] 每项记录所验证的Claim原文、必要性、自变量、控制变量、输出字段、推荐Figure/Table、能支持和不能支持的结论。
  - [x] 诊断可编辑并生成`user_edited`新修订；可行性和创新性固定为`not_assessed`，本轮不调用模型、不生成实验数据。
  - [x] 提供API、Vue工作区、明确标记的合成TAD表单示例、单元/API/仓储/迁移测试。
- [x] 将Project Claim诊断转化为版本化实验与图表计划。
  - [x] 新增`0005_experiment_artifact_plans`，保存不可变计划修订，并以规范化关系表闭合每个Experiment/Artifact到一个或多个稳定Claim版本；默认离线内存模式仍可用。
  - [x] `project-experiment-artifact-rules-v1`按八类证据需求生成RQ、Hypothesis、Dataset、Baseline、Variables、Controls、Metrics、ExpectedArtifact、Boundary和Status；RQ/Hypothesis保持所关联Claim原文。
  - [x] ArtifactPlan明确Figure/Table形式理由、轴或行列设计、数据字段、Claim关联和常见误读；Experiment与Artifact双向ID闭合。
  - [x] `experiment-plan-quality-rules-v1`逐实验检查缺少强基线、数据泄漏、不公平设置、指标不一致和过度结论；待选择数据集/强基线保持显式占位并触发提示，不冒充已确认配置。
  - [x] 用户可将每项建议标记为`confirmed`、`modified`或`rejected`，编辑保存为`user_edited`新修订，保留生成所用诊断修订、需求ID和规则ID。
  - [x] API、Vue编辑界面、MySQL/SQLite仓储、迁移升降级及合成TAD端到端流程通过测试；契约禁止额外结果或预期数值字段。
- [x] 将用户上传的真实实验数据转为可执行绘图代码与可追溯图表草稿。
  - [x] 只提供CSV/JSON文件上传入口，不接受URL、服务器路径或客户端Python；记录原始文件SHA-256，并将真实性明确标记为`user_uploaded_not_independently_verified`。
  - [x] 上传后检查UTF-8、文件/行列上限、表头、记录结构、推断类型和缺失值；生成代码前再次硬校验X/Y/分组关键字段，关键字段缺失时不插补并阻断。
  - [x] `matplotlib-traceable-v1`只生成固定模板代码，用户数据保存在相邻规范化JSON而不拼进源码；代码SHA-256、生成参数、Python/Matplotlib版本和原始/规范化数据哈希进入运行清单。
  - [x] 只执行服务端生成且哈希未变的代码，使用独立临时目录、`python -I`、无shell、Agg后端、最小环境和超时；执行失败或输出缺失时不提供图片。
  - [x] 逐绘图点保存原始CSV行号/JSON记录号、`identity`或均值/样本标准差聚合规则；完整下载包包含代码、规范化数据、参数、运行清单、溯源JSON和PNG/SVG/PDF产物。
  - [x] `plot-integrity-rules-v1`检查截断坐标轴、非允许平滑、重复观测缺少误差线、重叠柱/重复X折线风险，以及标题、坐标、单位、图例和论文导出格式。
  - [x] Vue完成上传、Schema报告、ArtifactPlan关联、参数编辑、只读代码预览、显式执行、成功后预览与下载；合成非科研敏感CSV只用于自动化流程测试，不是比赛实验成绩。
- [x] 建立持久化实验运行清单与上传数据生命周期策略。
  - [x] 新增`0006_experiment_run_manifests`，以不可变修订链保存运行登记、数据绑定、绘图成功/失败及删除/到期审计；MySQL保存清单与哈希，不保存CSV/JSON原始字节或规范化结果载荷。
  - [x] 每个运行闭合到稳定`plan_revision_id + experiment_id`，并对入口命令、代码修订、数据集版本、随机种子、参数和命令参数计算规范化配置SHA-256；秘密样式配置键硬阻断。
  - [x] 保存用户自报身份和用户报告的操作系统、Python、硬件、框架版本及可选容器摘要；本地模式身份固定标记`self_asserted_local_identity`，不冒充已认证账号。
  - [x] 区分`user_declared`与`externally_verifiable`；后者必须提供签发方、证据引用和SHA-256，但状态只能是`pending_external_verification`，上传者不能自行标记已验证。
  - [x] 生命周期支持`process_session`和`metadata_only`：原始上传从不持久化；规范化数据最多保留72小时且受进程临时目录限制，或立即只留哈希/Schema。到期和显式删除追加审计修订并清除临时图表。
  - [x] 新运行API、带身份门禁的数据绑定、运行—上传—Experiment—Artifact闭合校验、Vue登记/历史/删除界面及内存/MySQL/API/迁移/错误路径测试通过；默认离线模式保持可用。
- [x] 建立可重复的Demo Acceptance Gate，不再以手工页面检查代替核心流程验收。
  - [x] 新增单一Playwright黄金流程，自动启动独立离线后端与Vite，覆盖开发种子边界、`gold_snapshot`空页码、真实语料`insufficient_evidence`和R4完整绘图闭环。
  - [x] 浏览器验收从合成TAD表单继续到Claim v1、八项诊断、Experiment/Artifact Plan、运行登记、CSV Schema、受控绘图、PNG/SVG、逐点溯源JSON和复现包；合成数据不被标记为科研成绩。
  - [x] 运行登记默认选择带Figure的Experiment，并在Table-only实验上显示明确提示，避免演示在空Figure ArtifactPlan处无解释停止。
  - [x] `make demo-accept-offline`统一运行后端全测、Vue生产构建和浏览器黄金流程；`make demo-accept`再追加真实MySQL/Neo4j R2验收与授权私有PDF浏览器闭环。
  - [x] 真实基础设施Playwright套件硬校验MySQL `parsed_pdf`、本地SHA-256匹配PNG、Figure 1第4页联动、Neo4j 30节点/65关系、9阶段核心链及1280×720下至少580px的PDF显示宽度；星辰仍固定为`offline`，该套件不进入无外部服务CI。
- [x] 建立第一阶段“对话式科研工作台”，修复单页超长表单作为唯一入口的问题。
  - [x] 引入Vue Router和固定应用壳，默认进入科研助理；论文、项目、机会、实验图表、知识图谱和专业工作区均有明确导航，原有结构化能力继续兼容。
  - [x] 科研助理提供拆解论文、分析研究机会、诊断Claim和生成实验图表四类任务入口，以执行步骤、证据侧栏和结构化工作区承载结果，不把聊天文本作为唯一产物。
  - [x] 当前自然语言入口明确标记为`离线规则导航`，只做意图分流和澄清；未连接模型时不冒充多轮智能体或大模型推理。
  - [x] 新增`GET /api/v1/papers/{paper_id}/evidence-graph`；默认`gold_snapshot`保持离线，显式`neo4j`模式延迟加载驱动并返回真实可重建索引，失败时503且不静默伪造。
  - [x] 前端以可读证据列表和按Claim裁剪的关系路径为主，显示数据来源、未核验状态和MySQL权威边界；真实Neo4j容器查询通过30节点/65关系验收。
  - [x] Playwright黄金流程增加科研助理、四类任务、证据链步骤和关系图可见性检查，同时继续覆盖R4真实数据绘图闭环。
- [x] 建立第一篇可演示的论文逆向工程阅读器，保留PDF阅读与文献关系探索能力但不复制竞品界面。
  - [x] 新增`/papers/{paper_id}`独立路由；经真实浏览器验收后从不可读的三栏布局收敛为论文优先双栏工作区，左侧承载大幅真实页图，右侧统一承载核心链、实验、图表、证据与关系路径。
  - [x] 阅读器复用`paper-deconstruct`、`document-structure`和`evidence-graph`真实接口，不以聊天文本重新生成或改写结构化事实；未知或未公开记录继续返回并显示不可加载。
  - [x] `DocumentStructure`客观版面与`PaperDeconstruction`科研语义保持分区；`gold_snapshot`状态明确阻断PDF定位，不显示未核验页码、图注、bbox或正文引用，也不提供PDF文件分发端点。
  - [x] 提供离线规则式阅读问题导航、Claim筛选和证据透镜联动；关系图只作为局部闭合检查，EvidenceAnchor列表仍是主要审核界面。
  - [x] Playwright黄金流程覆盖9阶段核心链、8步叙事动作、2项实验意图、5张图表角色、按Claim聚焦的关系路径以及未授权PDF定位硬阻断。
- [x] 完成Anomaly Transformer单篇真实解析演示加固（不等于Gold完成）。
  - [x] 新增默认关闭、仅本地模式可启用的受控PDF预览；服务只在配置根目录中按MySQL SHA-256匹配私有副本，只返回即时PNG，响应`private, no-store`，不暴露路径、不提供原PDF下载。
  - [x] 点击章节或EvidenceAnchor可联动真实解析页；Figure/Table优先显示自动检测的对象/图注框、真实解析图注与正文引用，加载失败明确报错而不显示占位成功图。
  - [x] 开发语义记录改为中文可读转述，并与`pymupdf自动解析（待复核）`客观版面事实分栏显示；人工核验仍为0/10，不把自动解析写成双人Gold。
  - [x] 科研助理默认用纵向路径卡展示一个Claim、支撑实验/图表和相关EvidenceAnchor；论文阅读器保留显示`支撑/依据`语义的10节点局部图。Neo4j真实返回30节点/65关系，MySQL仍为权威源。
  - [x] 真实接口验收通过：`parsed_pdf`、`neo4j`和受控PNG均来自本地服务；星辰配置为空，助手继续明确显示`offline`，没有把Mock或规则回答伪装成线上模型调用。
- [x] 完成汇报前核心演示链路可用性加固（星辰接入继续后推）。
  - [x] 论文路由自动收起全局侧栏，真实页图在1280×720浏览器中获得约674px工作宽度；支持70%–180%缩放、翻页、章节抽屉与独立滚动，不再把PDF压缩为约231px缩略图。
  - [x] 新增章节预览端点，使用持久化`heading_bbox`在哈希匹配的私有副本页图上绘制定位框；Figure/Table继续使用对象框或图注框，不返回原PDF。
  - [x] 右侧显式展示`Problem → Gap → Hypothesis → Method → Claim → Experiment → Figure/Table → Evidence → Boundary`九阶段视图；每个阶段只映射已有实体，Hypothesis明确复用待检验的method Claim而不新增事实。
  - [x] 修正开发种子中与真实PDF不一致的Figure角色：Figure 1为模型架构、Figure 2为极小极大学习、Figure 5为异常准则定性案例；更新后10/10 EvidenceAnchor均可匹配自动解析章节或图表，但仍为0/10双人核验。
  - [x] Neo4j以当前Claim的`SUPPORTS`/`SUPPORTED_BY`纵向路径呈现，显示真实`neo4j`来源、30节点/65关系和MySQL权威边界；图索引失败时阅读器显式降级，不连带阻断PDF与证据阅读。
  - [x] `/knowledge-graph`导航直接进入同一论文工作区的Neo4j路径页，不再跳到无效的助手查询参数。
  - [x] 新增私有PDF图表阅读摘图：Figure按图注向上、Table按图注及已解析对象范围即时裁剪，响应明确标记`derived-reading-excerpt`；裁剪窗口不持久化、不冒充Gold bbox，原PDF仍不分发。
  - [x] 图表页签直接展示5张真实Figure/Table摘图，并以确定性规则组合ArtifactRole、ExperimentIntent、Claim和Boundary，说明“回答什么、为何用图/表、参与支撑什么、不能推出什么”，不依赖模型补造解释。
  - [x] EvidenceAnchor总览增加Claim、实验、图表和叙事动作四类用途；关系页改为可读的`Claim → 实验/图表 → EvidenceAnchor`论证路径，并明确Neo4j只是可重建索引、有关系不等于已人工确认。
  - [x] 将含糊的`development_seed`用户标签改为“开发种子 · 未经双审”，明确它可用于结构学习但不是论文原句、正式引用或冻结Gold，也不要求普通用户进入数据库复核。
- [x] 建立可解释的演示启动与首次使用引导闭环。
  - [x] 新增`GET /api/v1/demo/readiness`，分别报告语义种子、文档结构、SHA-256匹配私有PDF、论证关系索引和语言层；`healthz`只表示API存活，不再被当作核心链路就绪证据。
  - [x] 离线模式明确以`gold_snapshot`和本地规则完成零外部依赖演示；真实模式要求MySQL `parsed_pdf`、可渲染私有副本和Neo4j均闭合，缺失项返回`degraded/blocked`及修复动作。
  - [x] 新增跨平台`python -m app.cli.demo_start`：默认零数据库写入；只有显式`--with-infrastructure`才启动MySQL/Neo4j、迁移并幂等同步开发种子，已有服务安全复用。
  - [x] 前端顶部显示“完全离线模式”或“本地真实链路”，提供五步演示向导，依次导航核心链、实验意图、真实图表、EvidenceAnchor用途和Claim论证路径。
  - [x] 单元、Vue生产构建、离线Playwright和真实基础设施Playwright均覆盖就绪状态与向导；星辰仍为可选语言层，不因未配置而伪报核心链路失败。
- [x] 建立论文拆解会话、工具运行历史和星辰真实协议适配基础闭环（不代表星辰线上调用已验证）。
  - [x] 新增创建/读取会话与发送消息API，保存`session_id`、`trace_id`、提示词版本、消息来源、EvidenceAnchor和实际工具运行；当前明确为`process_memory`，API重启后清空。
  - [x] 本轮只编排`paper_deconstruct`、`document_structure`和`evidence_graph`，工具选择由可测试的服务端规则完成，不宣称模型已自主规划工具。
  - [x] 默认`ASSISTANT_BACKEND=offline`继续零密钥运行；离线回答标记`offline_rule`，星辰回答标记`model_generated`，前端显示真实后端、trace和工具来源。
  - [x] 按官方星辰工作流HTTP协议实现Bearer鉴权、`flow_id`、`chat_id`和最多12条历史消息；密钥仅从服务端环境变量读取。
  - [x] 模型回答必须引用当前论文已存在的`[ev-*]`；无引用、未知引用、鉴权/网络失败和工作流中断返回显式`error/system_error`，不静默用离线模板伪装成功。
  - [x] 单元/API/Playwright测试覆盖多轮历史、乐观并发、三类工具、证据引用门禁和星辰协议Mock；Mock不作为真实外部模型效果或可用性证据。
- [ ] 使用团队已发布的星辰工作流和服务端密钥完成首次真实联调，记录工作流/模型版本、脱敏调用日志、延迟和失败案例；完成前不得宣称星辰线上链路已验证。
- [ ] 建立前端语义审核与批注工作台，使授权用户可在页面确认、修改或驳回自动/开发解读并保留版本历史；完成前“待双审”只是诚实的数据状态，不描述成普通用户必须操作数据库的流程。
- [ ] 将会话与工具运行历史迁移到MySQL权威存储；当前进程内历史不能描述为跨重启持久化。
- [ ] 后续：接入真正的认证身份、受信任外部核验者工作流和加密对象存储；在此之前不得把自报身份或`pending_external_verification`写成已认证/已验证。
