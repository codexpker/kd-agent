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
- 已审计Anomaly Transformer首篇真实版面Gold前置条件：初次审计无PDF；随后用户指定了被Git忽略的本地候选PDF，但尚未确认权利依据和来源记录。MySQL仍无该论文`PdfSource`，现有PaperSource仅允许元数据且未确认全文权利，也未登记第二标注员。案例清单同时标记`needs_authorized_pdf`与`needs_second_annotator`。已提供授权后哈希/来源记录、独立空白标注、候选结果规范化导入、字段级差异和全未决仲裁模板；在合法PDF、双人标注和仲裁到位前不生成或声称真实Gold。

## R3 重建进展

- 需要全文权利确认、第二标注员和仲裁员的版面Gold工作已按排期后推；5篇TAD Gold和正式多论文比较矩阵仍未完成，不能用开发种子替代。
- 已实现基于本地已检索论文和版本化结构规则的 Research Opportunity Candidate API。规则覆盖八类研究缺口，每项输出支持/冲突证据及完整EvidenceAnchor、不同论文覆盖、检索年份范围、可复算置信度依据、人工确认事项、适用条件和禁止结论。
- 查询计划显式报告纳入/排除规则、逐论文决定与可能遗漏；只有`double_annotated/frozen`且引用已核验EvidenceAnchor的论文可以参与。未达到最少不同论文覆盖时返回`insufficient_evidence`，不会用合成记录或排队论文补足。
- Vue工作台展示证据列表与线性研究进展时间线，不使用知识图谱大球。八类规则正向路径目前只由明确标记的`synthetic-opportunity-fixture`测试验证；真实离线清单当前为5篇注册、0篇纳入，因此没有真实候选或真实研究机会成绩。
- 已建立候选驱动的研究教练框架：用户自行提交研究问题、可证伪假设和拟议方法，服务端重新校验候选仍属于当前证据查询，再生成主实验、基线、消融、敏感性、鲁棒性、失败案例及闭合图表计划。所有规划项标记为`system_planning_inference`并回链EvidenceAnchor，只定义变量、输出Schema、反驳条件和证据边界，不生成实验数据或结果。当前真实语料仍会在候选门禁处返回`insufficient_evidence`；正向路径仅由合成fixture验证，尚无真实研究教练质量成绩。

## R4 重建进展

- 已实现独立于R3候选的Project Claim录入与版本化：研究问题、假设、拟议方法、目标场景和已有结果保持用户原文，分别标记`user_supplied`/`user_reported`，已有结果不得标记为已核验。
- 新增`0004_project_claim_versions`及内存/MySQL双存储。Claim版本不可变，以父版本、内容SHA-256和乐观锁串联；规则诊断和用户编辑保存为独立修订。默认离线模式只用进程内存，不能把它描述为跨重启持久化。
- 固定规则规划器输出主实验、强基线、公平比较、消融、参数敏感性、鲁棒性、效率和失败案例八项证据需求，每项显式包含Claim原文、变量、输出、推荐图表及证明边界。语言组织当前也是确定性模板，未接入模型；可行性与创新性均保持`not_assessed`。
- Vue工作区支持Claim版本历史、合成TAD示例和诊断修订。该示例不含实验结果，不是研究结论或真实质量成绩。
- 已新增`0005_experiment_artifact_plans`，把一个或多个稳定Claim版本及其最新诊断修订转成八类ExperimentPlan和闭合ArtifactPlan。每次生成或用户编辑都会追加计划修订；MySQL关系表显式保存Experiment/Artifact到Claim版本的链接，离线默认仍只保存在进程内存。
- 实验计划保留RQ/Hypothesis原文，结构化记录Dataset、Baseline、Variables、Controls、Metrics、ExpectedArtifact、Boundary和Status。图表计划记录Figure/Table选择理由、轴或行列、数据字段、Claim链接与常见误读；不含结果值或预期提升数值字段。
- 固定质量规则逐实验检查强基线缺失、数据泄漏、不公平设置、指标不一致和过度结论。自动生成时未知数据集和强基线明确保留为待用户选择，其中强基线检查会保持警告；`confirmed/modified/rejected`状态是用户决定，不等于实验已执行或Claim已验证。

继续开发时以 `docs/ROADMAP.md` 为准，不要伪造旧 Git 提交号、PDF 页码或正式评测结果。
