# 重建说明

## 为什么是重建版

原 `kd-agent-0caddf6.zip` 位于已回收的临时工作区，且当时最新的本地提交未推送远端。本工程依据保留下来的方案、功能清单、接口描述和验收记录重新实现，不能视为原提交的字节级副本。

## 已恢复并通过验证

- FastAPI 离线启动与 OpenAPI 文档。
- Vue 3 + TypeScript 论文逆向工程工作台。
- TAD 五篇首批清单与 Anomaly Transformer 开发种子。
- 叙事链、Claim、实验意图、图表角色、证据锚点和边界。
- 未知论文 404 与排队论文不加载门禁。
- Gold 结构快照，不伪造 PDF 页码、bbox、图注或正文引用。
- PyMuPDF、GROBID TEI 与 MinerU JSON 到统一`ParsedDocument`的映射框架。
- MySQL、Milvus、Neo4j 的 Compose 开发服务配置。

## 未从旧提交恢复、需要继续实现

- Alembic `0001–0006` 的原始迁移历史。
- GROBID 与 MinerU 外部服务客户端、部署及真实版本兼容性验收。
- 五篇真实 PDF 版面真值与解析器正式评测结果；当前只有明确标识的合成冒烟测试。

## R2 重建进展

- 已建立新的 `0001_reconstructed` → `0002_reconstructed_authority` 迁移链，没有冒充旧 `0001–0006` 历史。
- `0002_reconstructed_authority` 建立Paper、PaperSource、GoldDatasetVersion、PaperGoldRecord、NarrativeMove、Claim、ExperimentIntent、ArtifactRole、EvidenceAnchor、Limitation及闭合关系表。
- 已在SQLite验证空库升级、降级和再升级，并在Docker Desktop + WSL2的MySQL 8.4上完成真实迁移和外键检查。
- Gold CLI现已默认dry-run，只有显式`--commit`才按`paper_id + dataset_version`事务性写入或替换规范化派生对象；MySQL失败不会调用Neo4j，图失败返回`partial`并记录`failed`。
- PaperSource已纳入Gold事务：稳定来源键允许多来源并存；同键按来源质量优先、同质量按严格更新的抓取时间替换；低质量或过期候选记为`protected`而不覆盖，并确定唯一主来源。元数据访问策略不替代PDF持久化权利确认。
- 已新增`0003_reconstructed_pdf_layout`及PDF dry-run/显式提交CLI。规范化表只保存权利依据、文件哈希、解析器版本、章节、Figure/Table、bbox、图注、结构化表格和正文引用位置，不保存PDF原文件或路径。无权利依据时持久化硬阻断；查询优先返回`parsed_pdf`并安全回退到无伪造版面字段的`gold_snapshot`。
- 已建立三解析器统一映射与评测框架：适配器只产出`ParsedDocument`，GROBID TEI和MinerU JSON已覆盖章节、层级、页码/bbox、图表/图注、正文引用及结构化表格字段；数据库写入仍由独立服务负责。`layout-gold-v1`要求显式区分真实仲裁Gold与`synthetic_smoke_test`，并输出JSON和Markdown七类指标。内置满分样例只验证程序闭合，不是实际解析质量结论。
- 已审计Anomaly Transformer首篇真实版面Gold前置条件：工作区无PDF，MySQL无该论文`PdfSource`，现有PaperSource仅允许元数据且未确认全文权利，也未登记第二标注员。案例清单同时标记`needs_authorized_pdf`与`needs_second_annotator`。已提供授权后哈希/来源记录、独立空白标注、候选结果规范化导入、字段级差异和全未决仲裁模板；在合法PDF、双人标注和仲裁到位前不生成或声称真实Gold。

继续开发时以 `docs/ROADMAP.md` 为准，不要伪造旧 Git 提交号、PDF 页码或正式评测结果。
