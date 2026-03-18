# 2026-3-18-search-analyze-workflow

## 背景
本轮目标：提升 kdump 已知漏洞识别稳定性，避免 `search_agent` 误判；同时让 `analyze_agent` 的结论更可落地、可解释。

## 问题复盘
### 1. search_agent 误判与噪声链接
- 现象：返回大量无关 URL（列表页、不相关 bug 页），已知漏洞场景下仍可能降级到 unknown。
- 关键原因：
  - 过度依赖一次性检索结果，缺少稳定复核机制。
  - 链接筛选与证据要求不一致，导致“看似命中、实际无关”。
  - 质量校验对措辞过于死板（例如只认 `not patched`）。

### 2. analyze_agent 结论偏推断
- 现象：能看到 `JFS_SBI(inode->i_sb)->ipimap` 相关问题，但会推断到“未初始化”而非“缺少检查”。
- 关键原因：
  - 证据落地约束不够（file/line 约束不足）。
  - 提示词允许了过强上游推断。

## 主要修改
### A. 工作流改造（search_agent）
- 从“规则快判”改为“主判定 + 复核”的语义化双阶段流程：
  1. 主判定 agent：完成检索、候选比对、初判。
  2. reviewer agent：二次语义审查（链接实体性、trace/症状一致性、patch 验证完整性）。
  3. 若复核不一致：触发重试；超过重试上限走保守降级策略。
- 目的：用流程稳定性替代硬编码规则。

### B. 提示词增强（search_prompt）
- 增加 check-agent / voting 指导，明确“先初判、再复核”。
- 强化输出要求：
  - unknown 必须包含 `Queries Tried`。
  - known 必须给可核验实体链接与复核依据。

### C. 质量门槛修复（search_agent）
- known 场景：链接必须是可核验实体（bug/commit/CVE）。
- patch 验证语义匹配扩展：支持 `missing fix` / `absence of the fix` / `unpatched` 等表达，避免措辞导致误伤。

### D. analyze_agent 约束增强
- 增加证据落地约束：至少一条 evidence 需可定位到 file/line 风格信息。
- 提示词中明确：
  - 不可无证据断言“上游初始化问题”。
  - 若无法证明，应写入 uncertainty，而非当作已确认根因。

## 文件变更
- `agents/search_agent.py`
- `agents/search_prompt.py`
- `agents/analyze_agent.py`
- `agents/analyze_prompt.py`
- `agents/prompt.py`（兼容导出）
- `agents/__init__.py`

## 验证
- 静态检查通过：`search_agent.py` / `search_prompt.py` / `analyze_agent.py` / `analyze_prompt.py` / `main.py` 无报错。
- 主流程接口保持不变：`main.py` 仍使用 `runSearchAgent()` + `runAnalyzeAgent()`。

## 当前结论
- 主要收益：
  - 明显减少“高噪声链接导致的 known bug 误报”。
  - 降低“因措辞差异导致的质量门槛误判”。
  - analyze 结论更偏证据驱动而非推断。
- 仍需持续验证：
  - 在更多 case 上观察 known/unknown 准确率。
  - 统计 reviewer 与主判定分歧率，评估工作流稳定性。

## 下一步建议
1. 增加回归脚本：固定 case 自动断言 known/unknown 结果与链接质量。
2. 增加指标记录：查询次数、重试次数、复核分歧率、最终准确率。
3. 引入 `strict/balanced` 模式开关：控制误报/漏报权衡。
