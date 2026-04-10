# 2026-4-10 RAG + Kdump Refactor Log

## Q&A 1
- human ask:
  - pageindex 请直接使用 python sdk（参考官方 SDK 与示例），并且 agent 创建方式模仿项目已有的 create_agent 风格。
  - 同时指出：不要假设 pageindex 不存在；新增函数需要注释；经验存储不能生硬堆原始 tool_call/trigger_path；Linux 背景检索要偏技术背景而非漏洞背景；崩溃报告解析不能只依赖正则固定格式。

- agent act:
  - 将 PageIndex 接入改为 Python SDK：在 `src/agents/rag/context_builder.py` 中使用 `PageIndexClient` 与 `chat_completions(...)`。
  - 新增并统一了 RAG agent 化流程：
    - `summary_agent`（检索结果总结）
    - `profile_agent`（crash profile 提取，正则低信号时 LLM fallback）
    - `lessons_agent`（成功案例经验提炼）
  - 删除“PageIndex SDK 可能不存在”的分支假设，保持为依赖项强约束。
  - 为新增函数补充 docstring，说明职责与输入输出。
  - 经验沉淀从“原始堆砌”改为“经验化存储”：
    - 新增 `trace_summary`（tool 使用计数 + 示例参数 + taint outline）
    - 新增 `lessons`（`reusable_lessons` / `trigger_pattern` / `tool_strategy`）
    - markdown 经验卡片改为展示压缩摘要而非完整长轨迹。
  - Linux 背景检索查询改为模块技术导向（architecture / call chain / docs），避免 bug_type 驱动的漏洞信息偏置。
  - 保留正则快路径，同时新增 LLM 兜底的 profile 提取，提升 report 格式漂移下的鲁棒性。

## Q&A 2
- human ask:
  - 重写 `/root/agent4kdump/src/kdump_analyze/kdump.py`，在不改变功能的前提下让代码更优雅、鲁棒性更高、功能更好。

- agent act:
  - 对 `KdumpAnalysis` 做等价重构，保持外部接口与返回协议不变（`loadKdump/loadGDB/execute/getCrashReport/stop`）。
  - 改进点：
    - 移除 `from pwn import *`，改为显式导入。
    - 拆分内部函数（report 切片、addr2line 解析、日志文件准备、gdb 结果校验）。
    - `loadKdump` 改为参数数组启动进程，减少 shell 拼接风险。
    - `loadGDB` 增强错误日志与失败路径可观测性。
    - `addr2line` 调用从 `os.popen` 改为 `subprocess.run`（timeout/capture 更可控）。
    - 增加类型标注与注释，提升可维护性。
  - 语法校验通过：`python3 -m py_compile src/kdump_analyze/kdump.py`。
