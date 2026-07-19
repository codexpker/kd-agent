# Gold 标注与质控规范

## 最小字段

每篇论文至少标注 Problem、Research Gap、Hypothesis、Contribution、Claim、Experiment、Experiment Intent、Dataset、Baseline、Metric、Figure/Table Role、Evidence Anchor 和 Limitation。

## 流程

1. 标注员 A 与 B 独立标注。
2. 自动检查重复 ID、断裂引用、非连续叙事顺序和孤立证据。
3. 对不一致项进行仲裁。
4. 许可复核和证据页码复核完成后才可冻结。

## 状态语义

- `queued`：只进入待标注清单，不对外提供深度分析。
- `development_seed`：单人复核的工程开发数据，不可作为正式评测 Gold。
- `double_annotated`：双标完成，等待仲裁或许可复核。
- `frozen`：仲裁、许可与版本冻结全部完成。

## 证据要求

- 区分作者明确陈述和标注员推断。
- 保留反对证据与适用边界。
- 没有合法全文时不填写伪页码或长原文。
- 图表角色必须能连接至少一个 Claim 或明确标记为背景/流程说明。

