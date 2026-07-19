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
- PyMuPDF 的统一适配器接口；GROBID 与 MinerU 适配器边界。
- MySQL、Milvus、Neo4j 的 Compose 开发服务配置。

## 未从旧提交恢复、需要继续实现

- Alembic `0001–0006` 的原始迁移历史。
- GROBID TEI 与 MinerU JSON 的完整字段映射。
- 五篇真实 PDF 版面真值与解析器正式评测结果。

## R2 重建进展

- 已建立新的 `0001_reconstructed` → `0002_reconstructed_authority` 迁移链，没有冒充旧 `0001–0006` 历史。
- `0002_reconstructed_authority` 建立Paper、PaperSource、GoldDatasetVersion、PaperGoldRecord、NarrativeMove、Claim、ExperimentIntent、ArtifactRole、EvidenceAnchor、Limitation及闭合关系表。
- 已在SQLite验证空库升级、降级和再升级，并在Docker Desktop + WSL2的MySQL 8.4上完成真实迁移和外键检查。
- Gold CLI现已默认dry-run，只有显式`--commit`才按`paper_id + dataset_version`事务性写入或替换规范化派生对象；MySQL失败不会调用Neo4j，图失败返回`partial`并记录`failed`。
- 更高质量或更新PaperSource元数据的防覆盖规则仍待后续完成，不在本轮Step 2范围内。

继续开发时以 `docs/ROADMAP.md` 为准，不要伪造旧 Git 提交号、PDF 页码或正式评测结果。
