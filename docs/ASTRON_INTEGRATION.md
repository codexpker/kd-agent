# 星辰 Agent、星火与 MaaS 正式集成

> 版本：2.0
> 更新日期：2026-07-22
> 状态：项目正式主链路，当前仅完成协议适配与 Mock，真实线上验收阻塞

## 1. 定位

官方规则允许使用其他工具，因此不把星辰误写为参赛准入条件。但科大讯飞是发榜方，官网重点推荐星辰 Agent 和
星火 MaaS，提交也支持 ServiceID。团队因此冻结它们为正式参赛主链路，而不是赛前才接入的装饰性适配。

`Vue → FastAPI → 星辰 Agent → 星火/科技文献模型、MaaS → 自研结构化工具`

Vue/FastAPI 保留是为了证据定位、结构化契约、安全、可视化和离线降级，不是绕过讯飞平台。

## 2. 能力分工

| 层 | 责任 | 禁止事项 |
| --- | --- | --- |
| 星辰 Agent | 意图识别、歧义澄清、上下文、三工作台编排、工具选择 | 越过工具直接构造论文事实、证据或实验结果 |
| 星火/科技文献模型 | 科研语言理解、基于工具结果的解释与报告组织 | 无EvidenceAnchor的核心结论、伪造引用、代写或编造创新点 |
| 星火 MaaS | TAD实验协议风险诊断微调与评测 | 通用论文生成、用测试集训练、只报告最优指标 |
| FastAPI工具网关 | Pydantic契约、白名单、证据门禁、超时/重试、审计、错误映射 | 从自然语言反解析核心数据或暴露密钥 |
| 自研科研工具 | PDF、混合检索、重排、叙事图、创新机会审计、引用一致性、TAD实验 | 将模型推断写成权威事实 |
| Vue | 正式Demo、对话、证据/PDF回跳、叙事图、实验曲线、运行态 | 将离线规则或Mock显示为正式平台调用 |

## 3. 当前真实状态

已实现：

- `backend/app/services/astron_workflow.py` 的星辰工作流 HTTP 客户端；
- 四个可由星辰注册的稳定工具接口：`search_papers`、`deconstruct_paper`、`compare_papers`、
  `diagnose_claim`；
- 工具统一响应契约、每次调用独立`trace_id`、开发种子/证据不足门禁；
- 非本地部署的Bearer鉴权门禁，未配置Token时返回`blocked_external_configuration`；
- 可导入的`docs/astron/agent-tools.openapi.yaml`、系统提示词和工作流节点设计；
- 服务端环境变量读取 API Key、Secret 和 Flow ID；
- 会话历史、`trace_id` 和模型回答 EvidenceAnchor 引用门禁；
- 鉴权形状、响应解析、无引用、错误和中断的 Mock 契约测试。

未实现/未验证：

- 团队账号上已发布的正式星辰工作流；
- 使用真实凭据的线上调用；
- 工具网关的公网HTTPS部署以及星辰平台真实注册/调用；
- 星火/科技文献模型的真实调用；
- MaaS数据集、微调、ServiceID、训练曲线与盲测对比；
- 脱敏调用日志、P50/P95、错误率和失败类型报告。

因此当前状态是 `blocked_external_configuration`，不得宣称“星辰正式链路已完成”。

前端和`GET /api/v1/demo/readiness`现在分别返回本地核心演示状态与`formal_chain_status`，本地就绪
不会再被显示成讯飞正式链路就绪。

## 4. P0-X1 最小真实链路

首次联调只使用已有 Anomaly Transformer 开发种子，验证平台和工具契约；它不得作为正式Gold成绩。

1. 用户输入“请解释 Anomaly Transformer 的核心主张”。
2. 星辰追问阅读目标（快速理解/实验复现/研究设计）。
3. 星辰调用`deconstruct_paper`，FastAPI返回结构化拆解与EvidenceAnchor。
4. 星火/科技文献模型只根据工具结果组织回答。
5. FastAPI拦截不存在的EvidenceAnchor和无证据核心结论。
6. Vue显示工作流/模型/工具版本、`trace_id`、证据状态和PDF回跳。
7. 模拟鉴权失败、超时和无证据，验证不伪成功。

## 5. 平台人工配置清单

需团队账号所有者在星辰/星火/MaaS官方平台完成，代码不能伪造：

- 创建并发布星辰工作流，记录不含密钥的工作流ID/版本；
- 配置星火或科技文献模型，记录官方模型名称与版本；
- 按OpenAPI契约注册FastAPI工具或插件，限制输入/输出字段；
- 将OpenAPI中的占位服务器地址替换为真实HTTPS地址，并在两端配置同一Bearer Token；
- 将API Key/Secret/Flow ID仅配置在服务端密钥管理中；
- 上传MaaS训练/验证集并启动微调，保存ServiceID和不含敏感数据的曲线/配置摘要；
- 使用三个正式典型问题运行端到端测试并导出脱敏证据。

可直接使用的配置材料：

- `docs/astron/agent-tools.openapi.yaml`
- `docs/astron/AGENT_SYSTEM_PROMPT.md`
- `docs/astron/WORKFLOW_NODES.md`

## 6. 契约与运行证据

所有Agent工具统一返回：

```json
{
  "result": {},
  "sources": [],
  "warnings": [],
  "evidence_status": "verified|partial|insufficient_evidence",
  "trace_id": "...",
  "tool_version": "...",
  "data_version": "..."
}
```

每次正式运行记录：星辰工作流版本、星火/MaaS模型或ServiceID、工具/数据/提示版本、`trace_id`、工具调用、延迟、降级、证据和用户确认。

## 7. 完成门禁

只有以下条件全部满足，路线图才可标记“讯飞正式主链路已完成”：

- 已发布星辰工作流，且完成最少真实链路；
- 3个典型问题均有真实请求ID和脱敏日志；
- 星火输出全部通过EvidenceAnchor门禁；
- MaaS有ServiceID、训练曲线、冻结盲测集和基础/微调对比；
- 记录P50/P95、错误率和至少3个失败案例；
- 断网、鉴权失败、超时、工具失败和证据不足不显示伪成功；
- 密钥不进入Git、浏览器、日志、测试快照或提交材料。
