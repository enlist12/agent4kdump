# Search / Analyze / RAG 改造说明

## 1. 背景

这次改造主要针对三个问题：

1. `search agent` 能形成 query，但对 `syzbot` 已知漏洞的检出率不稳定。
2. `analyze agent` 最终输出过于摘要化，缺少源码位置、传播链和可执行的修复示意。
3. 经验库更像归档摘要，缺少对后续分析的“检查顺序引导”和“适用边界”。

同时，在实现过程中暴露出一个工程问题：

- 结构化输出 schema 过于严格，LLM 一旦漏填某个字段，会在 Pydantic 解析阶段直接失败，导致流程中断，来不及进入质量检查和重试逻辑。

## 2. 本次代码改动

### 2.1 Search Agent

涉及文件：

- `src/agents/search_prompt.py`
- `src/agents/search_agent.py`
- `src/agents/schemas.py`

核心变化：

1. 把搜索 workflow 改成“先提取 crash fingerprint，再执行 query plan”。
2. 要求模型输出结构化检索信息，而不是只输出一段文字说明。
3. 强化质量检查，优先检查：
   - 是否有 `crash_fingerprint`
   - 是否记录了 `queries_tried`
   - 是否有 `candidate_matches`
   - 是否覆盖了 syzbot / patch 查询
4. reviewer 也改为复核结构化字段，而不仅仅看 `evidence`。

新增结构化字段：

- `crash_fingerprint`
  - `panic_header`
  - `fault_type`
  - `crash_function`
  - `top_frames`
  - `subsystem`
  - `source_path`
  - `access_type`
  - `title_candidates`
  - `keywords`
- `queries_tried`
  - `query`
  - `target_domains`
  - `purpose`
  - `observed_result`
- `candidate_matches`
  - `url`
  - `title`
  - `source`
  - `relevance`
  - `verdict`
  - `reason`
- `rejection_summary`
- `final_reasoning`

### 2.2 Analyze Agent

涉及文件：

- `src/agents/prompt.py`
- `src/agents/schemas.py`

核心变化：

1. 最终报告不再只有高层摘要字段。
2. prompt 强制要求给出 crash site、root-cause chain、source locations、fix candidates。
3. 支持输出 `git diff` 风格的 `patch_sketch`，明确标记为 demo patch。
4. RAG prompt 明确要求把“历史经验中的假设”和“当前源码已证实事实”分开。

新增结构化字段：

- `crash_site`
  - `file`
  - `function`
  - `line`
  - `statement`
  - `invalid_object`
- `root_cause_chain`
- `source_locations`
- `fix_candidates`
- `patch_sketch`
- `verification_todo`

### 2.3 Main 输出展示

涉及文件：

- `main.py`

核心变化：

1. `search` 结果增加分块展示：
   - Crash Fingerprint
   - Queries Tried
   - Candidate Matches
   - Rejection Summary / Final Reasoning
2. `analyze` 结果增加分块展示：
   - Crash Site
   - Root Cause Chain
   - Source Locations
   - Fix Candidates
   - Patch Sketch
   - Verification TODO

### 2.4 RAG / 经验库

涉及文件：

- `src/agents/rag/context_builder.py`

核心变化：

1. 经验蒸馏从“summary + reusable lessons”改成“分析引导型经验卡”。
2. 检索文本不再只堆 `root_cause` 和 `evidence`，而是补充：
   - crash site
   - root cause chain signature
   - reusable playbook
   - applicability / non-applicability
   - fix patterns
   - evidence boundary
3. RAG 注入上下文改成固定五段：
   - Similar Case Signatures
   - Transferable Analysis Playbook
   - Non-Transferable / Mismatch Warnings
   - Suggested Checks For This Crash
   - Confidence Notes

新的经验卡重点字段：

- `case_signature`
- `reusable_playbook`
- `applicability`
- `non_applicability`
- `fix_patterns`
- `evidence_boundary`
- `tool_strategy`

## 3. 结构化输出解析问题与当前处理

实现后已遇到两类典型问题：

1. `crash_fingerprint.subsystem` 缺失，导致 `KnownBugAnalysisResult` 解析失败。
2. `candidate_matches[*].source` 缺失，导致 `KnownBugAnalysisResult` 解析失败。

