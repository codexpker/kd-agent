# API 契约

## 健康检查

`GET /api/v1/healthz`

## 演示检索

`POST /api/v1/tools/search`

```json
{"query": "Transformer anomaly detection", "limit": 5}
```

返回首批论文队列；只有 `has_gold=true` 的论文可打开深度拆解。

## 论文逆向工程

`POST /api/v1/tools/paper-deconstruct/{paper_id}`

未收录或未完成审核的论文返回 404，不调用模型生成临时伪分析。

## 文档结构

`GET /api/v1/papers/{paper_id}/document-structure`

`source=gold_snapshot` 表示语义快照，页码等版面字段可能为空；未来 MySQL 解析结果使用 `source=parsed_pdf`。

