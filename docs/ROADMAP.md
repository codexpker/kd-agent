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
- [ ] Step 2：恢复面向规范化权威实体的可重复入库。
  - [x] CLI默认dry-run且零写入，只有显式`--commit`才写MySQL；图同步参数必须与`--commit`同时使用。
  - [x] 按`paper_id + dataset_version`事务性创建或替换NarrativeMove、Claim、ExperimentIntent、ArtifactRole、EvidenceAnchor、Limitation及关系。
  - [x] MySQL提交后才同步Neo4j；MySQL失败时图调用为零，Neo4j失败时返回并持久化`partial/failed`。
  - [x] 通过单元测试、SQLite CLI集成测试，以及MySQL 8.4 / Neo4j 5.26真实双次入库验收。
  - [ ] 保护更高质量或更新的PaperSource元数据，避免低质量来源覆盖。
- [ ] 将 Gold 扩至 5–10 篇并完成仲裁。

## R3

- [ ] 多论文对比矩阵。
- [ ] 研究进展地图与证据冲突检测。
- [ ] 从研究假设反推实验和图表计划。