当前处理原则：

- 对“模型容易漏填但不影响整体语义”的字段，schema 放宽为可选或提供默认值。
- 对真正关键的字段，不在 Pydantic 解析阶段卡死，而是在 `verify_result_quality()` 里做质量门禁，让 agent 有机会重试。

当前已经放宽的字段包括：

- `CrashFingerprint.subsystem`
- `CrashFingerprint.panic_header`
- `CrashFingerprint.fault_type`
- `CrashFingerprint.crash_function`
- `SearchQueryRecord.query`
- `SearchQueryRecord.purpose`
- `SearchQueryRecord.observed_result`
- `SearchCandidateMatch.url`
- `SearchCandidateMatch.title`
- `SearchCandidateMatch.source`
- `SearchCandidateMatch.relevance`
- `SearchCandidateMatch.verdict`
- `SearchCandidateMatch.reason`

这样做的目的不是降低要求，而是把失败从“解析崩溃”转成“质量不足后重试”。

## 4. 当前已知问题

### 4.1 Search 质量门槛较高

当前质量检查要求：

- `queries_tried` 至少 8 条
- 至少 3 条 syzbot/syzkaller 查询
- 至少 2 条 patch/commit 查询
- 必须有 title-oriented query
- 必须有 `candidate_matches`

这会带来两个结果：

1. 优点：能强迫 agent 不要草率地给出“unknown”。
2. 风险：如果模型没有稳定按 schema 填全，可能连续重试失败。

### 4.2 Search prompt 已经强化，但还不保证模型稳定执行

`search_prompt.py` 现在已经更强调 fingerprint 和 coverage，但 LangChain 结构化输出仍依赖模型自觉填字段。后续如果要继续提升稳定性，优先考虑：

1. 增加一个“query planning”中间 schema，而不是一步生成最终 `KnownBugAnalysisResult`。
2. 先用一个 agent 只产出 fingerprint + query plan。
3. 再由第二个 agent 执行搜索并填最终 verdict。

### 4.3 Analyze 输出能力已扩展，但还依赖模型是否充分利用新字段

schema 和 prompt 已经支持更强输出，但如果模型仍然偷懒，可能会返回：

- `root_cause` 比较详细
- 但 `root_cause_chain`、`fix_candidates`、`patch_sketch` 仍偏空或保守

这类问题下一步要靠：

1. 增加结果质量检查
2. 或把 root cause 结果拆成“先源码链路，再最终总结”

## 5. 后续建议

### 5.1 Search 阶段

建议下一步优先做：

1. 拆成两阶段：
   - fingerprint / query planning
   - search execution / verification
2. 在 retry 提示词中明确要求：
   - 如果上一轮少于 8 条 query，下一轮必须补齐
   - 如果缺少 `candidate_matches`，下一轮必须至少输出 2 个候选
3. 如有必要，可在 `search_agent.py` 中加入更强的“失败原因回灌模板”。

### 5.2 Analyze 阶段

建议下一步补：

1. 对 `RootCauseAnalysisResult` 做质量检查：
   - `crash_site` 是否为空
   - `root_cause_chain` 是否至少 2 步
   - `fix_candidates` 是否至少 1 个
2. 对 `patch_sketch` 增加最小格式校验，至少包含：
   - `DEMO PATCH ONLY`
   - `diff --git`
   - `@@`

### 5.3 经验库

建议后续持续观察：

1. 新格式经验卡是否真的能提升 analyze 阶段的起手方向。
2. 哪些字段最有召回价值：
   - source path
   - invalid object
   - crash function
   - propagation chain verbs
3. 是否需要把经验库拆成两类：
   - 分析引导经验
   - 修复模式经验

## 6. 结论

这次改造已经完成了三个方向的基础设施升级：

1. `search` 从“自由搜索”转向“fingerprint + coverage + candidate verification”。
2. `analyze` 从“摘要报告”转向“源码定位 + 传播链 + patch sketch”。
3. `RAG` 从“经验归档”转向“分析引导型经验卡”。

但当前最需要继续打磨的是：

- 让 `search` 的结构化输出更稳定
- 让失败优先走“质量检查重试”，而不是 schema 解析报错
- 视情况把 `search` 再拆成更稳的两阶段工作流
