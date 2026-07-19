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
- Gold→MySQL 幂等写入和 Neo4j 同步的原实现。
- MySQL 文档结构读模型原实现。
- GROBID TEI 与 MinerU JSON 的完整字段映射。
- 五篇真实 PDF 版面真值与解析器正式评测结果。

继续开发时以 `docs/ROADMAP.md` 为准，先建立新的迁移基线，不要伪造旧 Git 提交号。

