# Search Agent 改进 - 2026-03-12

## 问题背景
1. **Syzbot 标题问题**：Syzbot 报告的标题经常使用 call trace 中间层的语义丰富的函数（如 `kobject_cleanup`），而不是 RIP 位置的底层函数（如 `list_del`）
2. **误报问题**：Agent 有时声称找到了匹配，但实际验证后发现不是同一个漏洞

## 改进方案

### 1. 提示词改进 (prompt.py)

#### 1.1 Phase 2 查询策略增强
- **新增"语义函数"概念**：识别 call trace 中描述操作意图的函数（cleanup, release, free, init 等）
- **查询优先级调整**：
  - **Query 1（最高优先级）**：`"<panic_type> in <semantic_function>" site:syzkaller.appspot.com`
    - 例如：`"general protection fault in kobject_cleanup" site:syzkaller.appspot.com`
    - 直接匹配 Syzbot 标题格式
  - Query 2-6：渐进式降低特异性
- **从 3-4 个查询增加到 5-6 个查询**，覆盖更多搜索策略
- **要求至少尝试 5-8 种查询组合**才能得出"无匹配"结论

#### 1.2 Phase 3 验证强化
- **量化评分系统**：
  - Call Trace Match: 30% 权重
  - Root Cause Match: 40% 权重（最重要）
  - Patch Verification: 20% 权重
  - Falsification Test: 10% 权重
- **明确决策逻辑**：
  - 总分 < 25/40：不匹配
  - 总分 25-29/40 且 Root Cause < 7：不确定→继续搜索
  - 总分 ≥ 30/40 且 Root Cause ≥ 7：确认匹配

#### 1.3 新增 Phase 4：Self-Verification（自我验证）
强制要求在报告前回答 4 个检查问题：
1. 能否明确陈述两个 crash 的根本原因？
2. **是否对比了源码和补丁？** ✨ 核心逻辑：
   - 如果当前源码**已经包含了补丁的修改** → **不是同一个漏洞**（bug 已修复）
   - 如果当前源码**不包含补丁**（仍然是 vulnerable 状态）→ 可能是同一个漏洞
   - 必须明确对比源码文件，不能只看 GDB
3. 是否考虑了其他可能的解释？
4. 各检查点的量化评分

要求提供量化评分，总分 < 30/40 不允许报告为已知漏洞。

**重要改进**：去掉置信度评分，改为**强制二元决策**（True/False），不允许"不确定"或"可能"。

### 2. 代码改进 (search_agent.py)

#### 2.1 增强数据模型
```python
class KnownBugAnalysisResult(BaseModel):
    is_known_bug: bool  # 强制二元决策，不允许模糊地带
    evidence: str  # 必须包含 4-checkpoint 评分
    matched_url: Optional[List[str]]
    extra_info: Optional[str]
    verification_details: Optional[str]  # 新增：Phase 4 自检答案，必须包含源码对比结果
```

**关键改动**：
- **移除 `confidence_score`**：不提供置信度，强制 Agent 做出明确决策
- 如果不确定，必须报告 `is_known_bug=False`

#### 2.2 结果质量验证函数
```python
def verify_result_quality(result) -> tuple[bool, str]:
```
如果声称找到匹配（`is_known_bug=True`），必须满足：
- 提供 `matched_url`
- 提供详细的 `verification_details`（至少 100 字符）
- `evidence` 中包含 "Call Trace" 和 "Root Cause" 关键词
- **必须包含源码对比结果**：证明当前源码**不包含补丁**（仍然是 vulnerable 状态）

如果源码已经包含补丁，质量检查会直接拒绝该结果。

#### 2.3 重试机制
```python
def runSearchAgent(max_retries: int = 2):
```
- 默认最多重试 2 次（共 3 次尝试）
- 每次重试时向 agent 反馈上次失败的原因
- 如果 3 次尝试后仍然声称是已知漏洞但质量不达标，自动降级为 "unknown bug"

## 使用效果

### 对 Syzbot 标题问题
- 现在会优先搜索：`"general protection fault in kobject_cleanup"`
- 而不是仅搜索底层函数：`"list_del kobject_cleanup"`
- 命中率应显著提升

### 对误报问题
- 4 层防护机制：
  1. **Prompt 中的 Phase 3 Checkpoint 3**：强制对比源码和补丁
     - 如果源码已包含补丁 → 自动判定为不匹配
  2. **Prompt 中的 Phase 4 强制自检**：二元决策逻辑
     - 移除置信度评分，强制回答 True/False
     - 不确定时默认为 False
  3. **代码层面的 `verify_result_quality`**：质量门槛检查
     - 检查是否包含源码对比证据
  4. **不达标时的自动重试**：最多 3 次尝试
- 只有同时通过 4 层检查才会报告为已知漏洞

**关键逻辑**：
```
如果当前源码已经包含了补丁的修改 
  → 说明这个漏洞已经被修复了
  → 当前 crash 不可能是这个已知漏洞
  → 报告 is_known_bug=False
```

## 配置建议

可以在调用时调整重试次数：
```python
result = runSearchAgent(max_retries=3)  # 最多 4 次尝试
```

## 后续优化方向

1. **可能需要监控的指标**：
   - 平均查询次数
   - 重试率
   - 误报率和漏报率
   
2. **如果误报仍然存在**：
   - 强化源码对比检查：要求提供具体的源码行号和内容
   - 添加更多补丁验证测试用例
   - 考虑引入源码 diff 工具自动对比

3. **核心防护逻辑**：
   ```
   找到候选漏洞 → 获取补丁 → 对比当前源码
   ├─ 源码已包含补丁 → is_known_bug=False (已修复，不是这个漏洞)
   └─ 源码不包含补丁 → 继续验证 → 通过其他 checkpoint → is_known_bug=True
   ```
# 代码错误修复
1. CodeQuery文件路径提取错误
