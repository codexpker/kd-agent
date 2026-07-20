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

- [ ] 多论文对比矩阵。
- [ ] 研究进展地图与证据冲突检测。
- [ ] 从研究假设反推实验和图表计划。
