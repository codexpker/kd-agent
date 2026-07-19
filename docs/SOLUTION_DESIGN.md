# 方案设计

## 分层

```text
Vue Workbench
  → FastAPI API
    → Research services
      → Gold dataset / MySQL
      → Milvus retrieval
      → Neo4j relation index
      → PDF parser adapters
      → Astron gateway (optional)
```

## 数据边界

- `DocumentStructure`：客观版面事实，包括章节、页码、图注、表格内容和正文引用。
- `PaperDeconstruction`：人工复核或模型辅助的科研语义，包括叙事动作、主张、实验意图、图表角色和边界。
- 两层只通过稳定 ID 和 EvidenceAnchor 连接，解析结果不自动升级为科研判断。

## 失败语义

- 未收录论文：404，不临时编造分析。
- Gold 快照无页码：返回 `page=null` 和 `source=gold_snapshot`。
- 未授权 PDF：允许本地预览，禁止持久化。
- MySQL 写入失败：不执行 Neo4j 同步。
- Neo4j 同步失败：明确标记 partial。

