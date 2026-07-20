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
  - [x] 审计本地文件和MySQL来源：初次审计无PDF；现已发现用户指定的本地候选PDF，但尚未确认权利依据。MySQL仍无`PdfSource`，唯一来源为未确认全文权利的`metadata_only`；未联网下载。
  - [x] 建立案例阻塞清单与数据清单，明确`needs_authorized_pdf`、`needs_second_annotator`，不标记frozen。
  - [x] 提供默认dry-run的授权PDF初始化、SHA-256/来源记录、PyMuPDF候选、GROBID/MinerU候选导入工具；不复制PDF或外部原始输出。
  - [x] 提供A/B独立空白标注、第二标注员显式注册、来源一致性校验、字段级差异报告和全未决仲裁模板；不自动覆盖分歧。
  - [ ] 获得用户明确提供、开放许可或机构授权的Anomaly Transformer PDF，并记录来源、权利依据和精确SHA-256。
  - [ ] 注册两名不同标注员和独立仲裁员，完成章节、图表、引用、页码/bbox、图注及表格结构标注与仲裁。
  - [ ] 对同一SHA运行固定版本的PyMuPDF、GROBID、MinerU真实评测，并输出分项错误类型分析。
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
  - [x] `make demo-accept-offline`统一运行后端全测、Vue生产构建和浏览器黄金流程；`make demo-accept`再追加真实MySQL/Neo4j R2接受测试。
- [x] 建立第一阶段“对话式科研工作台”，修复单页超长表单作为唯一入口的问题。
  - [x] 引入Vue Router和固定应用壳，默认进入科研助理；论文、项目、机会、实验图表、知识图谱和专业工作区均有明确导航，原有结构化能力继续兼容。
  - [x] 科研助理提供拆解论文、分析研究机会、诊断Claim和生成实验图表四类任务入口，以执行步骤、证据侧栏和结构化工作区承载结果，不把聊天文本作为唯一产物。
  - [x] 当前自然语言入口明确标记为`离线规则导航`，只做意图分流和澄清；未连接模型时不冒充多轮智能体或大模型推理。
  - [x] 新增`GET /api/v1/papers/{paper_id}/evidence-graph`；默认`gold_snapshot`保持离线，显式`neo4j`模式延迟加载驱动并返回真实可重建索引，失败时503且不静默伪造。
  - [x] 前端以可读证据列表为主、局部SVG关系图为辅，显示数据来源、未核验状态和MySQL权威边界；真实Neo4j容器查询通过30节点/65关系验收。
  - [x] Playwright黄金流程增加科研助理、四类任务、证据链步骤和关系图可见性检查，同时继续覆盖R4真实数据绘图闭环。
- [x] 建立第一篇可演示的论文逆向工程阅读器，保留PDF阅读与文献关系探索能力但不复制竞品界面。
  - [x] 新增`/papers/{paper_id}`独立路由，把文档结构、科研叙事链、Claim、实验意图、Figure/Table角色、EvidenceAnchor和局部关系图组织为三栏审核界面。
  - [x] 阅读器复用`paper-deconstruct`、`document-structure`和`evidence-graph`真实接口，不以聊天文本重新生成或改写结构化事实；未知或未公开记录继续返回并显示不可加载。
  - [x] `DocumentStructure`客观版面与`PaperDeconstruction`科研语义保持分区；`gold_snapshot`状态明确阻断PDF定位，不显示未核验页码、图注、bbox或正文引用，也不提供PDF文件分发端点。
  - [x] 提供离线规则式阅读问题导航、Claim筛选和证据透镜联动；关系图只作为局部闭合检查，EvidenceAnchor列表仍是主要审核界面。
  - [x] Playwright黄金流程覆盖8步叙事链、2项实验意图、5张图表角色、21个局部证据节点以及未授权PDF定位硬阻断。
- [ ] 下一阶段：接入真实星火或开源模型的会话/工具调用层，保存对话与任务运行历史，并保持离线规则导航为可识别的降级模式；完成前不得宣称已具备真实多轮智能体能力。
- [ ] 后续：接入真正的认证身份、受信任外部核验者工作流和加密对象存储；在此之前不得把自报身份或`pending_external_verification`写成已认证/已验证。
