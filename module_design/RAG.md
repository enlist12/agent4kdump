# RAG Design

## 目标
在 `search_agent -> analyze_agent` 流水线中新增经验增强层：
1. 每次根因分析成功后自动沉淀“可复用经验”。
2. 每次新分析前检索相关经验并结合 Linux 内核背景知识生成摘要。
3. 将摘要注入 `analyze_agent` 的输入，提升分析稳定性与可解释性。

## 当前落地（2026-04-09）
代码位置：
- `src/agents/rag/context_builder.py`
- `src/agents/analysis_process.py`
- `src/agents/analyze_agent.py`
- `main.py`

行为：
1. 分析前：
- 读取 crash report，抽取 `bug_type/kernel_version/module/function`。
- 优先调用 PageIndex（如果配置 `PAGEINDEX_API_KEY + PAGEINDEX_DOC_IDS`）检索历史经验。
- 若 PageIndex 不可用，退化到本地经验库（`cache/rag/experience_store.jsonl`）关键词检索。
- 可选调用 WebSearch 工具抓取 Linux 模块背景（文档/邮件列表/报告）。
- 由模型做二次总结，输出统一 RAG 上下文，注入 analyze prompt。

2. 分析后：
- 将成功 case 自动入库，保存：
  - 根因结论、trigger path、evidence、fix suggestion、confidence
  - taint chain
  - tool call 摘要
  - crash profile 与当次检索上下文
- 同时生成 markdown 经验卡片到 `cache/rag/experience_docs/`。

## PageIndex 接入建议
直接使用 Python SDK（`PageIndexClient`）做检索增强：
1. 预先把历史案例文档导入 PageIndex，拿到 `doc_id`。
2. 配置环境变量：
- `PAGEINDEX_API_KEY`
- `PAGEINDEX_DOC_IDS`（逗号分隔）
- 可选 `PAGEINDEX_MODEL`（默认 `PI-Retrieve`）
3. 分析前通过 SDK 调用 `client.chat_completions(...)`，传 `doc_id + query` 获取相关经验摘要。

## 难点与改进方向
1. 经验抽象质量：
- 建议增加“失败案例”与“低置信案例”标签，避免污染经验库。
- 增加主题标签（UAF/NULL/锁竞争/生命周期）和修复模式标签（check/add ref/reorder/free path）。

2. Linux 知识抓取准确性：
- 对来源打分：`docs.kernel.org` > `lore.kernel.org` > 其他博客。
- 必须记录内核版本约束；版本不匹配时在摘要里显式降权。

3. 检索精度：
- 当前本地回退为词重合检索，后续可替换为更强 hybrid（BM25 + dense + rerank）。
- PageIndex 返回可追加结构化要求（固定 JSON）以利于可控融合。
